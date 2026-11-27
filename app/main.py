from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.agent import Agent
from app.config import get_settings
from app.llm import build_llm
from app.retrieval import Retriever
from app.store import Store
from app.tools import build_tools

app = FastAPI(
    title="AI Support Agent",
    description="Answers from your docs with sources, calls tools, and sends risky actions to a person.",
    version="0.1.0",
)


@lru_cache
def get_agent() -> Agent:
    settings = get_settings()
    return Agent(
        llm=build_llm(settings),
        retriever=Retriever.from_dir(settings.docs_dir),
        tools=build_tools(settings),
        store=Store.from_file(settings.orders_file),
        settings=settings,
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class Decision(BaseModel):
    reviewer: str = Field(min_length=1, max_length=100)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": get_settings().llm_provider}


@app.post("/chat")
def chat(req: ChatRequest, agent: Agent = Depends(get_agent)) -> dict:
    return asdict(agent.run(req.message, req.conversation_id))


@app.get("/approvals")
def approvals(status: str | None = "pending", agent: Agent = Depends(get_agent)) -> list[dict]:
    """List approvals by status: pending (default), approved, rejected, or all."""
    return agent.store.list_approvals(None if status == "all" else status)


@app.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, body: Decision, agent: Agent = Depends(get_agent)) -> dict:
    return _decide(agent, approval_id, True, body.reviewer)


@app.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, body: Decision, agent: Agent = Depends(get_agent)) -> dict:
    return _decide(agent, approval_id, False, body.reviewer)


@app.get("/tickets")
def tickets(agent: Agent = Depends(get_agent)) -> list[dict]:
    return list(agent.store.tickets.values())


@app.get("/audit")
def audit(limit: int = 100, agent: Agent = Depends(get_agent)) -> list[dict]:
    return agent.store.audit_log[-limit:]


def _decide(agent: Agent, approval_id: str, approve_: bool, reviewer: str) -> dict:
    try:
        return agent.decide(approval_id, approve_, reviewer)
    except KeyError:
        raise HTTPException(404, f"Approval {approval_id} not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
