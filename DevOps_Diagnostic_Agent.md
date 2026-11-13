# DevOps Diagnostic Agent：课程回顾与问题排查手册

> 面向：从 DevOps / Python 自动化转向 AI Agent 应用开发的工程师  
> 项目：DevOps 故障诊断 Agent  
> 当前模型配置：MiMo `mimo-v2.6-flash`，OpenAI 兼容 Chat Completions API  
> 当前阶段：已完成基础 Agent、工具调用、结构化报告、Mock 测试、指标统计、三案例 Benchmark 和确定性前置诊断路由；下一阶段计划优化模型调用次数与响应延迟。

---

## 目录

- [1. 项目目标与整体学习路线](#1-项目目标与整体学习路线)
- [2. 项目最终架构](#2-项目最终架构)
- [3. 核心概念回顾](#3-核心概念回顾)
  - [3.1 Zero-shot、Few-shot 与 ReAct](#31-zero-shotfew-shot-与-react)
  - [3.2 Tool Calling 的工作机制](#32-tool-calling-的工作机制)
  - [3.3 为什么先手写 Agent Loop](#33-为什么先手写-agent-loop)
- [4. 项目模块与文件职责](#4-项目模块与文件职责)
- [5. 学习过程：从 Demo 到可评测 Agent](#5-学习过程从-demo-到可评测-agent)
  - [5.1 启动项目与理解代码结构](#51-启动项目与理解代码结构)
  - [5.2 实现模型工具调用循环](#52-实现模型工具调用循环)
  - [5.3 让 MiMo 返回结构化 Tool Calls](#53-让-mimo-返回结构化-tool-calls)
  - [5.4 生成结构化诊断报告](#54-生成结构化诊断报告)
  - [5.5 使用 Mock 测试 Agent Loop](#55-使用-mock-测试-agent-loop)
  - [5.6 状态管理、日志、Token 与耗时统计](#56-状态管理日志token-与耗时统计)
  - [5.7 建立 Agent Evaluation](#57-建立-agent-evaluation)
  - [5.8 扩展故障 Benchmark：Pod Not Found 与 OOMKilled](#58-扩展故障-benchmarkpod-not-found-与-oomkilled)
  - [5.9 引入确定性前置检查与动态诊断路由](#59-引入确定性前置检查与动态诊断路由)
- [6. 遇到的问题与解决方案汇总](#6-遇到的问题与解决方案汇总)
- [7. 当前 Benchmark 数据与正确解读](#7-当前-benchmark-数据与正确解读)
- [8. 常用运行与调试命令](#8-常用运行与调试命令)
- [9. 当前版本的已知限制](#9-当前版本的已知限制)
- [10. 面试复习：常见问题与回答要点](#10-面试复习常见问题与回答要点)
- [11. 下一阶段学习计划](#11-下一阶段学习计划)
- [附录 A：关键术语速查](#附录-a关键术语速查)
- [附录 B：一次诊断请求的数据流](#附录-b一次诊断请求的数据流)

---

# 1. 项目目标与整体学习路线

项目目标不是单纯做一个能聊天的机器人，而是实现一个具备以下能力的 DevOps 故障诊断 Agent：

1. 接收自然语言故障描述。
2. 查询 Kubernetes Pod 状态、应用日志和监控指标。
3. 根据证据决定是否需要继续调用其他工具。
4. 检索运维手册，结合运行证据分析可能原因。
5. 输出结构化诊断报告，包括摘要、可能原因、建议和证据。
6. 控制工具权限、执行步数和错误处理。
7. 记录运行日志、Token 用量、LLM 耗时和工具耗时。
8. 使用自动化测试与 Benchmark 验证 Agent 质量。

这条路线特别适合有 DevOps 背景的工程师：既能展示 Python 与 LLM 应用开发能力，也能把 Kubernetes、监控、日志、生产故障排查和自动化交付经验结合起来。

## 学习路线概览

| 阶段 | 学习内容 | 达成目标 |
|---|---|---|
| 1 | 项目启动与代码结构 | 本地服务可以运行 |
| 2 | ReAct / Tool Calling / Agent Loop | 理解模型如何请求调用工具 |
| 3 | MiMo 接口兼容性排查 | 模型返回标准 `tool_calls` |
| 4 | JSON 结构化报告 | 将模型输出解析为稳定的数据结构 |
| 5 | Mock 与单元测试 | 不依赖真实模型验证 Agent 行为 |
| 6 | 状态、日志、Token、耗时 | 具备基础可观测性 |
| 7 | Evaluation | 定量衡量工具选择、诊断和证据质量 |
| 8 | OOMKilled 等故障场景 | 扩展故障覆盖范围 |
| 9 | 确定性前置检查 + LLM 推理 | 降低模型漏查必要证据的风险 |
| 10 | 下一阶段：性能优化 | 减少模型调用、Token 和响应延迟 |

---

# 2. 项目最终架构

当前项目采用 **Deterministic Workflow + LLM-driven Reasoning** 的混合式架构：确定性 Python 代码保证必要的检查执行，LLM 负责基于证据进行进一步分析和动态工具选择。

```text
用户提交故障问题
       |
       v
FastAPI 接收请求 / Pydantic 校验
       |
       v
run_agent(request)
       |
       v
run_llm_agent(request)
       |
       +---- Python 前置检查：get_pod_status
       |          |
       |          +---- Pod 不存在：记录证据，不再查无关工具
       |          |
       |          +---- OOMKilled：按当前路由策略查询 Metrics
       |          |
       |          +---- CrashLoopBackOff：按当前路由策略查询 Logs
       |
       v
LLM Agent Loop
       |
       +---- 模型请求 Tool Calling
       |          |
       |          v
       |       execute_tool()
       |          |
       |          v
       |       保存 ToolCallRecord / Evidence
       |          |
       |          v
       |       role=tool 结果加入 messages
       |          |
       |          +---- 继续下一轮模型请求
       |
       +---- 模型输出初步诊断
                  |
                  v
          Structured Report Formatter
                  |
                  v
          JSON 解析与字段校验
                  |
                  v
          DiagnosisResponse
                  |
                  +---- summary
                  +---- probable_causes
                  +---- recommendations
                  +---- evidence
                  +---- tool_calls
                  +---- status
                  +---- metrics
```

### 为什么采用混合式 Agent？

- 必须执行的安全检查，不应该完全依赖 LLM 是否“想起来”调用工具。
- 已有证据足够时，不应该为了流程完整而机械查询全部工具。
- LLM 仍然适合做开放式判断，例如根据日志判断是否需要查询 Metrics 或 Runbook。
- Python 负责参数校验、工具白名单、状态控制、权限边界和最终 API 响应。

**原则：确定性代码负责必须发生的动作，LLM 负责需要推理的动作。**

---

# 3. 核心概念回顾

## 3.1 Zero-shot、Few-shot 与 ReAct

### Zero-shot

Zero-shot 指在当前 Prompt 中不提供该任务的具体示范样例，模型直接根据指令和已有知识完成任务。

例如：

```text
请判断以下句子的情绪是正面还是负面：
“今天的服务非常差。”
```

没有示例，直接要求模型分类，就是 Zero-shot。

### Few-shot

Few-shot 是在问题前提供少量示例，让模型参考示例理解任务和输出格式。

### ReAct

ReAct = Reason + Act，即推理与行动结合。Agent 根据当前问题决定是否执行动作，观察工具结果，再决定下一步。

典型循环：

```text
Question
  -> Thought / Decision
  -> Action
  -> Observation
  -> Thought / Decision
  -> ...
  -> Final Answer
```

需要区分：

- Zero-shot / Few-shot：描述当前任务是否提供示例。
- ReAct：描述 Agent 如何结合推理、行动和观察结果执行任务。
- Tool Calling：模型如何以结构化方式提出工具调用请求。

它们不是互斥概念，可以组合使用。

## 3.2 Tool Calling 的工作机制

工具调用分成两个步骤：

1. LLM 根据工具 Schema 返回一个结构化调用请求。
2. 应用程序检查请求、执行 Python 工具，并把结果作为 Tool Message 返回模型。

模型请求调用工具，不代表工具已经执行。

示意响应：

```json
{
  "name": "get_pod_status",
  "arguments": {
    "cluster": "prod-cluster",
    "namespace": "default",
    "pod_name": "payment-api-7d9c7d"
  }
}
```

Python 侧通常会执行类似逻辑：

```python
name = tool_call.function.name
arguments = json.loads(tool_call.function.arguments or "{}")
result = execute_tool(name, arguments)
```

随后将结果加入消息历史：

```python
messages.append({
    "role": "tool",
    "tool_call_id": tool_call.id,
    "content": as_json(result),
})
```

重要概念：

- `tools`：告诉模型当前有哪些可用工具及其参数 Schema。
- `tool_choice="auto"`：让模型自行判断是否请求调用工具。
- `message.tool_calls`：SDK 返回的结构化工具调用。
- `execute_tool()`：应用程序实际执行工具的入口。
- `role="tool"`：将工具执行结果交回模型。

## 3.3 为什么先手写 Agent Loop

当前项目没有一开始就引入 LangGraph，而是先通过 Python 循环理解 Agent 的底层机制。

```python
for step_index in range(request.max_steps):
    response = client.chat.completions.create(...)
    message = response.choices[0].message

    if not message.tool_calls:
        final_text = message.content or ""
        break

    # 解析并执行工具
    # 把工具结果追加到 messages
else:
    # 循环耗尽，未正常 break
    final_text = "达到最大步骤数"
```

好处：

- 每一步执行过程可见，便于学习和调试。
- 更容易理解 Tool Calling 与消息历史之间的关系。
- 可以掌握循环退出、工具白名单、错误反馈等底层机制。

后续当工作流涉及多个分支、持久化状态、人工审批、中断恢复或长期运行时，再考虑 LangGraph。

LangChain 与 LangGraph 并不冲突：LangChain 提供较高层的模型和 Agent 组件；LangGraph 提供更细粒度的有状态工作流编排能力。

---

# 4. 项目模块与文件职责

| 文件 / 目录 | 职责 |
|---|---|
| `app/main.py` | FastAPI 应用入口、HTTP 路由和 API 异常处理 |
| `app/agent.py` | Agent 主流程、LLM 调用循环、工具结果收集、报告生成 |
| `app/tools.py` | 工具实现、工具白名单、模拟 Pod / Logs / Metrics / Runbook 数据 |
| `app/schemas.py` | Pydantic 请求、响应、证据、工具记录和性能指标模型 |
| `app/config.py` | API Key、Base URL、模型名称等配置读取 |
| `tests/test_api.py` | API 层测试 |
| `tests/test_tools.py` | 工具层测试 |
| `tests/test_agent.py` | 最终报告解析与结构化输出测试 |
| `tests/test_agent_loop.py` | Mock Agent Loop 测试 |
| `evaluation/cases.json` | 故障 Benchmark 数据集 |
| `scripts/evaluate_agent.py` | 调用真实 Agent API 并计算评测指标 |

建议始终保持职责清晰：工具数据访问逻辑放在 `tools.py`，Agent 编排放在 `agent.py`，数据契约放在 `schemas.py`，评测逻辑不要混入生产 Agent 代码。

---

# 5. 学习过程：从 Demo 到可评测 Agent

## 5.1 启动项目与理解代码结构

项目最初包含 Demo 模式与 LLM 模式：

- Demo 模式：按照预设顺序执行本地模拟工具，便于没有 API Key 时验证接口。
- LLM 模式：由模型决定请求调用哪些工具，应用程序执行工具并返回结果。

本地启动：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

访问：

- Web 页面：`http://127.0.0.1:8000/`
- FastAPI 文档：`http://127.0.0.1:8000/docs`

运行测试：

```bash
pytest -q
```

初始阶段的核心学习点：

- `main.py` 接收 HTTP 请求。
- `schemas.py` 定义请求与响应格式。
- `agent.py` 决定使用 Demo 还是 LLM 模式。
- `tools.py` 提供 Agent 可以调用的能力。

## 5.2 实现模型工具调用循环

LLM 模式主要步骤：

1. 创建 OpenAI 兼容客户端。
2. 将 System Prompt、用户问题和 Tool Schema 发送给模型。
3. 检查响应是否包含 `message.tool_calls`。
4. 如果有工具调用，解析工具名与参数。
5. 调用 `execute_tool()`。
6. 保存工具执行记录和证据。
7. 将 Tool Message 加入对话历史。
8. 继续下一轮，直到模型输出最终答案或达到最大步数。

代码中的关键请求参数：

```python
response = client.chat.completions.create(
    model=llm_model(),
    messages=messages,
    tools=LLM_TOOLS,
    tool_choice="auto",
    max_completion_tokens=2048,
    extra_body={
        "thinking": {
            "type": "disabled"
        }
    },
)
```

说明：当前参数是项目当时与 MiMo `mimo-v2.6-flash` 适配后的配置。更换模型提供商或模型版本时，应重新验证接口参数和工具调用兼容性。

## 5.3 让 MiMo 返回结构化 Tool Calls

模型配置：

```dotenv
LLM_BASE_URL=https://api.xiaomimimo.com/v1
LLM_MODEL=mimo-v2.6-flash
```

密钥保存在本地 `.env`，不能提交到 Git，也不要贴到聊天或日志中。

### 问题：模型返回 XML 风格 `<tool_call>`，但 `tool_calls` 为空

最初 Agent 返回类似：

```text
<tool_call>
  <function=get_pod_status>
    ...
  </function>
</tool_call>
```

表现：

- `summary` 中出现 `<tool_call>` 文本。
- `tool_calls=[]`。
- `evidence=[]`。

这表示模型没有通过 SDK 预期的结构化 `message.tool_calls` 返回调用请求；现有 Agent Loop 因而没有执行工具。

### 最小独立测试

新建 `test_mimo_tool_call.py`，只向模型注册一个简单工具，检查：

```python
choice = response.choices[0]
message = choice.message

print("Finish reason:", choice.finish_reason)
print("Tool calls:", [
    item.model_dump()
    for item in (message.tool_calls or [])
])
print("Content:", repr(message.content))
```

独立简单工具测试返回标准结构化 Tool Call，说明模型 API 的基础 Tool Calling 能力可用。

### 逐步定位 Schema 兼容性

项目原始 `get_pod_status` Schema 中有可空类型：

```python
"pod_name": {
    "type": ["string", "null"],
    "description": "Pod 名称；不确定时传 null"
}
```

独立简单工具测试使用的是：

```python
"pod_name": {"type": "string"}
```

将项目 Schema 改为非空字符串后，单工具测试再次返回结构化 `tool_calls`。随后逐步验证 `LLM_TOOLS[:2]`、`LLM_TOOLS[:3]` 和完整 `LLM_TOOLS`，最终完整工具列表测试也通过。

结论：在当时的 MiMo 接口与 Schema 组合下，可空类型声明是一个关键兼容性因素。不能将此结论泛化为所有模型都不支持 nullable Schema；更换服务后需重新测试。

## 5.4 生成结构化诊断报告

初版模型最终回答会将 Markdown 报告放在 `summary`，而 `probable_causes` 和 `recommendations` 仍然是默认空值或默认提示。

因此增加 `parse_final_report()`，负责将模型返回文本解析为：

```json
{
  "summary": "故障摘要",
  "probable_causes": ["可能原因 1", "可能原因 2"],
  "recommendations": ["建议 1", "建议 2"]
}
```

建议将 `parse_final_report()` 定义为 `app/agent.py` 的顶层函数，放在 `run_llm_agent()` 之前，而不是放在其他函数内部。

解析逻辑需要包含：

- JSON 解析。
- 根对象类型检查。
- `summary` 字符串校验。
- `probable_causes` 与 `recommendations` 列表校验。
- 解析失败时使用明确的 fallback。

注意：Fallback 是容错机制，不应让评测把没有有效证据的 fallback 报告判定为成功。

### MiMo 输出 JSON 后附带 XML 闭合标签

曾出现如下情况：

```text
{"summary": "...", "recommendations": ["..."]}</parameter>
```

`json.loads()` 报：

```text
JSONDecodeError: Extra data
```

原因：JSON 本身结束后还有 XML 标签。

修复思路：使用 `JSONDecoder().raw_decode()` 解析开头的 JSON，再严格检查剩余后缀，只允许已知闭合标签，例如：

```python
r"(?:</(?:parameter|function|tool_call)>)+"
```

任何未知尾部文本都应该拒绝，不能无条件丢弃。

### OOM 报告缺少数组结束符

曾出现：

```text
JSONDecodeError: Expecting ',' delimiter
```

错误位置位于 `recommendations` 数组最后一项附近，模型输出的 JSON 结构没有正确关闭。

这不是尾部 XML 问题，而是 JSON 内部结构不完整。由此决定尝试使用模型服务的 JSON Mode，并将最终报告格式化拆成单独的请求。

### JSON Mode 的注意点

尝试请求参数：

```python
response_format={"type": "json_object"}
```

JSON Mode 的目标是提高 JSON 语法合法性；它不自动保证字段完整、数组非空或诊断正确。因此仍需 `parse_final_report()` 和 Pydantic / 业务规则校验。

项目当时采用独立 `generate_structured_report()`：

- Agent Loop 先调用工具并收集证据。
- 模型生成初步诊断。
- Formatter 单独请求模型，输出 JSON。

这会多一次模型请求，增加延迟和 Token，但职责更清晰。后续是否能将工具调用与结构化输出合并，需要单独验证模型 API 的兼容性。

## 5.5 使用 Mock 测试 Agent Loop

为了不依赖真实 MiMo API、不产生费用，并且确定性地测试 Agent 行为，引入 Mock 模型。

核心类：

- `FakeToolCall`：模拟模型返回的工具调用对象。
- `make_response()`：模拟 Chat Completion 响应。
- `FakeCompletions`：按预设顺序返回响应。
- `prepare_test()`：替换真实 OpenAI Client 和模型配置。

### `responses` 是什么？

`responses` 是预先安排好的模型响应队列，不是真实模型动态生成的结果。

```python
responses = [
    # 第一次模型响应：请求调用工具
    make_response(
        content="",
        tool_calls=[
            FakeToolCall("get_pod_status", status_call, "call_1")
        ],
    ),

    # 第二次模型响应：继续请求工具（例如模拟重试）
    make_response(
        content="",
        tool_calls=[
            FakeToolCall("get_pod_status", status_call, "call_2")
        ],
    ),

    # 第三次模型响应：输出最终报告
    make_response(content=final_report()),
]
```

`FakeCompletions.create()` 中：

```python
return self.responses.pop(0)
```

`pop(0)` 会取出列表第一个元素并删除。每调用一次模拟模型接口，就返回队列中的下一条预设响应。

### Mock 模型与 Mock 工具要区分

- Mock 模型：模拟 LLM 每一轮返回什么。
- Mock 工具：模拟工具执行时发生什么，例如第一次超时、第二次成功。

测试通过预设响应序列验证 Agent 是否正确处理成功、失败、错误反馈和结束条件。Mock 测试只能证明程序按预设序列正确运行，不能证明真实模型每次都会做出相同行为。

## 5.6 状态管理、日志、Token 与耗时统计

### Agent 状态

给 `DiagnosisResponse` 增加 `status`，区分：

- `completed`：模型正常输出最终回答。
- `max_steps_reached`：达到最大模型交互轮次，仍未完成。
- `no_final_answer`：模型没有工具调用，也没有有效最终文本。

Python 的 `for ... else`：只有循环没有通过 `break` 提前退出时才执行 `else`，适合表达达到最大步数。

注意：当前 `max_steps` 限制的是 LLM Agent Loop 的模型交互轮数；Python 前置工具调用和独立 Formatter 请求是否计入，需要在实现中明确。后续应另设总工具调用上限，避免前置工具数量无限增长。

### 日志

常见日志事件：

```text
agent_llm_call
agent_tool
agent_structured_report
agent_report_raw
agent_report_parsed
agent_run_completed
```

建议记录：

- 模型交互轮次。
- LLM 请求耗时。
- `finish_reason`。
- Tool Call 数量。
- 工具名、成功状态、异常类型和工具耗时。
- Token Usage。
- 最终总耗时和统计摘要。

不应在普通日志中输出 API Key、密码、完整敏感 Prompt 或未经脱敏的生产日志。

### ToolCallRecord 与 AgentMetrics

`ToolCallRecord` 记录单次工具执行，例如：

```python
class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict[str, Any]
    success: bool
    result_preview: str
    duration_ms: float = Field(default=0.0, ge=0)
```

`AgentMetrics` 记录整个诊断过程的聚合指标，例如：

```python
class AgentMetrics(BaseModel):
    total_elapsed_ms: float = 0.0
    llm_call_count: int = 0
    llm_latency_ms_total: float = 0.0
    llm_latency_ms_avg: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_usage_available: bool = False
    tool_call_count: int = 0
    tool_latency_ms_total: float = 0.0
    tool_failure_count: int = 0
```

统计含义：

- `prompt_tokens`：累计每轮请求的输入 Token。
- `completion_tokens`：累计每轮响应的输出 Token。
- `total_tokens`：累计输入与输出 Token。
- `llm_latency_ms_total`：所有模型请求耗时之和。
- `llm_latency_ms_avg`：平均每次模型请求耗时。
- `tool_latency_ms_total`：所有工具调用耗时之和。
- `total_elapsed_ms`：完整诊断从开始到结束的墙钟时间。

每轮模型都会重新提交部分或全部历史消息，因此累计 `prompt_tokens` 会重复计算上下文，这正是实际 API 成本的重要组成部分。

`token_usage_available=false` 表示服务没有返回可用的 Usage，不代表真实 Token 用量一定为零。

### 计时

使用：

```python
started = time.perf_counter()
# 执行操作
elapsed_ms = (time.perf_counter() - started) * 1000
```

`perf_counter()` 适合测量经过时间。

注意：工具总耗时之和与整个请求的墙钟耗时不是同一概念；并发工具执行时，工具耗时之和可能超过墙钟耗时。

## 5.7 建立 Agent Evaluation

建立 `evaluation/cases.json`，保存问题、输入参数、预期工具、允许工具、必要证据和预期诊断知识点。

建立 `scripts/evaluate_agent.py`，通过 HTTP 调用正在运行的 FastAPI 服务，并计算评测指标。

核心指标：

### Tool Recall

$$
Tool\ Recall = \frac{成功执行的必要工具数量}{预期必要工具数量}
$$

### Diagnosis Accuracy（当前是规则化 Finding Match）

$$
Finding\ Match\ Rate = \frac{匹配的预期诊断知识点数量}{预期诊断知识点总数}
$$

当前实现主要基于关键词或同义表达匹配，是简化的规则评测，不等同于完整语义准确率。

### Evidence Recall

$$
Evidence\ Recall = \frac{实际提供的必要证据来源数量}{要求的必要证据来源数量}
$$

### Report Complete

检查摘要非空、建议数量达标、状态为 completed，并且必要工具和证据满足要求。

评测数据应保持独立于 Agent 实现，不能为了通过测试而随意降低预期要求。

### 单元测试、集成测试、Agent Evaluation 的区别

| 类型 | 目标 | 是否需要真实模型 |
|---|---|---|
| Unit Test | 测试单个函数 / 工具 | 否 |
| Mock Integration Test | 测试 Agent 各组件协作和执行流程 | 否，可用 Mock |
| Agent Evaluation | 测量真实模型工具选择、诊断与输出质量 | 通常需要 |
| Performance Test | 测量延迟、Token、吞吐量 | 真实运行更有意义 |

## 5.8 扩展故障 Benchmark：Pod Not Found 与 OOMKilled

### Case 1：数据库认证失败

模拟信息：

- Pod：`payment-api-7d9c7d`
- 状态：`CrashLoopBackOff`
- 重启次数：8
- 最近退出码：1
- 日志：`password authentication failed for user "app_user"`
- 监控：CPU 12.4%，Memory 38.1%，HTTP 5xx 7.8%

核心诊断方向：应用使用的数据库凭据与数据库端不一致，可能与 Secret 引用错误或密码轮换未同步有关。

### Case 2：Pod Not Found

模拟 Pod：`unknown-api-123`。

预期行为：

- 查询 Pod 状态。
- 得到 `found=false`。
- 不应编造故障根因。
- 不应继续查询不必要的日志或指标。
- 返回明确的“资源不存在 / 未找到”说明。

### Case 3：OOMKilled

模拟信息：

- Pod：`inventory-api-6f8c9d`
- 容器状态：`CrashLoopBackOff`
- 重启次数：5
- Last Exit Code：137
- Last Termination Reason：`OOMKilled`
- Memory：97.8%
- CPU：42.3%
- HTTP 5xx：12.6%
- 日志提示：内存接近容器上限、大缓存分配。

重要知识点：

- `OOMKilled` 表示容器最近一次终止原因为内存超限。
- `CrashLoopBackOff` 描述反复启动失败后的重启等待状态。
- 137 通常与 SIGKILL 有关，但单凭 137 不能确定是 OOM。
- 应结合 termination reason、Pod Events、内存指标和日志综合判断。

## 5.9 引入确定性前置检查与动态诊断路由

### 为什么需要改造？

新增 JSON Formatter 后曾出现：模型第一轮 `finish_reason=stop`、`tool_calls=0`，直接生成报告，没有调用工具。

原始 LLM 请求使用：

```python
tools=LLM_TOOLS
tool_choice="auto"
```

`auto` 允许模型决定不调用工具。因此，对于必须先查询 Pod 的任务，仅靠 Prompt 不是可靠保障。

### 混合式路由

当前方案：

1. Python 强制执行 `get_pod_status`。
2. Pod 不存在：停止无关诊断。
3. 如果 `last_termination_reason == "OOMKilled"`：查询 Metrics。
4. 如果 `container_status == "CrashLoopBackOff"`：查询 Logs。
5. 将前置工具调用和结果按标准 assistant tool_calls / tool message 形式加入消息历史。
6. LLM 基于现有证据决定是否需要额外工具。
7. Formatter 生成最终 JSON。

### Python 前置工具消息为什么要加入 messages？

因为模型需要知道这些工具已经执行过，避免重复请求。应用程序应将执行调用与工具结果以模型 API 支持的标准消息结构加入历史，而不是只把结果当作普通用户文本。

### 当前路由的限制

目前是简单规则：Pod Not Found、OOMKilled、CrashLoopBackOff。未来应扩展更多状态，并确保路由规则和 Benchmark 一致；同时需要总工具调用上限、异常分支以及对前置工具失败的处理。

---

# 6. 遇到的问题与解决方案汇总

| 问题 / 现象 | 定位方法 | 原因 / 解决方案 |
|---|---|---|
| 模型把 `<tool_call>...</tool_call>` 放进 `content`，`tool_calls=[]` | 写单工具独立测试，检查原始 SDK 响应 | 先确认模型 API 能否返回标准结构化 Tool Calls；比较简单 Schema 与项目 Schema |
| 独立工具测试成功，项目工具 Schema 测试失败 | 逐步测试 `LLM_TOOLS[:1]`、`:2`、`:3` 和完整列表 | 项目 `pod_name` 的 nullable 声明与简单测试存在差异；改成必需 `string` 后恢复。此结论限于当前模型 / API 组合 |
| `max_completion_tokens` 与 thinking 配置 | 使用模型提供商兼容参数进行独立测试 | 当前 MiMo 配置采用 `thinking: {type: disabled}`；更换模型后必须复测 |
| `parse_final_report()` 找不到合适位置 | 搜索 `def run_llm_agent` | 将解析函数定义在 `app/agent.py` 顶层，放在 `run_llm_agent()` 之前 |
| `JSONDecodeError: Extra data` | 检查错误位置和文本尾部 | JSON 后面附带 `</parameter>`；使用 `raw_decode()`，并对尾部闭合标签做严格白名单校验 |
| `JSONDecodeError: Expecting ',' delimiter` | 打印错误位置、context 和 tail | JSON 内部数组未正确结束，模型输出语法不完整；尝试 JSON Mode / 独立结构化报告请求 |
| JSON Mode 后工具调用变成 0 | 检查 `finish_reason`、`tool_calls`、工具记录和 Evidence | 模型第一轮直接回答，Formatter 再格式化，形成无证据报告；增加 Python 必要的前置检查，并要求评测验证证据完整性 |
| `report_complete=false`，但诊断知识点正确 | 增加 `report_checks` 逐项输出 | 实际只返回 1 条建议，案例要求至少 2 条；检查模型原始响应与解析后数量，不能简单降低阈值 |
| `list.append() takes no keyword arguments` | 搜索 `duration_ms=` | `duration_ms` 放在 `calls.append()` 的括号层级，而不是 `ToolCallRecord(...)` 内部；将字段移入 Pydantic 记录构造函数 |
| API 测试 HTTP 502 | 检查服务端异常日志 | 与上述 `list.append()` TypeError 是同一根因；修复后重新跑 API 测试 |
| Mock 测试断言工具调用数量失败 | 对照新 Agent 执行流程 | 加入 Python preflight 和 Formatter 后，工具调用数 / 模型请求次数发生变化；更新 Mock 响应队列和预期调用顺序 |
| 外层 Evaluation 报 `timed out` | 区分 `urlopen` 外层超时和 SDK 请求超时 | Evaluation HTTP timeout 从 120 秒调整到 300 秒；SDK 的 45 秒请求超时是另一层，不能混为一谈 |
| `StarletteDeprecationWarning` | 查看 warning 信息 | 测试客户端依赖的弃用提示，不是本次测试失败；后续依赖升级时统一处理 |
| OOMKilled 只凭 exit code 137 判断 | 检查终止原因、Events、Metrics | 137 通常意味着 SIGKILL，必须结合 `OOMKilled` termination reason 与内存证据 |
| 完整报告有建议，但 Evidence 为空仍被评为完整 | 检查 `report_complete` 判定条件 | 将 `tool_recall == 1.0`、`evidence_recall == 1.0` 加入完整性条件 |

## 6.1 排错时建议遵循的顺序

1. 先看 HTTP 状态和 API 异常。
2. 再看 `finish_reason` 与 `message.tool_calls`。
3. 确认工具是否真正执行，检查 `tool_calls` 和 `evidence`。
4. 检查最终模型原始文本与 JSON 解析错误位置。
5. 检查 Pydantic 响应模型和 Evaluation 规则。
6. 最后才调整 Prompt、Schema、模型参数或超时设置。

原则：**一次只改变一个变量；用最小复现定位问题；保留原始错误信息；不要通过降低评测标准掩盖真实缺陷。**

---

# 7. 当前 Benchmark 数据与正确解读

截至目前，最近一次完整的三个案例 Benchmark 结果为 3/3 通过。

| Case | 总耗时 | LLM 调用次数 | Token | 工具调用次数 | 结果 |
|---|---:|---:|---:|---:|---|
| Database Authentication | 32.68 s | 2 | 3,364 | 2 | PASS |
| Pod Not Found | 37.49 s | 2 | 2,914 | 1 | PASS |
| OOMKilled | 33.51 s | 2 | 3,236 | 2 | PASS |

汇总：

- 案例数：3。
- 通过：3。
- 失败：0。
- 当前样本通过率：100%。
- 平均 Token：约 3,171。
- 平均诊断耗时：约 34.56 秒。

必须正确解读：

1. 100% 只是这三个已知模拟案例的规则评测通过率，不代表真实生产故障总体准确率。
2. 当前工具使用模拟数据，工具耗时非常小，不能代表真实 Kubernetes / Prometheus / ELK API 延迟。
3. 当前诊断耗时主要来自 LLM API。三个案例的 LLM 请求耗时占总耗时的大部分。
4. 评测规则中 Diagnosis Accuracy 主要通过预设关键词 / 同义词匹配，属于简化 Benchmark。
5. Token Usage 由模型 API 返回，缺失时应标注 `token_usage_available=false`，不能把未知用量当作零。

未来扩展 Benchmark 时，应加入更多故障类型、不同语言表达、证据冲突、工具超时、模型输出异常和无关问题等测试。

---

# 8. 常用运行与调试命令

## 启动虚拟环境

```bash
source .venv/bin/activate
```

## 启动 FastAPI

```bash
uvicorn app.main:app --reload
```

## 运行所有自动化测试

```bash
pytest -q
```

## 运行 Agent Loop 测试

```bash
pytest -q tests/test_agent_loop.py
```

## 运行工具测试

```bash
pytest -q tests/test_tools.py
```

## 运行报告解析测试

```bash
pytest -q tests/test_agent.py
```

## 运行 API 测试

```bash
pytest -q tests/test_api.py
```

## 运行真实模型 Benchmark

先启动 FastAPI 服务，再在另一个终端执行：

```bash
python scripts/evaluate_agent.py
```

该命令会调用真实 MiMo API，会消耗 Token 并产生模型调用成本。Kubernetes、日志、监控工具仍为本地模拟数据，不会修改真实集群。

## 只跑某一个案例

在调试阶段，可以临时筛选：

```python
cases = [
    case
    for case in json.load(file)
    if case["id"] == "inventory-oom-001"
]
```

完成后必须恢复：

```python
cases = json.load(file)
```

否则完整 Benchmark 会只运行一个案例。

---

# 9. 当前版本的已知限制

1. **模拟工具数据**：Pod、日志、指标和 Runbook 仍是本地 Fixture，不是真实集群查询。
2. **故障类型有限**：目前 Benchmark 主要包含数据库认证失败、Pod 不存在和 OOMKilled。
3. **诊断路由有限**：Python 前置规则覆盖少量状态，尚未形成全面故障分类体系。
4. **JSON Formatter 增加一次模型请求**：提高格式化稳定性，但增加 Token 和延迟。
5. **模型响应时间不稳定**：MiMo API 的延迟可能随服务负载、Prompt 长度和生成长度变化。
6. **评测指标较简单**：Keyword Finding Match 不能完全衡量语义正确性、推理质量和证据因果关系。
7. **还没有真正的人工审批工作流**：当前安全提示和只读工具限制不等同于完整生产审批系统。
8. **没有真实多租户权限隔离**：生产部署前需要增加身份认证、租户隔离、工具授权和审计。
9. **尚未做生产级 RAG**：当前 Runbook 是简单本地检索，不是完整的文档解析、Embedding、向量检索和 Reranker 流程。
10. **缺少总工具执行预算**：`max_steps` 主要约束 LLM 交互轮次，未来还要对 Python 前置工具、LLM 工具和总工具调用次数统一设限。

---

# 10. 面试复习：常见问题与回答要点

## Q1：Agent 和普通 LLM Chain 有什么区别？

- Chain 通常按照预先定义的步骤执行。
- Agent 能基于当前输入和工具结果，动态决定下一步行动。
- 本项目采用确定性前置检查与 LLM 动态工具选择相结合的混合架构。

## Q2：ReAct 的执行过程是什么？

模型根据问题决定 Action，应用程序执行工具并返回 Observation，模型再根据 Observation 决定下一步，直到输出 Final Answer 或达到限制。

## Q3：模型返回 tool_calls 是否表示工具已经执行？

不是。它只是结构化的调用请求。应用程序必须验证工具名称、参数和权限，再调用实际 Python 函数。

## Q4：为什么不完全依靠 LLM 决定要不要查 Pod？

因为某些检查是业务和安全要求，不能依赖模型每次都能正确选择。确定性 Python 前置检查可以保证必要证据被收集，LLM 再负责动态推理。

## Q5：为什么使用 Mock？

Mock 可以固定模型响应和工具故障行为，测试 Agent Loop 的确定性逻辑，不需要真实 API Key、网络和 Token 费用。但 Mock 测试不能代替真实模型 Evaluation。

## Q6：如何处理模型输出非法 JSON？

先记录并检查原始输出与解析异常位置；使用 JSON Mode / Structured Output 提高格式合法性；使用 `raw_decode()` 处理明确允许的格式尾缀；最后进行 Pydantic 和业务字段校验。不能无条件丢弃未知尾部内容。

## Q7：如何衡量 Agent 质量？

使用 Tool Recall、工具顺序、Finding Match、Evidence Recall、Report Completeness、工具失败率、Latency 和 Token Usage。当前项目用小型 Benchmark 验证基础能力，后续应扩充真实多样化案例并加入人工评审。

## Q8：如何降低 Agent 成本和延迟？

- 减少不必要的模型交互轮数。
- 精简重复传递的对话历史。
- 使用确定性代码处理简单规则。
- 避免重复查询工具。
- 评估是否能将诊断与结构化输出合并为一次模型请求。
- 监控每次请求的输入、输出 Token 和 P50 / P95 延迟。

## Q9：OOMKilled 和 CrashLoopBackOff 有什么区别？

OOMKilled 是容器终止原因；CrashLoopBackOff 是反复启动失败后的重启等待状态。两者可能同时出现，但含义不同。Exit Code 137 不能单独证明 OOM。

## Q10：为什么当前项目暂时不用 LangGraph？

当前状态与循环较简单，手写 Python Loop 有利于理解底层机制。复杂分支、持久化、人工审批、中断恢复和长任务管理增多后，再考虑 LangGraph 更合适。

---

# 11. 下一阶段学习计划

下一阶段原计划为第 12 课：减少 LLM 调用次数和诊断延迟。

建议按以下顺序推进：

1. **建立优化前基线**：固定三个 Benchmark，记录平均 Token、总耗时、LLM 调用次数和通过率。
2. **验证模型 API 组合能力**：确认 MiMo 是否支持 Tool Calling 与 JSON Mode / Structured Output 的兼容组合，不能假定参数组合一定有效。
3. **尝试一次生成结构化报告**：在保留工具调用正确性的前提下，评估能否避免独立 Formatter 请求。
4. **优化消息历史**：研究哪些工具结果和历史消息必须保留，哪些可以压缩为摘要。
5. **防止重复工具调用**：维护已执行工具、参数和调用预算，避免模型重复查询相同资源。
6. **增加预算控制**：设置每次诊断的最大 LLM 调用数、最大工具调用数、总耗时和 Token 预算。
7. **回归测试**：每次优化后运行 21 项以上自动化测试，并运行三个真实模型 Benchmark。
8. **比较优化前后**：只有质量不下降、成本和延迟确有改善，才接受优化。

后续还可以继续扩展：

- ImagePullBackOff。
- CPU Throttling。
- Liveness / Readiness Probe Failure。
- DNS / Network Failure。
- Database Connection Timeout。
- RAG 运维知识库。
- Prometheus / Kubernetes 只读真实 API 集成。
- LangGraph 工作流版本。
- Human-in-the-loop 审批。
- Docker / CI/CD / Prometheus / Grafana 部署与可观测性。

---

# 附录 A：关键术语速查

| 术语 | 含义 |
|---|---|
| LLM | Large Language Model，大语言模型 |
| Agent | 能根据任务选择行动、调用工具并利用结果继续执行的应用系统 |
| Tool Calling | 模型通过结构化请求要求应用调用工具 |
| ReAct | Reason + Act，推理与行动循环 |
| Zero-shot | 当前 Prompt 不提供具体任务示例 |
| Few-shot | 当前 Prompt 提供少量示例 |
| Observation | 工具执行后返回给 Agent 的结果 |
| Tool Schema | 工具的名称、描述、参数结构和约束 |
| `tool_calls` | Chat Completion 响应中的结构化工具调用列表 |
| `finish_reason` | 模型本轮响应的结束原因，例如 `tool_calls` 或 `stop` |
| Mock | 用预设行为替代真实依赖进行测试 |
| Evaluation | 对 Agent 实际行为与输出质量进行评估 |
| Benchmark | 一组固定、可重复运行的评测案例 |
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| JSON Mode | 要求模型以 JSON 格式输出的接口能力 |
| Structured Output | 根据结构或 Schema 约束模型输出 |
| Pydantic | Python 数据校验与序列化工具 |
| Latency | 请求或操作耗时 |
| P95 | 95% 的请求耗时不超过该数值的分位数指标 |
| Token Usage | 模型输入与输出 Token 用量 |
| OOMKilled | 容器因内存超限被终止 |
| CrashLoopBackOff | 容器反复启动失败后的重启等待状态 |
| LLMOps | LLM / Agent 应用部署、监控、评测、成本和运行维护实践 |

# 附录 B：一次诊断请求的数据流

以数据库认证失败案例为例：

1. 用户提交：`payment-api 为什么频繁重启？`
2. FastAPI 将请求校验为 `DiagnoseRequest`。
3. Python 前置查询 `get_pod_status`。
4. 根据 `CrashLoopBackOff` 路由查询 `get_pod_logs`。
5. 工具结果保存到 `evidence` 和 `tool_calls`，并作为 Tool Message 进入模型对话历史。
6. LLM 看到 `password authentication failed for user "app_user"`，决定是否还需要查询 Metrics 或 Runbook。
7. Agent Loop 继续执行额外工具，直到模型返回最终分析或达到步数限制。
8. Structured Report Formatter 根据用户问题、证据和初步分析生成 JSON。
9. `decode_report_json()` / `parse_final_report()` 解析和校验最终报告。
10. Pydantic 组装 `DiagnosisResponse`。
11. API 返回 summary、probable causes、recommendations、evidence、tool calls、status 和 metrics。
12. Evaluation 脚本检查必要工具、Finding、Evidence、报告完整性与性能指标。

---

## 学习记录

- 已完成：项目本地启动与 Demo 验证。
- 已完成：MiMo 结构化 Tool Calling 调试。
- 已完成：工具执行与 Agent Loop。
- 已完成：结构化报告解析与 JSON 兼容处理。
- 已完成：Mock Agent Loop 测试。
- 已完成：状态、日志、Token 和耗时统计。
- 已完成：三个模拟故障 Benchmark，最近一次结果为 3/3 通过。
- 当前待做：合并或优化诊断与结构化输出请求，降低 LLM 调用成本和延迟。

> 重要提醒：以上结果以当前对话中报告的代码和测试结果为依据。整理笔记时没有重新运行用户本地项目；实际代码若有后续修改，应以本地仓库为准，并持续运行 `pytest -q` 与 Benchmark 回归验证。
