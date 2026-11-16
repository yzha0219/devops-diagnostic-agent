
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT_FILE = ROOT / "evaluation" / "latest_results.json"


# Overall Quality Gate thresholds
THRESHOLDS = {
    "pass_rate": 1.0,
    "tool_recall": 0.90,
    "diagnosis_accuracy": 0.90,
    "evidence_recall": 0.90,
}


def load_results() -> dict:
    """Load the latest Agent evaluation report."""

    if not RESULT_FILE.exists():
        raise FileNotFoundError(
            f"Evaluation report not found: {RESULT_FILE}"
        )

    with RESULT_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def main():

    print("\n========== AI Agent Quality Gate ==========")

    try:
        report = load_results()
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"FAIL: Cannot load evaluation report: {exc}")
        sys.exit(1)

    total_cases = report.get("total_cases", 0)
    passed_cases = report.get("passed", 0)
    results = report.get("results", [])

    failures = []

    # 1. Validate evaluation report structure
    if total_cases <= 0:
        failures.append("No evaluation cases found")

    if len(results) != total_cases:
        failures.append(
            f"Case count mismatch: "
            f"total_cases={total_cases}, results={len(results)}"
        )

    # 2. Check overall pass rate
    pass_rate = report.get("pass_rate", 0)

    print(
        f"Pass Rate: {pass_rate:.1%} "
        f"(Required: {THRESHOLDS['pass_rate']:.1%})"
    )

    if pass_rate < THRESHOLDS["pass_rate"]:
        failures.append("Overall pass rate below threshold")

    # 3. Check each Case
    for result in results:

        case_id = result.get("case_id", "UNKNOWN")

        print(f"\nChecking Case: {case_id}")

        if not result.get("passed", False):
            failures.append(f"{case_id}: Evaluation failed")

        for metric in (
            "tool_recall",
            "diagnosis_accuracy",
            "evidence_recall",
        ):
            threshold = THRESHOLDS[metric]
            actual = result.get(metric)

            if actual is None:
                failures.append(
                    f"{case_id}: {metric} is missing"
                )
                continue

            print(
                f"  {metric}: {actual:.1%} "
                f"(Required: {threshold:.1%})"
            )

            if actual < threshold:
                failures.append(
                    f"{case_id}: {metric} below threshold"
                )

        if not result.get("report_complete", False):
            failures.append(
                f"{case_id}: Final report is incomplete"
            )

        if result.get("forbidden_tool_violations"):
            failures.append(
                f"{case_id}: Forbidden tool violations detected"
            )

    # 4. Final result
    print("\n========== Quality Gate Summary ==========")

    print(f"Total Cases: {total_cases}")
    print(f"Passed Cases: {passed_cases}")
    print(f"Failed Cases: {total_cases - passed_cases}")

    if failures:
        print("\nQUALITY GATE FAILED")

        for failure in failures:
            print(f"  - {failure}")

        sys.exit(1)

    print("\nQUALITY GATE PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
