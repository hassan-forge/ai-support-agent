import pytest
from fastapi.testclient import TestClient

from app.agent import Agent
from app.config import Settings
from app.llm import MockLLM
from app.main import app, get_agent
from app.retrieval import Retriever
from app.store import Store
from app.tools import build_tools


@pytest.fixture
def settings() -> Settings:
    return Settings(llm_provider="mock", _env_file=None)


@pytest.fixture
def agent(settings: Settings) -> Agent:
    return Agent(
        llm=MockLLM(),
        retriever=Retriever.from_dir(settings.docs_dir),
        tools=build_tools(settings),
        store=Store.from_file(settings.orders_file),
        settings=settings,
    )


@pytest.fixture
def client(agent: Agent):
    app.dependency_overrides[get_agent] = lambda: agent
    yield TestClient(app)
    app.dependency_overrides.clear()
