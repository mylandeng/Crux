from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage

from curx.core.config import Settings
from curx.main import create_app


class FakeChatModel:
    def __init__(self) -> None:
        self.messages: list[BaseMessage] = []

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.messages = messages
        return AIMessage(content="这是模型返回的真实对话回答。")

    async def astream(self, messages: list[BaseMessage]):
        self.messages = messages
        yield AIMessage(content="流式")
        yield AIMessage(content="回答")


def test_health_check_reports_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_demo_answer_returns_citations_and_events() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/demo/answer",
        json={"question": "电池充电截止电压是多少？"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["handoff_required"] is False
    assert payload["citations"]
    assert payload["events"][-1]["type"] == "answer.completed"


def test_chat_answer_sends_conversation_messages_to_configured_model(monkeypatch) -> None:
    fake_model = FakeChatModel()

    def fake_build_chat_model(settings: Settings) -> FakeChatModel:
        assert settings.model_provider == "openai"
        return fake_model

    monkeypatch.setattr("curx.services.chat_llm.build_chat_model", fake_build_chat_model)
    client = TestClient(create_app(Settings(auth_required=False, _env_file=None)))

    response = client.post(
        "/api/chat/answer",
        json={
            "messages": [
                {"role": "user", "content": "先记住：截止电压是 4.20V"},
                {"role": "assistant", "content": "已记住。"},
                {"role": "user", "content": "刚才那个参数是多少？"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "这是模型返回的真实对话回答。"
    assert payload["citations"] == []
    assert payload["events"][-1]["type"] == "answer.completed"
    assert [message.type for message in fake_model.messages] == ["human", "ai", "human"]


def test_chat_stream_returns_sse_delta_and_completion(monkeypatch) -> None:
    fake_model = FakeChatModel()

    def fake_build_chat_model(settings: Settings) -> FakeChatModel:
        return fake_model

    monkeypatch.setattr("curx.services.chat_llm.build_chat_model", fake_build_chat_model)
    client = TestClient(create_app(Settings(auth_required=False, _env_file=None)))

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"messages": [{"role": "user", "content": "流式测试"}]},
    ) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: answer.started" in body
    assert "event: answer.delta" in body
    assert '"text": "流式"' in body
    assert '"answer": "流式回答"' in body
    assert "event: answer.completed" in body
