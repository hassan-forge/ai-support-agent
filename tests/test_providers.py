"""Check that requests to Claude and OpenAI are built and parsed correctly, without network calls."""

import json

import httpx

from app.llm import AnthropicLLM, OpenAILLM, ToolCall

TOOLS = [{"name": "lookup_order", "description": "Look up an order", "parameters": {"type": "object"}}]
HISTORY = [
    {"role": "user", "content": "Where is ORD-1042?"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [ToolCall("t1", "lookup_order", {"order_id": "ORD-1042"})],
    },
    {
        "role": "tool",
        "tool_call_id": "t1",
        "name": "lookup_order",
        "content": '{"order": {"status": "shipped"}}',
    },
]


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_anthropic_request_and_tool_use_parsing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Checking."},
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "lookup_order",
                        "input": {"order_id": "ORD-1043"},
                    },
                ],
                "usage": {"input_tokens": 120, "output_tokens": 15},
            },
        )

    llm = AnthropicLLM("key", "claude-test", client=_client(handler))
    resp = llm.complete("system prompt", HISTORY, TOOLS)

    body = seen["body"]
    assert seen["headers"]["x-api-key"] == "key"
    assert body["system"] == "system prompt"
    assert body["tools"][0]["input_schema"] == {"type": "object"}
    assert body["messages"][1]["content"][0]["type"] == "tool_use"
    assert body["messages"][2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": '{"order": {"status": "shipped"}}',
    }
    assert resp.text == "Checking."
    assert resp.tool_calls[0].arguments == {"order_id": "ORD-1043"}
    assert (resp.input_tokens, resp.output_tokens) == (120, 15)


def test_openai_request_and_tool_call_parsing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup_order",
                                        "arguments": '{"order_id": "ORD-1044"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 90, "completion_tokens": 12},
            },
        )

    llm = OpenAILLM("key", "gpt-test", client=_client(handler))
    resp = llm.complete("system prompt", HISTORY, TOOLS)

    msgs = seen["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "system prompt"}
    assert msgs[2]["tool_calls"][0]["function"]["arguments"] == '{"order_id": "ORD-1042"}'
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": '{"order": {"status": "shipped"}}'}
    assert resp.tool_calls[0].name == "lookup_order"
    assert resp.tool_calls[0].arguments == {"order_id": "ORD-1044"}


def test_api_errors_raise_llm_error():
    import pytest

    from app.llm import LLMError

    llm = OpenAILLM("key", "gpt-test", client=_client(lambda r: httpx.Response(429, text="rate limited")))
    with pytest.raises(LLMError, match="429"):
        llm.complete("s", [{"role": "user", "content": "hi"}], TOOLS)
