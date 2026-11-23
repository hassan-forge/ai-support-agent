from app.llm import LLMError, LLMResponse, ToolCall


def test_answers_from_docs_with_a_citation(agent):
    result = agent.run("How long does standard shipping take?")
    assert not result.handed_off
    assert "3 to 5 business days" in result.answer
    assert result.citations[0]["source"] == "shipping.md"
    assert result.citations[0]["title"] == "Delivery times"


def test_looks_up_an_order(agent):
    result = agent.run("Where is my order ORD-1042?")
    assert "shipped" in result.answer
    assert [a.tool for a in result.actions] == ["lookup_order"]
    assert result.actions[0].status == "done"


def test_refund_waits_for_a_person(agent):
    result = agent.run("Please refund ORD-1044, the chair broke")
    action = result.actions[0]
    assert action.tool == "issue_refund"
    assert action.status == "pending_approval"
    assert agent.store.refunds == []  # nothing happened yet
    assert agent.store.orders["ORD-1044"]["status"] == "delivered"

    decision = agent.decide(action.approval_id, approve=True, reviewer="maria")
    assert decision["status"] == "approved"
    assert agent.store.refunds[0]["amount"] == 219.0
    assert agent.store.orders["ORD-1044"]["status"] == "refunded"


def test_rejected_refund_does_nothing(agent):
    result = agent.run("refund ORD-1042 please")
    agent.decide(result.actions[0].approval_id, approve=False, reviewer="maria")
    assert agent.store.refunds == []


def test_unknown_question_goes_to_a_person(agent):
    result = agent.run("What is your CEO's name?")
    assert result.handed_off or any(a.tool == "create_ticket" for a in result.actions)
    assert len(agent.store.tickets) == 1
    assert result.citations == []


def test_ungrounded_model_answer_is_not_sent(agent):
    class MakesThingsUp:
        def complete(self, system, messages, tools):
            return LLMResponse(text="Our CEO is Jane Smith.")  # no citation, no tool

    agent.llm = MakesThingsUp()
    result = agent.run("Who is the CEO?")
    assert result.handed_off
    assert "Jane" not in result.answer


def test_model_errors_hand_off_instead_of_crashing(agent):
    class Broken:
        def complete(self, system, messages, tools):
            raise LLMError("timeout")

    agent.llm = Broken()
    result = agent.run("How long does shipping take?")
    assert result.handed_off
    assert agent.store.audit_log[-1]["reason"] == "model error: timeout"


def test_step_limit_stops_tool_loops(agent):
    class Loops:
        def complete(self, system, messages, tools):
            return LLMResponse(tool_calls=[ToolCall("x", "lookup_order", {"order_id": "ORD-1042"})])

    agent.llm = Loops()
    result = agent.run("Where is ORD-1042?")
    assert result.handed_off
    assert len(result.actions) == agent.settings.max_agent_steps + 1


def test_unknown_tool_is_refused(agent):
    calls = iter(
        [
            LLMResponse(tool_calls=[ToolCall("x", "delete_database", {})]),
            LLMResponse(text="Sorry, I can't do that. Our standard shipping takes 3 to 5 business days. [1]"),
        ]
    )

    class AsksForBadTool:
        def complete(self, system, messages, tools):
            return next(calls)

    agent.llm = AsksForBadTool()
    result = agent.run("How long does shipping take?")
    assert result.actions[0].status == "rejected"


def test_every_step_is_audited(agent):
    agent.run("Where is my order ORD-1043?")
    actions = [e["action"] for e in agent.store.audit_log]
    assert actions == ["message", "tool_call", "reply"]
