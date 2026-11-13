import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BASELINE_FILE = ROOT / "evaluation" / "baseline_results.json"
LATEST_FILE = ROOT / "evaluation" / "latest_results.json"


# 必须达到的最低指标
THRESHOLDS = {
    "tool_recall": 1.0,
    "diagnosis_accuracy": 1.0,
    "evidence_recall": 1.0,
    "duplicate_tool_call_rate": 0.0,
}


def load_results(path: Path) -> dict:
    """读取 Evaluation JSON 结果。"""

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def check_case(case_id: str, result: dict) -> list[str]:
    """检查单个 Case 是否满足回归测试标准。"""

    failures = []

    if not result.get("passed", False):
        failures.append("Case evaluation failed")

    for metric, threshold in THRESHOLDS.items():
        actual = result.get(metric)

        if actual is None:
            failures.append(f"{metric} is missing")
            continue

        if actual < threshold:
            failures.append(
                f"{metric} regressed: "
                f"expected >= {threshold}, got {actual}"
            )

    if not result.get("first_tool_correct", False):
        failures.append("First tool selection is incorrect")

    if result.get("unexpected_tools"):
        failures.append(
            f"Unexpected tools: {result['unexpected_tools']}"
        )

    if result.get("forbidden_tool_violations"):
        failures.append(
            f"Forbidden tool violations: "
            f"{result['forbidden_tool_violations']}"
        )

    if not result.get("report_complete", False):
        failures.append("Final report is incomplete")

    return failures


def check_case(
    case_id: str,
    baseline: dict,
    latest: dict,
) -> list[str]:
    """检查最新 Case 是否低于基准或质量门槛。"""

    failures = []

    if not latest.get("passed", False):
        failures.append("Case evaluation failed")

    # 越高越好的指标
    higher_is_better = [
        "tool_recall",
        "diagnosis_accuracy",
        "evidence_recall",
    ]

    for metric in higher_is_better:
        old = baseline.get(metric)
        new = latest.get(metric)
        threshold = THRESHOLDS[metric]

        if old is None or new is None:
            failures.append(f"{metric} is missing")
            continue

        if new < threshold:
            failures.append(
                f"{metric} below threshold: {new} < {threshold}"
            )
        elif new < old:
            failures.append(
                f"{metric} regressed: {old} -> {new}"
            )

    # 越低越好的指标
    metric = "duplicate_tool_call_rate"
    old = baseline.get(metric)
    new = latest.get(metric)
    threshold = THRESHOLDS[metric]

    if old is None or new is None:
        failures.append(f"{metric} is missing")
    else:
        if new > threshold:
            failures.append(
                f"{metric} exceeds threshold: {new} > {threshold}"
            )
        elif new > old:
            failures.append(
                f"{metric} regressed: {old} -> {new}"
            )

    if not latest.get("first_tool_correct", False):
        failures.append("First tool selection is incorrect")

    if latest.get("unexpected_tools"):
        failures.append(
            f"Unexpected tools: {latest['unexpected_tools']}"
        )

    if latest.get("forbidden_tool_violations"):
        failures.append(
            f"Forbidden tool violations: "
            f"{latest['forbidden_tool_violations']}"
        )

    if not latest.get("report_complete", False):
        failures.append("Final report is incomplete")

    return failures

def main():
    baseline = load_results(BASELINE_FILE)
    latest = load_results(LATEST_FILE)

    baseline_cases = {
        item["case_id"]: item
        for item in baseline["results"]
    }

    latest_cases = {
        item["case_id"]: item
        for item in latest["results"]
    }

    regression_count = 0

    print("\n========== Regression Test ==========")

    # 1. 检查基准案例是否仍然存在
    for case_id in baseline_cases:
        if case_id not in latest_cases:
            regression_count += 1
            print(f"\nFAIL: {case_id}")
            print("  Case is missing from latest results")

    # 2. 检查最新结果中的每个案例
    for case_id, result in latest_cases.items():

        # 新增案例：没有历史 Baseline
        if case_id not in baseline_cases:
            failures = check_case(case_id, result)

            if failures:
                regression_count += 1
                print(f"\nFAIL: {case_id} (NEW CASE)")
                for failure in failures:
                    print(f"  - {failure}")
            else:
                print(f"\nNEW CASE PASS: {case_id}")

            continue

        failures = check_case(
            case_id,
            baseline_cases[case_id],
            result,
        )

        if failures:
            regression_count += 1
            print(f"\nFAIL: {case_id}")

            for failure in failures:
                print(f"  - {failure}")

        else:
            print(f"\nPASS: {case_id}")

    # 3. 输出最终结果
    print("\n========== Regression Summary ==========")
    print(f"Baseline cases: {len(baseline_cases)}")
    print(f"Latest cases: {len(latest_cases)}")
    print(f"Regressions: {regression_count}")

    if regression_count:
        print("\nREGRESSION TEST FAILED")
        sys.exit(1)

    print("\nREGRESSION TEST PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()