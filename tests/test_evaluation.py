
from scripts.evaluate_agent import evaluate_case


def test_duplicate_tool_calls_are_detected():
    """重复调用同一个工具时，评估器应该准确统计重复次数。"""

    case = {
        "id": "duplicate-tools-test",
        "required_tools": [
            "get_pod_status",
        ],
        "allowed_tools": [
            "get_pod_status",
            "get_pod_logs",
            "query_metrics",
        ],
        "forbidden_tools": [],
        "expected_first_tool": "get_pod_status",
        "expected_findings": [],
        "required_evidence_sources": [],
        "min_recommendations": 1,
    }

    response = {
        "status": "completed",
        "summary": "Pod 诊断完成。",
        "probable_causes": [],
        "recommendations": [
            "继续观察 Pod 状态。"
        ],
        "evidence": [],
        "tool_calls": [
            {"tool": "get_pod_status", "success": True},
            {"tool": "get_pod_logs", "success": True},
            {"tool": "get_pod_logs", "success": True},
            {"tool": "query_metrics", "success": True},
            {"tool": "query_metrics", "success": True},
            {"tool": "query_metrics", "success": True},
        ],
    }

    result = evaluate_case(case, response)

    assert result["actual_tools"] == [
        "get_pod_status",
        "get_pod_logs",
        "get_pod_logs",
        "query_metrics",
        "query_metrics",
        "query_metrics",
    ]

    assert result["duplicate_tool_calls"] == [
        "get_pod_logs",
        "query_metrics",
    ]

    assert result["duplicate_tool_call_count"] == 3
    assert result["total_tool_calls"] == 6
    assert result["unique_tool_calls"] == 3
    assert result["duplicate_tool_call_rate"] == 0.5
    assert result["efficiency_score"] == 50.0


def test_different_tool_arguments_are_not_duplicates():
    """同一个工具查询不同 Pod，不应该被判定为重复调用。"""

    case = {
        "id": "different-pods-test",
        "required_tools": ["get_pod_logs"],
        "allowed_tools": ["get_pod_logs"],
        "forbidden_tools": [],
        "expected_first_tool": "get_pod_logs",
        "expected_findings": [],
        "required_evidence_sources": [],
        "min_recommendations": 1,
    }

    response = {
        "status": "completed",
        "summary": "日志查询完成。",
        "probable_causes": [],
        "recommendations": ["继续观察日志。"],
        "evidence": [],
        "tool_calls": [
            {
                "tool": "get_pod_logs",
                "arguments": {
                    "pod_name": "payment-api",
                    "tail_lines": 50,
                },
                "success": True,
            },
            {
                "tool": "get_pod_logs",
                "arguments": {
                    "pod_name": "inventory-api",
                    "tail_lines": 50,
                },
                "success": True,
            },
        ],
    }

    result = evaluate_case(case, response)

    assert result["duplicate_tool_calls"] == []
    assert result["duplicate_tool_call_count"] == 0
    assert result["duplicate_tool_call_details"] == []
    assert result["total_tool_calls"] == 2
    assert result["unique_tool_calls"] == 2
    assert result["duplicate_tool_call_rate"] == 0.0
    assert result["efficiency_score"] == 100.0
