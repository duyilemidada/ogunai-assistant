# backend/app/services/agents/base.py
import json
from typing import Dict, Any, List, Optional, Callable

from ..llm_adapter import llm_adapter as _global_adapter
from .tools import get_tool_schemas, _TOOL_REGISTRY
from .events import emit_event, set_callback, clear_callback
from ...database import SessionLocal
from ...models import Episode

MAX_HISTORY      = 20
MAX_RESULT_CHARS = 2000


class OgunAIAgent:
    def __init__(
        self,
        role_config: Dict,
        llm_adapter=None,
        user_id: int = None,
        conversation_id: int = None,
        history_messages: Optional[List[Dict[str, str]]] = None,
    ):
        self.role_config     = role_config
        self.llm             = llm_adapter if llm_adapter is not None else _global_adapter
        self.user_id         = user_id
        self.conversation_id = conversation_id
        self.history: List[Dict] = [
            {"role": "system", "content": role_config["system_prompt"]}
        ]
        if history_messages:
            # Prior turns from this SAME conversation, loaded from the DB by
            # chat.py, so the agent has continuity across separate HTTP
            # requests. Without this, every message starts from zero —
            # which is the exact bug behind "I don't remember what we
            # discussed a moment ago" within one unbroken chat thread.
            self.history.extend(history_messages)

    def _trim_history(self):
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[:1] + self.history[-(MAX_HISTORY - 1):]

    def _truncate_result(self, result_str: str) -> str:
        if len(result_str) <= MAX_RESULT_CHARS:
            return result_str
        return (
            result_str[:MAX_RESULT_CHARS]
            + f"\n... [truncated — {len(result_str) - MAX_RESULT_CHARS} chars omitted]"
        )

    def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name not in self.role_config["tools"]:
            return {
                "error": (
                    f"Permission denied: '{self.role_config['name']}' "
                    f"cannot use '{tool_name}'. "
                    f"Allowed: {self.role_config['tools']}"
                )
            }
        if tool_name not in _TOOL_REGISTRY:
            return {"error": f"Unknown tool: '{tool_name}'."}

        func = _TOOL_REGISTRY[tool_name]
        if 'user_id' in func.__code__.co_varnames[:func.__code__.co_argcount]:
            args['user_id'] = self.user_id

        try:
            print(f"  [{self.role_config['name']}] → {tool_name}({list(args.keys())})")
            return func(**args)
        except Exception as e:
            print(f"  [{self.role_config['name']}] ✗ {tool_name} raised: {e}")
            return {"error": f"{tool_name} failed: {e}"}

    def run(self, user_input: str, event_callback: Optional[Callable] = None) -> str:
        if event_callback is not None:
            set_callback(event_callback)

        self.history.append({"role": "user", "content": user_input})
        tools    = get_tool_schemas(self.role_config["tools"])
        max_iter = self.role_config["max_iterations"]

        seen_call_signatures: Dict[str, int] = {}
        force_text_only_next = False

        try:
            for i in range(max_iter):
                self._trim_history()
                print(f"[{self.role_config['name']}] Iteration {i+1}/{max_iter}")

                emit_event("thinking", {
                    "agent":          self.role_config["name"],
                    "iteration":      i + 1,
                    "max_iterations": max_iter,
                })

                tools_for_this_call = [] if force_text_only_next else tools
                force_text_only_next = False

                llm_response  = self.llm.invoke_with_tools(self.history, tools_for_this_call, temperature=0.4)
                text_response = llm_response.get("text", "")
                tool_calls    = llm_response.get("tool_calls", [])

                print(f"  THOUGHT    : {text_response[:200]!r}")
                print(f"  TOOL CALLS : {[tc['name'] for tc in tool_calls]}")

                if len(tool_calls) > 1:
                    print(f"  [CAP] {len(tool_calls)} calls → first only.")
                    tool_calls = tool_calls[:1]

                if tool_calls:
                    emit_event("tool_call", {
                        "agent": self.role_config["name"],
                        "tool":  tool_calls[0]["name"],
                        "args":  {k: str(v)[:80] for k, v in tool_calls[0]["arguments"].items()},
                    })

                assistant_msg: Dict = {"role": "assistant", "content": text_response}
                if tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id":   tc["id"],
                            "type": "function",
                            "function": {
                                "name":      tc["name"],
                                "arguments": json.dumps(tc["arguments"])
                            }
                        }
                        for tc in tool_calls
                    ]
                self.history.append(assistant_msg)

                if not tool_calls:
                    emit_event("agent_done", {
                        "agent":   self.role_config["name"],
                        "preview": text_response[:200],
                    })
                    return text_response

                for tc in tool_calls:
                    signature = f"{tc['name']}::{json.dumps(tc['arguments'], sort_keys=True, default=str)}"
                    seen_call_signatures[signature] = seen_call_signatures.get(signature, 0) + 1

                    if seen_call_signatures[signature] > 1:
                        print(f"  [DEDUPE] Repeated identical call to {tc['name']} — blocking re-execution.")
                        result = {
                            "error": (
                                "You already called this exact tool with these exact arguments earlier "
                                "in this conversation. The result will not change — do not call it again. "
                                "Answer the user's question now using the information already returned above."
                            )
                        }
                        force_text_only_next = True
                    else:
                        result = self._execute_tool(tc["name"], tc["arguments"])

                    result_str = self._truncate_result(json.dumps(result, indent=2))

                    emit_event("tool_result", {
                        "agent":   self.role_config["name"],
                        "tool":    tc["name"],
                        "success": "error" not in result,
                        "preview": str(result)[:150],
                    })

                    self.history.append({
                        "role":         "tool",
                        "tool_call_id": tc["id"],
                        "name":         tc["name"],
                        "content":      result_str
                    })
                    if self.conversation_id:
                        self._log_episode(tc["name"], tc["arguments"], result)

            print(f"[{self.role_config['name']}] Hit max iterations ({max_iter})")
            return text_response or "I reached the maximum number of steps without completing this task."

        finally:
            if event_callback is not None:
                clear_callback()

    def _log_episode(self, action: str, metadata: Dict, result: Dict):
        try:
            db = SessionLocal()
            db.add(Episode(
                conversation_id=self.conversation_id,
                agent_name=self.role_config["name"],
                action=action,
                meta_data=metadata,
                result=result,
                feedback=None
            ))
            db.commit()
        except Exception as e:
            print(f"[DB] Episode log failed: {e}")
        finally:
            db.close()