# backend/app/services/agents/base.py
import json
from typing import Dict, Any, List, Optional, Callable

from ..llm_adapter import llm_adapter as _global_adapter
from .tools import get_tool_schemas, _TOOL_REGISTRY
from .events import emit_event, set_callback, clear_callback
from .guards import (
    TAINTING_TOOLS, set_turn_context, get_turn_context, clear_turn_context,
    mark_tainted, gate_tool_call, render_tool_result,
)
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
            # chat.py, so the agent has continuity across separate requests.
            self.history.extend(history_messages)

    def _trim_history(self):
        """
        Keep the system prompt plus the most recent messages.

        The system prompt (index 0) always survives. The subtle part: a 'tool'
        message is only valid directly after the assistant message that asked
        for it. If the cut lands between the two, the history would start with
        an orphaned tool message and the API rejects the request with a 400.
        So after cutting, drop any tool messages left at the front.
        """
        if len(self.history) <= MAX_HISTORY:
            return
        system = self.history[0]
        tail = self.history[-(MAX_HISTORY - 1):]
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]
        self.history = [system] + tail

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

        # Code-level gate (see guards.py). Money movement, shell commands and
        # GitHub writes only run if the user has approved them in their own
        # chat message. This sits in front of the tool, so the model cannot
        # bypass it by being persuaded, tricked, or by skipping a prompt rule.
        decision = gate_tool_call(tool_name, args)
        if not decision.allowed:
            return decision.result
        args = decision.args

        try:
            print(f"  [{self.role_config['name']}] → {tool_name}({list(args.keys())})")
            return func(**args)
        except Exception as e:
            print(f"  [{self.role_config['name']}] ✗ {tool_name} raised: {e}")
            return {"error": f"{tool_name} failed: {e}"}

    def run(self, user_input: str, event_callback: Optional[Callable] = None) -> str:
        """
        ReAct loop. Returns the final text response.

        The top-level agent (the Supervisor) opens the "turn context" that
        tracks whether this request has read untrusted content. Specialists
        started through delegate_to run in the same thread, see the same
        context, and leave closing it to the agent that opened it.
        """
        owns_turn_context = False
        text_response = ""
        try:
            if event_callback is not None:
                set_callback(event_callback)
            if self.user_id is not None and get_turn_context() is None:
                set_turn_context(self.user_id, self.conversation_id)
                owns_turn_context = True

            self.history.append({"role": "user", "content": user_input})
            tools    = get_tool_schemas(self.role_config["tools"])
            max_iter = self.role_config["max_iterations"]

            seen_call_signatures: Dict[str, int] = {}
            force_text_only_next = False

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

                    # External content just entered the context: from here on,
                    # shell commands and GitHub writes in this request need approval.
                    if tc["name"] in TAINTING_TOOLS and "error" not in result:
                        mark_tainted(tc["name"])

                    emit_event("tool_result", {
                        "agent":   self.role_config["name"],
                        "tool":    tc["name"],
                        "success": "error" not in result,
                        "preview": str(result)[:150],
                    })

                    # Truncate, wrap as untrusted data, flag instruction-like text.
                    self.history.append({
                        "role":         "tool",
                        "tool_call_id": tc["id"],
                        "name":         tc["name"],
                        "content":      render_tool_result(tc["name"], result, MAX_RESULT_CHARS),
                    })
                    if self.conversation_id:
                        self._log_episode(tc["name"], tc["arguments"], result, reasoning=text_response)

            print(f"[{self.role_config['name']}] Hit max iterations ({max_iter})")
            return text_response or "I reached the maximum number of steps without completing this task."

        finally:
            if event_callback is not None:
                clear_callback()
            if owns_turn_context:
                clear_turn_context()

    def _log_episode(self, action: str, metadata: Dict, result: Dict, reasoning: str = ""):
        """
        Audit trail of every tool call. The model's own reasoning text is
        stored under '_reasoning' so that after an incident you can see not
        just WHAT it did but what it was thinking when it did it.
        """
        try:
            db = SessionLocal()
            meta = dict(metadata)
            if reasoning:
                meta["_reasoning"] = reasoning[:500]
            db.add(Episode(
                conversation_id=self.conversation_id,
                agent_name=self.role_config["name"],
                action=action,
                meta_data=meta,
                result=result,
                feedback=None
            ))
            db.commit()
        except Exception as e:
            print(f"[DB] Episode log failed: {e}")
        finally:
            db.close()