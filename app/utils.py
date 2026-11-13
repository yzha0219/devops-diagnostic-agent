import json
from typing import Any
import logging
import re

logger = logging.getLogger(__name__)


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def generate_structured_report(
    client,
    model: str,
    question: str,
    evidence: list,
    draft_text: str,
):
    """基于诊断证据，生成结构化 JSON 报告。"""

    evidence_data = [
        item.model_dump()
        if hasattr(item, "model_dump")
        else item
        for item in evidence
    ]

    messages = [
        {
                "role": "system",
                "content": """
    你是一个 DevOps 故障诊断报告生成器。

    请根据用户问题、诊断证据和初步分析，
    生成最终诊断报告。

    必须严格返回 JSON，不允许 Markdown 或 XML。

    JSON 必须包含以下字段：

    {
    "summary": "string",
    "probable_causes": ["string"],
    "recommendations": ["string"]
    }

    规则：
    1. summary 必须是简洁的故障摘要。
    2. probable_causes 必须是字符串数组。
    3. recommendations 必须是字符串数组，至少包含两条
    不重复、具体且有依据的建议。
    4. 不得编造证据或将推测描述为已确认事实。
    5. 对于证据不足的情况，应明确表达不确定性。
    6. 生产环境变更必须经过授权和人工审批。
    7. 只输出 JSON 对象。
    """
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "evidence": evidence_data,
                    "draft_analysis": draft_text,
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]

    return client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={
            "type": "json_object"
        },
        max_completion_tokens=2048,
        extra_body={
            "thinking": {
                "type": "disabled"
            }
        },
    )


def parse_final_report(text: str) -> dict[str, Any]:
    """解析模型生成的结构化诊断报告。"""

    fallback = {
        "summary": text.strip() or "模型未返回诊断摘要。",
        "probable_causes": [],
        "recommendations": [
            "请结合工具证据人工复核诊断结果。"
        ],
    }

    data, trailing = decode_report_json(text)

    if data is None or not isinstance(data, dict):
        return fallback

    summary = data.get("summary")
    causes = data.get("probable_causes")
    recommendations = data.get("recommendations")

    if not isinstance(summary, str) or not summary.strip():
        return fallback

    if not isinstance(causes, list):
        causes = []

    if not isinstance(recommendations, list):
        recommendations = []

    return {
        "summary": summary.strip(),
        "probable_causes": [
            item for item in causes
            if isinstance(item, str)
        ],
        "recommendations": [
            item for item in recommendations
            if isinstance(item, str)
        ],
    }

def decode_report_json(text: str,) -> tuple[dict[str, Any] | None, str]:
    """
    从模型输出中解析完整 JSON 对象。

    允许 JSON 后面存在已知的 XML 闭合标签，
    但不允许任意尾部文本。
    """

    if not isinstance(text, str):
        return None, ""

    candidate = text.lstrip()

    try:
        data, end = json.JSONDecoder().raw_decode(candidate)
    except json.JSONDecodeError as exc:
        logger.warning(
            "agent_report_decode_error "
            "message=%s position=%d line=%d column=%d "
            "context=%r tail=%r",
            exc.msg,
            exc.pos,
            exc.lineno,
            exc.colno,
            candidate[
                max(0, exc.pos - 100):
                min(len(candidate), exc.pos + 150)
            ],
            candidate[-250:],
        )
        return None, ""

    trailing = candidate[end:].strip()

    # 只允许已知的 XML 闭合标签
    if trailing and not re.fullmatch(
        r"(?:</(?:parameter|function|tool_call)>)+",
        trailing,
    ):
        return None, trailing

    if not isinstance(data, dict):
        return None, trailing

    return data, trailing


def is_valid_final_report(
    text: str,
    min_recommendations: int = 2,
) -> bool:
    """
    判断模型原始报告是否可以直接使用。
    """

    data, trailing = decode_report_json(text)

    if not isinstance(data, dict):
        return False

    # 检查 summary
    summary = data.get("summary")

    if not isinstance(summary, str) or not summary.strip():
        return False

    # 检查 probable_causes
    causes = data.get("probable_causes")

    if not isinstance(causes, list):
        return False

    if not all(
        isinstance(item, str) and item.strip()
        for item in causes
    ):
        return False

    # 检查 recommendations
    recommendations = data.get("recommendations")

    if not isinstance(recommendations, list):
        return False

    valid_recommendations = [
        item for item in recommendations
        if isinstance(item, str) and item.strip()
    ]

    if len(valid_recommendations) < min_recommendations:
        return False

    return True