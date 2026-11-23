"""The agent loop: retrieve, ask the model, run safe tools, queue risky ones, cite sources."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.llm import LLM, LLMError
from app.retrieval import Hit, Retriever
from app.store import Store, now
from app.tools import Tool

SYSTEM_PROMPT = """You are the support assistant for Northwind Supply, an online store.

Rules:
- Answer only from the numbered context below or from tool results. Never invent policies, prices or dates.
- Cite the context you used with its number in square brackets, like [1].
- If the context does not answer the question and no tool helps, call create_ticket so a person follows up.
- Use lookup_order for questions about a specific order id. Use issue_refund only when the customer asks for a refund.
- Keep answers short, plain and friendly.

Context:
{context}"""

HANDOFF_MESSAGE = (
    "I'm not able to answer that reliably, so I've passed it to our team "
    "(ticket {ticket_id}). Someone will reply by email."
)
CITATION = re.compile(r"\[(\d+)\]")


@dataclass
class Action:
    tool: str
    status: str
    approval_id: str | None = None
    detail: str | None = None


@dataclass
class AgentResult:
    conversation_id: str
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    handed_off: bool = False


class Agent:
    def __init__(
        self, llm: LLM, retriever: Retriever, tools: dict[str, Tool], store: Store, settings: Settings
    ):
        self.llm = llm
        self.retriever = retriever
        self.tools = tools
        self.store = store
        self.settings = settings

    def run(self, message: str, conversation_id: str | None = None) -> AgentResult:
        conv = self.store.conversation(conversation_id)
        hits = [
            h
            for h in self.retriever.search(message, self.settings.top_k)
            if h.coverage >= self.settings.min_coverage
        ]
        system = SYSTEM_PROMPT.format(context=self._format_context(hits))

        history = conv.messages[-self.settings.history_turns * 2 :]
        turn: list[dict[str, Any]] = [{"role": "user", "content": message}]
        actions: list[Action] = []
        self.store.audit("customer", "message", conversation_id=conv.id, text=message[:500])

        answer = ""
        for _ in range(self.settings.max_agent_steps):
            if conv.tokens_used > self.settings.max_tokens_per_conversation:
                return self._handoff(conv.id, message, actions, "token budget exceeded")
            try:
                resp = self.llm.complete(system, history + turn, [t.spec() for t in self.tools.values()])
            except LLMError as exc:
                return self._handoff(conv.id, message, actions, f"model error: {exc}")
            conv.tokens_used += resp.input_tokens + resp.output_tokens

            turn.append({"role": "assistant", "content": resp.text, "tool_calls": resp.tool_calls})
            if not resp.tool_calls:
                answer = resp.text
                break
            for call in resp.tool_calls:
                result = self._run_tool(conv.id, call.name, call.arguments, actions)
                turn.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(result),
                    }
                )
        else:
            return self._handoff(conv.id, message, actions, "step limit reached")

        citations = self._citations(answer, hits)
        if not actions and not citations:
            # Ungrounded answer: no source and no tool behind it. Don't send it.
            return self._handoff(conv.id, message, actions, "answer had no source")

        conv.messages.extend([{"role": "user", "content": message}, {"role": "assistant", "content": answer}])
        self.store.audit("agent", "reply", conversation_id=conv.id, text=answer[:500])
        return AgentResult(conv.id, answer, citations, actions)

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def _format_context(hits: list[Hit]) -> str:
        if not hits:
            return "(no relevant documents found)"
        return "\n".join(
            f"[{i}] ({h.chunk.source}) {h.chunk.title}: {h.chunk.text}" for i, h in enumerate(hits, 1)
        )

    @staticmethod
    def _citations(answer: str, hits: list[Hit]) -> list[dict[str, Any]]:
        seen, out = set(), []
        for n in CITATION.findall(answer):
            i = int(n)
            if 1 <= i <= len(hits) and i not in seen:
                seen.add(i)
                h = hits[i - 1]
                out.append({"n": i, "source": h.chunk.source, "title": h.chunk.title, "score": h.score})
        return out

    def _run_tool(
        self, conversation_id: str, name: str, args: dict[str, Any], actions: list[Action]
    ) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            actions.append(Action(name, "rejected", detail="unknown tool"))
            return {"error": f"Unknown tool {name}."}

        reason = tool.needs_approval(self.store, args)
        if reason:
            approval = self.store.add_approval(conversation_id, name, args, reason)
            self.store.audit("agent", "approval_requested", tool=name, approval_id=approval.id, args=args)
            actions.append(Action(name, "pending_approval", approval.id, reason))
            return {"status": "pending_approval", "approval_id": approval.id}

        result = tool.handler(self.store, args)
        status = "error" if "error" in result else "done"
        self.store.audit("agent", "tool_call", tool=name, args=args, status=status)
        actions.append(Action(name, status, detail=result.get("error")))
        return result

    def _handoff(self, conversation_id: str, message: str, actions: list[Action], why: str) -> AgentResult:
        ticket = self.store.create_ticket(
            subject=message[:80], summary=f"{message}\n\nHanded off: {why}", priority="normal"
        )
        self.store.audit(
            "agent", "handoff", conversation_id=conversation_id, reason=why, ticket_id=ticket["id"]
        )
        actions.append(Action("create_ticket", "done", detail=why))
        return AgentResult(
            conversation_id,
            HANDOFF_MESSAGE.format(ticket_id=ticket["id"]),
            actions=actions,
            handed_off=True,
        )

    # --- approvals -------------------------------------------------------

    def decide(self, approval_id: str, approve: bool, reviewer: str) -> dict[str, Any]:
        approval = self.store.approvals.get(approval_id)
        if approval is None:
            raise KeyError(approval_id)
        if approval.status != "pending":
            raise ValueError(f"Approval {approval_id} is already {approval.status}.")
        approval.decided_at, approval.decided_by = now(), reviewer
        if approve:
            approval.result = self.tools[approval.tool].handler(self.store, approval.arguments)
            approval.status = "approved"
        else:
            approval.status = "rejected"
        self.store.audit(reviewer, f"approval_{approval.status}", approval_id=approval_id, tool=approval.tool)
        return {"id": approval.id, "status": approval.status, "result": approval.result}
