from app.tools import execute_tool, get_pod_logs, get_pod_status, query_metrics, search_runbook


def test_get_known_pod_status():
    result = get_pod_status("prod-cluster", "default", "payment-api-7d9c7d")
    assert result["found"] is True
    assert result["container_status"] == "CrashLoopBackOff"
    assert result["restart_count"] == 8


def test_get_unknown_pod_status():
    result = get_pod_status("prod-cluster", "default", "missing-pod")
    assert result["found"] is False


def test_logs_are_capped_and_fixture_has_auth_error():
    result = get_pod_logs("prod-cluster", "default", "payment-api-7d9c7d", 10000)
    assert len(result["lines"]) <= 100
    assert any("password authentication failed" in line for line in result["lines"])


def test_metrics_are_available():
    result = query_metrics("prod-cluster", "default", "payment-api-7d9c7d")
    assert result["found"] is True
    assert result["cpu_usage_percent"] < 80
    assert result["http_5xx_rate_percent"] > 0


def test_runbook_search_returns_database_runbook():
    result = search_runbook("password authentication failed database app_user")
    assert result["results"]
    assert result["results"][0]["title"] == "数据库认证失败排查"


def test_unknown_tool_is_rejected():
    try:
        execute_tool("delete_pod", {"pod_name": "payment-api-7d9c7d"})
    except ValueError as exc:
        assert "not allow-listed" in str(exc)
    else:
        raise AssertionError("Unknown tool should be rejected")


from app.tools import (
    get_pod_status,
    get_pod_logs,
    query_metrics,
)


def test_oom_pod_status():
    result = get_pod_status(
        cluster="prod-cluster",
        namespace="default",
        pod_name="inventory-api-6f8c9d",
    )

    assert result["found"] is True
    assert result["container_status"] == "CrashLoopBackOff"
    assert result["restart_count"] == 5
    assert result["last_exit_code"] == 137
    assert result["last_termination_reason"] == "OOMKilled"


def test_oom_pod_metrics():
    result = query_metrics(
        cluster="prod-cluster",
        namespace="default",
        pod_name="inventory-api-6f8c9d",
    )

    assert result["found"] is True
    assert result["memory_usage_percent"] == 97.8
    assert result["cpu_usage_percent"] == 42.3


def test_oom_pod_logs():
    result = get_pod_logs(
        cluster="prod-cluster",
        namespace="default",
        pod_name="inventory-api-6f8c9d",
    )

    assert result["found"] is True
    assert any(
        "memory" in line.lower()
        for line in result["lines"]
    )