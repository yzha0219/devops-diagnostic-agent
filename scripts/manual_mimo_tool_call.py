from openai import OpenAI

from app.config import llm_api_key, llm_base_url, llm_model
from app.tools import LLM_TOOLS


client_kwargs = {
    "api_key": llm_api_key(),
    "timeout": 45.0,
}

if llm_base_url():
    client_kwargs["base_url"] = llm_base_url()

client = OpenAI(**client_kwargs)

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_pod_status",
            "description": "查询指定 Kubernetes Pod 的状态",
            "parameters": {
                "type": "object",
                "properties": {
                    "cluster": {"type": "string"},
                    "namespace": {"type": "string"},
                    "pod_name": {"type": "string"},
                },
                "required": [
                    "cluster",
                    "namespace",
                    "pod_name",
                ],
                "additionalProperties": False,
            },
        },
    }
]

response = client.chat.completions.create(
    model=llm_model(),
    messages=[
        {
            "role": "system",
            "content": (
                "你必须通过 get_pod_status 工具查询 Pod 状态。"
                "不要把工具调用写成普通文本或 XML。"
            ),
        },
        {
            "role": "user",
            "content": (
                "查询 prod-cluster 集群 default 命名空间中 "
                "payment-api-7d9c7d 的状态。"
            ),
        },
    ],
    tools=LLM_TOOLS,  # Use only the get_pod_status tool for this test
    tool_choice="auto",
    max_completion_tokens=512,
    extra_body={
        "thinking": {
            "type": "disabled"
        }
    },
)

choice = response.choices[0]
message = choice.message

print("Model:", response.model)
print("Finish reason:", choice.finish_reason)

print(
    "Tool calls:",
    [
        tool_call.model_dump()
        for tool_call in (message.tool_calls or [])
    ],
)

print("Content:", repr(message.content))
print(
    "Reasoning content:",
    repr(getattr(message, "reasoning_content", None)),
)