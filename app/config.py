from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings, read from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["mock", "anthropic", "openai"] = "mock"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0

    docs_dir: Path = ROOT / "data" / "docs"
    orders_file: Path = ROOT / "data" / "orders.json"

    # Retrieval
    top_k: int = 4
    min_coverage: float = 0.5  # share of the question a chunk must cover to be used

    # Guardrails
    max_agent_steps: int = 4
    max_tokens_per_conversation: int = 20_000
    max_refund_without_review: float = 0.0  # every refund goes to a person by default
    history_turns: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
