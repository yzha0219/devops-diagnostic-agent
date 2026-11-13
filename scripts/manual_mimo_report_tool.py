import json

from openai import OpenAI

from app.config import (
    llm_api_key,
    llm_base_url,
    llm_model,
)


client_kwargs = {
    "api_key": llm_api_key(),
    "timeout": 60.0,
}

if llm_base_url():
    client_kwargs["base_url"] = llm_base_url()

client = OpenAI(**client_kwargs)


# 定义最终诊断报告工具
REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_diagnosis_report",
        "description": (
            "当你已经完成故障分析后，必须调用此工具"
            "提交最终诊断报告。"
            "它只用于返回结构化报告，不执行外部操作。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "故障诊断摘要",
                },
                "probable_causes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "按证据支持程度排序的可能原因",
                },
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "具体且可执行的排查建议",
                },
            },
            "required": [
                "summary",
                "probable_causes",
                "recommendations",
            ],
            "additionalProperties": False,
        },
    },
}


# 模拟之前 Agent 收集到的诊断证据
evidence = {
    "pod_status": {
        "container_status": "CrashLoopBackOff",
        "restart_count": 8,
        "last_exit_code": 1,
    },
    "logs": [
        'FATAL: password authentication failed for user "app_user"',
        "application startup failed",
    ],
    "metrics": {
        "cpu_usage_percent": 12.4,
        "memory_usage_percent": 38.1,
        "http_5xx_rate_percent": 7.8,
    },
}


messages = [
    {
        "role": "system",
        "content": """
你是一个 DevOps 故障诊断助手。

请根据提供的证据分析故障。

完成分析后，必须调用 submit_diagnosis_report
提交最终报告。

不要通过普通文本输出最终报告。
不要调用其他工具。
不要编造证据。

至少提供两条不同的排查建议。
涉及生产环境变更必须经过人工审批。
""",
    },
    {
        "role": "user",
        "content": json.dumps(
            {
                "question": "payment-api 为什么频繁重启？",
                "evidence": evidence,
            },
            ensure_ascii=False,
        ),
    },
]


response = client.chat.completions.create(
    model=llm_model(),
    messages=messages,
    tools=[REPORT_TOOL],
    tool_choice="auto",
    max_completion_tokens=1024,
    extra_body={
        "thinking": {
            "type": "disabled"
        }
    },
)


choice = response.choices[0]
message = choice.message

print("Finish reason:", choice.finish_reason)

print(
    "Tool calls:",
    [
        call.model_dump()
        for call in (message.tool_calls or [])
    ],
)

if not message.tool_calls:
    raise RuntimeError(
        "测试失败：模型没有调用 submit_diagnosis_report"
    )


report_call = message.tool_calls[0]

assert (
    report_call.function.name
    == "submit_diagnosis_report"
)

report = json.loads(
    report_call.function.arguments
)

assert isinstance(report["summary"], str)

assert isinstance(
    report["probable_causes"], list
)

assert isinstance(
    report["recommendations"], list
)

assert len(report["recommendations"]) >= 2

print("\n========== REPORT TOOL TEST PASSED ==========")

print(
    json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
    )
)