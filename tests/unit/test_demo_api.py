from fastapi.testclient import TestClient

from curx.main import create_app


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
