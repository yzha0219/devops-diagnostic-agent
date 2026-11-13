import json

from openai import OpenAI

from app.config import (
    llm_api_key,
    llm_base_url,
    llm_model,
)

from app.tools import LLM_TOOLS


client_kwargs = {
    "api_key": llm_api_key(),
    "timeout": 60.0,
}

if llm_base_url():
    client_kwargs["base_url"] = llm_base_url()

client = OpenAI(**client_kwargs)


# 定义报告格式
SYSTEM_PROMPT = """
你是一个 DevOps 故障诊断助手。

当前测试需要验证 Tool Calling 和 JSON Mode 是否能够同时工作。

执行规则：

1. 用户要求查询 Pod 时，必须调用 get_pod_status。
2. 收到工具结果后，不要再次调用工具。
3. 根据工具结果生成最终诊断报告。
4. 最终报告必须严格返回 JSON。
5. 不允许输出 Markdown 或 XML。

JSON 格式：

{
    "summary": "string",
    "probable_causes": ["string"],
    "recommendations": ["string"]
}

如果证据不足，应明确说明，不能编造故障原因。
"""


messages = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT,
    },
    {
        "role": "user",
        "content": (
            "查询 prod-cluster/default 中的 "
            "payment-api-7d9c7d，判断它是否存在启动故障。"
        ),
    },
]


# 第一次请求：同时启用 Tools 和 JSON Mode
print("\n========== Step 1: Tool Calling + JSON Mode ==========")

response = client.chat.completions.create(
    model=llm_model(),
    messages=messages,
    tools=LLM_TOOLS,
    tool_choice="auto",
    response_format={
        "type": "json_object"
    },
    max_completion_tokens=512,
    extra_body={
        "thinking": {
            "type": "disabled"
        }
    },
)

message = response.choices[0].message

print("Finish reason:", response.choices[0].finish_reason)
print(
    "Tool calls:",
    [
        call.function.name
        for call in (message.tool_calls or [])
    ],
)
print("Content:", repr(message.content))


# 第一次必须产生结构化工具调用
if not message.tool_calls:
    raise RuntimeError(
        "测试未通过：模型没有返回结构化工具调用。"
    )


# 模拟工具返回结果
messages.append({
    "role": "assistant",
    "content": message.content or "",
    "tool_calls": [
        call.model_dump(exclude_none=True)
        for call in message.tool_calls
    ],
})


for tool_call in message.tool_calls:

    if tool_call.function.name != "get_pod_status":
        raise RuntimeError(
            f"测试调用了非预期工具：{tool_call.function.name}"
        )

    result = {
        "cluster": "prod-cluster",
        "namespace": "default",
        "pod_name": "payment-api-7d9c7d",
        "found": True,
        "phase": "Running",
        "container_status": "CrashLoopBackOff",
        "ready": False,
        "restart_count": 8,
        "last_exit_code": 1,
        "events": [
            "Back-off restarting failed container payment-api"
        ],
    }

    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps(
            result,
            ensure_ascii=False,
        ),
    })


# 第二次请求：带着工具结果，要求直接生成 JSON
print("\n========== Step 2: Final JSON Output ==========")

response2 = client.chat.completions.create(
    model=llm_model(),
    messages=messages,
    tools=LLM_TOOLS,
    tool_choice="auto",
    response_format={
        "type": "json_object"
    },
    max_completion_tokens=1024,
    extra_body={
        "thinking": {
            "type": "disabled"
        }
    },
)

final_message = response2.choices[0].message

print("Finish reason:", response2.choices[0].finish_reason)
print("Tool calls:", final_message.tool_calls)
print("Content:", final_message.content)

if final_message.tool_calls:
    raise RuntimeError(
        "测试未通过：模型在获得足够证据后仍然请求调用工具。"
    )

# 验证 JSON 格式
report = json.loads(final_message.content)

required_fields = {
    "summary",
    "probable_causes",
    "recommendations",
}

assert required_fields.issubset(report.keys())
assert isinstance(report["summary"], str)
assert isinstance(report["probable_causes"], list)
assert isinstance(report["recommendations"], list)

print("\n========== TEST PASSED ==========")
print(json.dumps(report, ensure_ascii=False, indent=2))