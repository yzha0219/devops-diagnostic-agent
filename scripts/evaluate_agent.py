import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]

API_URL = os.getenv(
    "AGENT_API_URL",
    "http://127.0.0.1:8000/diagnose",
)

CASES_FILE = ROOT / "evaluation" / "cases.json"
RESULT_FILE = ROOT / "evaluation" / "latest_results.json"


def call_agent(case: dict) -> dict:
    """调用真实的 DevOps Agent API。"""

    payload = {
        "question": case["question"],
        "cluster": case["cluster"],
        "namespace": case["namespace"],
        "pod_name": case["pod_name"],
        "max_steps": case.get("max_steps", 6),
        "mode": "llm",
    }

    request = Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))

    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Agent API returned HTTP {exc.code}: {body}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Cannot connect to Agent API: {exc}"
        ) from exc


def contains_any(text: str, alternatives: list[str]) -> bool:
    """检查文本中是否包含任意一个预期关键词。"""

    normalized = text.casefold()

    return any(
        term.casefold() in normalized
        for term in alternatives
    )


def evaluate_case(case: dict, response: dict) -> dict:
    """根据预设标准评估 Agent 的诊断结果。"""

    tool_calls = response.get("tool_calls") or []
    evidence = response.get("evidence") or []

    actual_tools = [
        item.get("tool")
        for item in tool_calls
        if item.get("tool")
    ]

    
    # 统计真正重复的工具调用：
    # 必须同时满足工具名称和参数完全相同。

    tool_call_counts = {}

    for item in tool_calls:
        tool = item.get("tool")
        if not tool:
            continue

        arguments = item.get("arguments") or {}

        # 将参数字典转换为稳定的 JSON 字符串。
        arguments_key = json.dumps(
            arguments,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        signature = (tool, arguments_key)

        if signature not in tool_call_counts:
            tool_call_counts[signature] = {
                "tool": tool,
                "arguments": arguments,
                "count": 0,
            }

        tool_call_counts[signature]["count"] += 1

    # 找出重复调用的工具和参数组合。
    duplicate_tool_call_details = [
        {
            "tool": item["tool"],
            "arguments": item["arguments"],
            "call_count": item["count"],
            "duplicate_count": item["count"] - 1,
        }
        for item in tool_call_counts.values()
        if item["count"] > 1
    ]

    # 保留重复工具名称列表，方便统计和展示。
    duplicate_tool_calls = sorted({
        item["tool"]
        for item in duplicate_tool_call_details
    })

    # 计算多余调用的总次数。
    duplicate_tool_call_count = sum(
        item["duplicate_count"]
        for item in duplicate_tool_call_details
    )

    # Tool Call Efficiency

    # 实际有效工具调用次数
    total_tool_calls = len(actual_tools)

    # 不同的工具 + 参数组合数量
    unique_tool_calls = len(tool_call_counts)

    # 重复调用比例
    duplicate_tool_call_rate = (
        duplicate_tool_call_count / total_tool_calls
        if total_tool_calls > 0
        else 0.0
    )

    duplicate_tool_call_rate = round(duplicate_tool_call_rate, 4)

    successful_tools = {
        item.get("tool")
        for item in tool_calls
        if item.get("success") is True
    }

    required_tools = set(case["required_tools"])

    # 1. 工具选择评估
    missing_tools = required_tools - successful_tools

    tool_recall = (
        len(required_tools & successful_tools) / len(required_tools)
        if required_tools else 1.0
    )

    expected_first_tool = case.get("expected_first_tool")

    first_tool_correct = (
        bool(actual_tools)
        and actual_tools[0] == expected_first_tool
    ) if expected_first_tool else True

    unexpected_tools = (
        set(actual_tools) - set(case["allowed_tools"])
    )

    # 检查是否调用了明确禁止的工具
    forbidden_tools = set(case.get("forbidden_tools", []))

    violated_tools = set(actual_tools) & forbidden_tools

    # 2. 故障诊断准确性
    report_text = " ".join([
        response.get("summary", ""),
        *response.get("probable_causes", []),
    ])

    findings = case["expected_findings"]

    matched_findings = [
        contains_any(report_text, alternatives)
        for alternatives in findings
    ]

    diagnosis_accuracy = (
        sum(matched_findings) / len(findings)
        if findings else 1.0
    )

    # 3. 证据完整性
    evidence_sources = {
        item.get("source")
        for item in evidence
    }

    required_sources = set(
        case["required_evidence_sources"]
    )

    missing_evidence = required_sources - evidence_sources

    evidence_recall = (
        len(required_sources & evidence_sources)
        / len(required_sources)
        if required_sources else 1.0
    )

    # 4. 报告完整性
    recommendations = response.get("recommendations") or []

    summary = response.get("summary") or ""
    status = response.get("status")

    min_recommendations = case["min_recommendations"]

    report_checks = {
        "status": status,
        "status_completed": status == "completed",
        "summary_present": bool(summary.strip()),
        "recommendation_count": len(recommendations),
        "min_recommendations": min_recommendations,
        "recommendations_sufficient": (
            len(recommendations) >= min_recommendations
        ),
        "tool_recall": tool_recall,
        "tool_recall_sufficient": tool_recall == 1.0,
        "evidence_recall": evidence_recall,
        "evidence_recall_sufficient": evidence_recall == 1.0,
    }

    report_complete = all([
        report_checks["status_completed"],
        report_checks["summary_present"],
        report_checks["recommendations_sufficient"],
        report_checks["tool_recall_sufficient"],
        report_checks["evidence_recall_sufficient"],
    ])

    # 5. 性能与 Token
    metrics = response.get("metrics") or {}


    # Quality Score
    quality_score = (
        tool_recall * 30
        + evidence_recall * 20
        + diagnosis_accuracy * 25
        + (10 if first_tool_correct else 0)
        + (15 if report_complete else 0)
    )

    quality_score = round(quality_score, 2)

    # Efficiency Score
    efficiency_score = round(
        100 * (1 - duplicate_tool_call_rate),
        2,
    )

    # Overall Score
    overall_score = round(
        quality_score * 0.85
        + efficiency_score * 0.15,
        2,
    )

    result = {
        "case_id": case["id"],

        "tool_recall": round(tool_recall, 4),
        "first_tool_correct": first_tool_correct,
        "actual_tools": actual_tools,
        "missing_tools": sorted(missing_tools),
        "unexpected_tools": sorted(unexpected_tools),
        "configured_forbidden_tools": sorted(forbidden_tools),
        "forbidden_tool_violations": sorted(violated_tools),
        "duplicate_tool_calls": duplicate_tool_calls,
        "duplicate_tool_call_count": duplicate_tool_call_count,
        "duplicate_tool_call_details": duplicate_tool_call_details,
        "total_tool_calls": total_tool_calls,
        "unique_tool_calls": unique_tool_calls,
        "duplicate_tool_call_rate": duplicate_tool_call_rate,


        "diagnosis_accuracy": round(diagnosis_accuracy, 4),
        "matched_findings": matched_findings,

        "evidence_recall": round(evidence_recall, 4),
        "missing_evidence": sorted(missing_evidence),

        "quality_score": quality_score,
        "efficiency_score": efficiency_score,
        "overall_score": overall_score,

        "report_complete": report_complete,
        "report_checks": report_checks,

        "performance": {
            "total_elapsed_ms": metrics.get("total_elapsed_ms"),
            "llm_call_count": metrics.get("llm_call_count"),
            "total_tokens": metrics.get("total_tokens"),
            "token_usage_available": metrics.get(
                "token_usage_available", False
            ),
            "tool_call_count": metrics.get("tool_call_count"),
            "tool_latency_ms_total": metrics.get(
                "tool_latency_ms_total"
            ),
            "tool_failure_count": metrics.get(
                "tool_failure_count"
            ),
            "llm_latency_ms_total": metrics.get(
                "llm_latency_ms_total"
            ),
            "llm_latency_ms_avg": metrics.get(
                "llm_latency_ms_avg"
            ),
        },
    }

    # 全部必须满足的条件
    result["passed"] = all([
        tool_recall == 1.0,
        first_tool_correct,
        not unexpected_tools,
        not violated_tools,
        diagnosis_accuracy == 1.0,
        evidence_recall == 1.0,
        report_complete,
    ])

    return result


def main():
    with open(CASES_FILE, "r", encoding="utf-8") as file:
        cases = json.load(file)
        # cases = [
        #     case
        #     for case in json.load(file)
        #     if case["id"] == "inventory-oom-001"
        # ]

    results = []

    for case in cases:
        print(f"\nRunning evaluation: {case['id']}")

        try:
            response = call_agent(case)
            result = evaluate_case(case, response)

        except Exception as exc:
            result = {
                "case_id": case["id"],
                "passed": False,
                "error": str(exc),
            }

        results.append(result)

        print("PASS" if result["passed"] else "FAIL")

        if "error" not in result:
            print(
                f"Tool recall: {result['tool_recall']:.0%}"
            )
            print(
                f"Diagnosis accuracy: "
                f"{result['diagnosis_accuracy']:.0%}"
            )
            print(
                f"Evidence recall: {result['evidence_recall']:.0%}"
            )
            print(
                "Performance:",
                json.dumps(
                    result["performance"],
                    ensure_ascii=False,
                ),
            )

    passed = sum(item["passed"] for item in results)
    total = len(results)

    report = {
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0,
        "results": results,
    }

    RESULT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n========== Evaluation Summary ==========")
    print(f"Total cases: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {total - passed}")
    print(f"Pass rate: {report['pass_rate']:.1%}")
    print(f"Report saved to: {RESULT_FILE}")
    print(
    "Report checks:",
    json.dumps(
        result["report_checks"],
        ensure_ascii=False,
    ),
)


if __name__ == "__main__":
    main()