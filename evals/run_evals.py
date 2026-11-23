"""Run the eval set against the configured model and print a pass rate.

    python -m evals.run_evals                 # mock model, no key needed
    LLM_PROVIDER=anthropic python -m evals.run_evals
    LLM_PROVIDER=openai python -m evals.run_evals

Each case checks one behaviour that matters in production: the right source is
cited, the right tool is used, risky actions wait for a person, and questions
the docs can't answer are handed off instead of guessed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.agent import Agent
from app.config import get_settings
from app.llm import build_llm
from app.retrieval import Retriever
from app.store import Store
from app.tools import build_tools

CASES = Path(__file__).with_name("cases.json")


def fresh_agent() -> Agent:
    settings = get_settings()
    return Agent(
        build_llm(settings),
        Retriever.from_dir(settings.docs_dir),
        build_tools(settings),
        Store.from_file(settings.orders_file),
        settings,
    )


def check(case: dict, result) -> list[str]:
    problems = []
    handed_off = result.handed_off or any(a.tool == "create_ticket" for a in result.actions)
    if case.get("expect_handoff"):
        if not handed_off:
            problems.append("expected a handoff to a person")
        return problems
    if handed_off:
        problems.append("handed off unexpectedly")
    if src := case.get("expect_source"):
        if src not in {c["source"] for c in result.citations}:
            problems.append(f"did not cite {src}")
    if tool := case.get("expect_tool"):
        matching = [a for a in result.actions if a.tool == tool]
        if not matching:
            problems.append(f"did not call {tool}")
        elif (status := case.get("expect_status")) and matching[0].status != status:
            problems.append(f"{tool} status was {matching[0].status}, expected {status}")
    if (text := case.get("expect_text")) and text.lower() not in result.answer.lower():
        problems.append(f"answer missing '{text}'")
    return problems


def main() -> int:
    cases = json.loads(CASES.read_text())
    failed = 0
    for case in cases:
        result = fresh_agent().run(case["question"])
        problems = check(case, result)
        mark = "PASS" if not problems else "FAIL"
        failed += bool(problems)
        print(f"{mark}  {case['question']}")
        for p in problems:
            print(f"      - {p}")
            print(f"      answer: {result.answer[:160]}")
    passed = len(cases) - failed
    print(f"\n{passed}/{len(cases)} passed ({get_settings().llm_provider})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
