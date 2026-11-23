def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "provider": "mock"}


def test_chat_and_approval_flow(client):
    reply = client.post("/chat", json={"message": "I want a refund for ORD-1043"}).json()
    assert reply["actions"][0]["status"] == "pending_approval"
    approval_id = reply["actions"][0]["approval_id"]

    pending = client.get("/approvals").json()
    assert [a["id"] for a in pending] == [approval_id]

    decided = client.post(f"/approvals/{approval_id}/approve", json={"reviewer": "maria"}).json()
    assert decided["status"] == "approved"
    assert client.get("/approvals").json() == []

    again = client.post(f"/approvals/{approval_id}/approve", json={"reviewer": "maria"})
    assert again.status_code == 409


def test_conversation_id_is_kept(client):
    first = client.post("/chat", json={"message": "Is shipping free?"}).json()
    second = client.post(
        "/chat", json={"message": "Can I pay with PayPal?", "conversation_id": first["conversation_id"]}
    ).json()
    assert second["conversation_id"] == first["conversation_id"]


def test_missing_approval_is_404(client):
    assert client.post("/approvals/A-nope/approve", json={"reviewer": "x"}).status_code == 404


def test_empty_message_is_rejected(client):
    assert client.post("/chat", json={"message": ""}).status_code == 422
