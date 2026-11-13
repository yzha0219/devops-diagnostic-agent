from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_demo_diagnosis_returns_evidence_and_tool_calls():
    response = client.post("/diagnose", json={
        "question": "payment-api 为什么频繁重启？",
        "cluster": "prod-cluster",
        "namespace": "default",
        "pod_name": "payment-api-7d9c7d",
        "mode": "demo",
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "demo"
    assert "CrashLoopBackOff" in data["summary"]
    assert len(data["evidence"]) == 4
    assert {item["tool"] for item in data["tool_calls"]} == {
        "get_pod_status", "get_pod_logs", "query_metrics", "search_runbook"
    }


def test_unknown_pod_is_reported_without_crashing():
    response = client.post("/diagnose", json={
        "question": "检查一个未知 Pod 的状态",
        "pod_name": "unknown-pod",
        "mode": "demo",
    })
    assert response.status_code == 200
    assert "没有在 Demo 数据中找到" in response.json()["summary"]


def test_invalid_short_question_is_rejected():
    response = client.post("/diagnose", json={"question": "x"})
    assert response.status_code == 422



def test_llm_timeout_returns_502(monkeypatch):
    """LLM 超时时，API 应返回 HTTP 502。"""

    import openai
    import app.main as main_module

    def mock_run_agent(request):
        raise openai.APITimeoutError(
            request=None
        )

    monkeypatch.setattr(
        main_module,
        "run_agent",
        mock_run_agent,
    )

    response = client.post("/diagnose", json={
        "question": "payment-api 为什么频繁重启？",
        "cluster": "prod-cluster",
        "namespace": "default",
        "pod_name": "payment-api-7d9c7d",
        "mode": "llm",
    })

    assert response.status_code == 502

    data = response.json()

    assert "诊断失败" in data["detail"]
    assert "APITimeoutError" in data["detail"]
