"""In-memory store for orders, tickets, approvals, conversations and the audit log.

Swap for Postgres in production; the agent only talks to this class.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Approval:
    id: str
    conversation_id: str
    tool: str
    arguments: dict[str, Any]
    reason: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    result: dict[str, Any] | None = None
    created_at: str = field(default_factory=now)
    decided_at: str | None = None
    decided_by: str | None = None


@dataclass
class Conversation:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0


class Store:
    def __init__(self, orders: dict[str, dict[str, Any]] | None = None):
        self._lock = threading.Lock()
        self.orders: dict[str, dict[str, Any]] = orders or {}
        self.tickets: dict[str, dict[str, Any]] = {}
        self.refunds: list[dict[str, Any]] = []
        self.approvals: dict[str, Approval] = {}
        self.conversations: dict[str, Conversation] = {}
        self.audit_log: list[dict[str, Any]] = []

    @classmethod
    def from_file(cls, orders_file: Path) -> Store:
        orders = {o["id"]: o for o in json.loads(orders_file.read_text(encoding="utf-8"))}
        return cls(orders)

    # --- audit -----------------------------------------------------------
    def audit(self, actor: str, action: str, **details: Any) -> None:
        with self._lock:
            self.audit_log.append({"at": now(), "actor": actor, "action": action, **details})

    # --- conversations ---------------------------------------------------
    def conversation(self, conversation_id: str | None) -> Conversation:
        with self._lock:
            cid = conversation_id or f"c_{uuid.uuid4().hex[:10]}"
            if cid not in self.conversations:
                self.conversations[cid] = Conversation(id=cid)
            return self.conversations[cid]

    # --- tickets ---------------------------------------------------------
    def create_ticket(self, subject: str, summary: str, priority: str) -> dict[str, Any]:
        with self._lock:
            ticket_id = f"T-{len(self.tickets) + 1001}"
            ticket = {
                "id": ticket_id,
                "subject": subject,
                "summary": summary,
                "priority": priority,
                "status": "open",
                "created_at": now(),
            }
            self.tickets[ticket_id] = ticket
            return ticket

    # --- approvals -------------------------------------------------------
    def add_approval(self, conversation_id: str, tool: str, arguments: dict, reason: str) -> Approval:
        with self._lock:
            approval = Approval(
                id=f"A-{uuid.uuid4().hex[:8]}",
                conversation_id=conversation_id,
                tool=tool,
                arguments=arguments,
                reason=reason,
            )
            self.approvals[approval.id] = approval
            return approval

    def list_approvals(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = [a for a in self.approvals.values() if status is None or a.status == status]
            return [asdict(a) for a in items]
