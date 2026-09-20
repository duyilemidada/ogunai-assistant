# backend/app/services/llm_adapter.py
import json
from typing import List, Dict, Any
from abc import ABC, abstractmethod
from ..config import settings


class BaseLLMAdapter(ABC):
    @abstractmethod
    def invoke_with_tools(
        self,
        messages: List[Dict],
        tools: List[Dict],
        temperature: float = 0.4,
        tool_choice: str = "auto"
    ) -> Dict[str, Any]:
        pass


class OpenAICompatibleAdapter(BaseLLMAdapter):
    def __init__(self):
        try:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY
            )
            self.model = settings.LLM_MODEL
        except ImportError:
            raise ImportError("Run: pip install openai")

    def invoke_with_tools(
        self,
        messages: List[Dict],
        tools: List[Dict],
        temperature: float = 0.4,
        tool_choice: str = "auto"
    ) -> Dict[str, Any]:
        effective_tool_choice = tool_choice if tools else None

        for attempt in (1, 2):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=settings.LLM_MAX_TOKENS,   # ← caps output, avoids OTPM 429s
                    tools=tools if tools else None,
                    tool_choice=effective_tool_choice
                )
                msg = response.choices[0].message
                tool_calls = []

                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append({
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": args
                        })

                return {"text": msg.content or "", "tool_calls": tool_calls}

            except Exception as e:
                err = str(e)
                print(f"[LLM ADAPTER] Attempt {attempt} failed: {err[:300]}")
                if attempt == 1 and "tool_use_failed" in err:
                    effective_tool_choice = "auto"
                    messages = messages + [{
                        "role": "user",
                        "content": "Your previous tool call was malformed. Use the exact JSON schema provided — no other format."
                    }]
                    continue
                return {"text": f"LLM error: {e}", "tool_calls": []}


llm_adapter = OpenAICompatibleAdapter()