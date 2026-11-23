"""Tools the agent may call.

Each tool declares its risk. Read tools run immediately. Write tools either run
immediately or go to a person for approval, depending on `needs_approval`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.config import Settings
from app.store import Store


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Literal["read", "write"]
    handler: Callable[[Store, dict[str, Any]], dict[str, Any]]
    needs_approval: Callable[[Store, dict[str, Any]], str | None] = lambda store, args: None

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def _lookup_order(store: Store, args: dict[str, Any]) -> dict[str, Any]:
    order = store.orders.get(str(args.get("order_id", "")).upper())
    if not order:
        return {"error": f"No order found with id {args.get('order_id')}."}
    return {"order": order}


def _create_ticket(store: Store, args: dict[str, Any]) -> dict[str, Any]:
    priority = args.get("priority", "normal")
    if priority not in {"low", "normal", "high"}:
        priority = "normal"
    ticket = store.create_ticket(
        subject=str(args.get("subject", "Support request"))[:120],
        summary=str(args.get("summary", ""))[:2000],
        priority=priority,
    )
    return {"ticket": ticket}


def _issue_refund(store: Store, args: dict[str, Any]) -> dict[str, Any]:
    order = store.orders.get(str(args.get("order_id", "")).upper())
    if not order:
        return {"error": f"No order found with id {args.get('order_id')}."}
    amount = float(args.get("amount") or order["total"])
    if amount <= 0 or amount > order["total"]:
        return {"error": f"Refund amount must be between 0 and the order total ({order['total']})."}
    refund = {"order_id": order["id"], "amount": round(amount, 2), "reason": args.get("reason", "")}
    store.refunds.append(refund)
    order["status"] = "refunded"
    return {"refund": refund}


def build_tools(settings: Settings) -> dict[str, Tool]:
    def refund_review(store: Store, args: dict[str, Any]) -> str | None:
        order = store.orders.get(str(args.get("order_id", "")).upper())
        amount = float(args.get("amount") or (order or {}).get("total", 0))
        if amount > settings.max_refund_without_review:
            return f"Refund of {amount:.2f} is above the auto-approve limit ({settings.max_refund_without_review:.2f})."
        return None

    tools = [
        Tool(
            name="lookup_order",
            description="Look up an order by id (format ORD-1234) to get its status, items and delivery date.",
            parameters={
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "Order id, e.g. ORD-1042"}},
                "required": ["order_id"],
            },
            risk="read",
            handler=_lookup_order,
        ),
        Tool(
            name="create_ticket",
            description="Create a support ticket for the team when the answer is not in the docs or needs a person.",
            parameters={
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "summary": {"type": "string", "description": "What the customer needs, in one paragraph"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                },
                "required": ["subject", "summary"],
            },
            risk="write",
            handler=_create_ticket,
        ),
        Tool(
            name="issue_refund",
            description="Refund an order. Use only when the customer asks for a refund on a specific order.",
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "amount": {"type": "number", "description": "Defaults to the full order total"},
                    "reason": {"type": "string"},
                },
                "required": ["order_id", "reason"],
            },
            risk="write",
            handler=_issue_refund,
            needs_approval=refund_review,
        ),
    ]
    return {t.name: t for t in tools}
