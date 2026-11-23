"""Model providers behind one small interface.

Messages use a neutral format so the agent never depends on one vendor:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...


class LLMError(RuntimeError):
    pass


# --- Anthropic -----------------------------------------------------------


class AnthropicLLM:
    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, timeout: float = 30.0, client: httpx.Client | None = None):
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self.model = model
        self.client = client or httpx.Client(timeout=timeout)
        self.headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    @staticmethod
    def to_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                out.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                # Consecutive tool results go into one user turn.
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def complete(self, system, messages, tools) -> LLMResponse:
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system,
            "messages": self.to_messages(messages),
            "tools": [
                {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                for t in tools
            ],
        }
        resp = self.client.post(self.url, headers=self.headers, json=payload)
        if resp.status_code >= 400:
            raise LLMError(f"Anthropic API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        text_parts, calls = [], []
        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                calls.append(ToolCall(block["id"], block["name"], block.get("input") or {}))
        usage = data.get("usage", {})
        return LLMResponse(
            "".join(text_parts).strip(), calls, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        )


# --- OpenAI --------------------------------------------------------------


class OpenAILLM:
    url = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, model: str, timeout: float = 30.0, client: httpx.Client | None = None):
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self.model = model
        self.client = client or httpx.Client(timeout=timeout)
        self.headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}

    @staticmethod
    def to_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m["tool_calls"]
                    ]
                out.append(msg)
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        return out

    def complete(self, system, messages, tools) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self.to_messages(system, messages),
            "tools": [{"type": "function", "function": t} for t in tools],
        }
        resp = self.client.post(self.url, headers=self.headers, json=payload)
        if resp.status_code >= 400:
            raise LLMError(f"OpenAI API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        message = data["choices"][0]["message"]
        calls = []
        for tc in message.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc["id"], tc["function"]["name"], args))
        usage = data.get("usage", {})
        return LLMResponse(
            (message.get("content") or "").strip(),
            calls,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )


# --- Mock ----------------------------------------------------------------

ORDER_ID = re.compile(r"\bORD-\d{4}\b", re.IGNORECASE)
CONTEXT_LINE = re.compile(r"^\[(\d+)\] \((?P<source>[^)]+)\) (?P<title>[^:]+): (?P<text>.+)$", re.MULTILINE)


class MockLLM:
    """Deterministic stand-in so the project runs and tests pass without an API key.

    It follows the same contract as the real providers: it reads the numbered
    context in the system prompt, cites it, and asks for tools by name.
    """

    def __init__(self) -> None:
        self._n = 0

    def _id(self) -> str:
        self._n += 1
        return f"mock_{self._n}"

    def complete(self, system, messages, tools) -> LLMResponse:
        last = messages[-1]
        if last["role"] == "tool":
            return LLMResponse(
                text=self._after_tool(last["name"], json.loads(last["content"])), output_tokens=40
            )

        question = last["content"]
        order = ORDER_ID.search(question)
        lowered = question.lower()
        if order and "refund" in lowered:
            args = {"order_id": order.group(0).upper(), "reason": question[:200]}
            return LLMResponse(tool_calls=[ToolCall(self._id(), "issue_refund", args)], output_tokens=30)
        if order:
            args = {"order_id": order.group(0).upper()}
            return LLMResponse(tool_calls=[ToolCall(self._id(), "lookup_order", args)], output_tokens=20)

        context = CONTEXT_LINE.search(system)
        if context:
            n, text = context.group(1), context.group("text")
            first_sentences = " ".join(re.split(r"(?<=[.!?])\s+", text)[:2])
            return LLMResponse(
                text=f"{first_sentences} [{n}]", input_tokens=len(system) // 4, output_tokens=60
            )

        args = {"subject": question[:80], "summary": question[:500], "priority": "normal"}
        return LLMResponse(tool_calls=[ToolCall(self._id(), "create_ticket", args)], output_tokens=30)

    @staticmethod
    def _after_tool(name: str, result: dict[str, Any]) -> str:
        if result.get("error"):
            return f"I couldn't complete that: {result['error']} Could you check the details and try again?"
        if result.get("status") == "pending_approval":
            return (
                "I've sent this to a team member for approval. "
                f"You'll get an update once it's reviewed (reference {result['approval_id']})."
            )
        if name == "lookup_order":
            o = result["order"]
            eta = f", expected delivery {o['eta']}" if o.get("eta") else ""
            return f"Order {o['id']} is {o['status']}{eta}."
        if name == "create_ticket":
            return f"I couldn't find that in our help center, so I've passed it to the team (ticket {result['ticket']['id']})."
        return "Done."


def build_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(
            settings.anthropic_api_key, settings.anthropic_model, settings.llm_timeout_seconds
        )
    if settings.llm_provider == "openai":
        return OpenAILLM(settings.openai_api_key, settings.openai_model, settings.llm_timeout_seconds)
    return MockLLM()
