import json
import pytest
from types import SimpleNamespace

import openai

import app.agent as agent_module
from app.schemas import DiagnoseRequest
from app.tools import execute_tool as real_execute_tool


class FakeToolCall:
    """模拟 OpenAI SDK 返回的工具调用对象。"""

    def __init__(self, name, arguments, call_id="call_test_001"):
        self.id = call_id
        self.type = "function"
        self.function = SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        )

    def model_dump(self, exclude_none=True):
        return {
            "id": self.id,
            "type": self.type,
            "function": {
                "name": self.function.name,
                "arguments": self.function.arguments,
            },
        }


def make_response(
    content=None,
    tool_calls=None,
    usage=None,
):
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
    )

    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=message)
        ],
        usage=usage,
    )


class FakeCompletions:
    """按照预设顺序返回模型响应，不发送真实 API 请求。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)

        if not self.responses:
            raise AssertionError("模型请求次数超过预设测试响应数量")

        return self.responses.pop(0)


def prepare_test(monkeypatch, responses):
    """注入假客户端和测试配置。"""
    completions = FakeCompletions(responses)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        agent_module, "llm_api_key", lambda: "test-key"
    )
    monkeypatch.setattr(
        agent_module, "llm_base_url", lambda: ""
    )
    monkeypatch.setattr(
        agent_module, "llm_model", lambda: "fake-model"
    )

    return completions


def make_request():
    return DiagnoseRequest(
        question="payment-api 为什么频繁重启？",
        cluster="prod-cluster",
        namespace="default",
        pod_name="payment-api-7d9c7d",
        mode="llm",
        max_steps=4,
    )


def final_report():
    return json.dumps(
        {
            "summary": "Pod 因数据库认证失败而反复重启。",
            "probable_causes": ["数据库凭据不匹配"],
            "recommendations": ["核对 Secret 引用和凭据轮换记录"],
        },
        ensure_ascii=False,
    )


def test_agent_executes_tool_and_returns_report(monkeypatch):
    """前置检查、LLM 工具调用和最终报告均应成功。"""

    metrics_call = {
        "cluster": "prod-cluster",
        "namespace": "default",
        "pod_name": "payment-api-7d9c7d",
    }

    responses = [
        # 第一次：LLM 根据前置证据决定查询监控指标。
        make_response(
            content="",
            tool_calls=[
                FakeToolCall(
                    "query_metrics",
                    metrics_call,
                    "call_metrics",
                )
            ],
        ),

        # 第二次：LLM 根据所有证据生成初步诊断。
        make_response(content=final_report()),

        # 第三次：JSON Formatter 生成结构化报告。
        make_response(content=final_report()),
    ]

    completions = prepare_test(monkeypatch, responses)

    result = agent_module.run_llm_agent(make_request())

    # 两次前置工具 + 一次 LLM 工具调用
    assert len(result.tool_calls) == 3

    # 两次 Agent 模型请求 + 一次 JSON Formatter 请求
    assert len(completions.requests) == 3

    assert result.summary == "Pod 因数据库认证失败而反复重启。"

    assert result.probable_causes == [
        "数据库凭据不匹配"
    ]

    assert result.status == "completed"

    # 检查工具调用顺序
    assert [
        item.tool for item in result.tool_calls
    ] == [
        "get_pod_status",
        "get_pod_logs",
        "query_metrics",
    ]

    assert all(
        item.success for item in result.tool_calls
    )

    assert len(result.evidence) == 3


def test_agent_can_retry_after_tool_error(monkeypatch):
    """前置检查后，LLM 工具失败，模型重新请求后成功。"""

    metrics_call = {
        "cluster": "prod-cluster",
        "namespace": "default",
        "pod_name": "payment-api-7d9c7d",
    }

    responses = [
        # 第一次：模型请求查询指标。
        make_response(
            content="",
            tool_calls=[
                FakeToolCall(
                    "query_metrics",
                    metrics_call,
                    "call_1",
                )
            ],
        ),

        # 第二次：模型收到超时错误，再次请求查询指标。
        make_response(
            content="",
            tool_calls=[
                FakeToolCall(
                    "query_metrics",
                    metrics_call,
                    "call_2",
                )
            ],
        ),

        # 第三次：生成初步诊断。
        make_response(content=final_report()),

        # 第四次：JSON Formatter。
        make_response(content=final_report()),
    ]

    completions = prepare_test(monkeypatch, responses)

    attempts = {"count": 0}

    def flaky_execute_tool(name, arguments):
        if name == "query_metrics" and attempts["count"] == 0:
            attempts["count"] += 1

            raise TimeoutError(
                "simulated temporary timeout"
            )

        return real_execute_tool(name, arguments)

    monkeypatch.setattr(
        agent_module,
        "execute_tool",
        flaky_execute_tool,
    )

    result = agent_module.run_llm_agent(make_request())

    # 4 次模型请求：
    # 2 次工具调用 + 1 次初步诊断 + 1 次 JSON Formatter
    assert len(completions.requests) == 4

    # 2 次前置工具 + 2 次指标工具调用
    assert len(result.tool_calls) == 4

    assert [
        item.tool for item in result.tool_calls
    ] == [
        "get_pod_status",
        "get_pod_logs",
        "query_metrics",
        "query_metrics",
    ]

    # 前置检查成功
    assert result.tool_calls[0].success is True
    assert result.tool_calls[1].success is True

    # 第一次指标查询失败，第二次成功
    assert result.tool_calls[2].success is False
    assert result.tool_calls[3].success is True

    assert "simulated temporary timeout" in (
        result.tool_calls[2].result_preview
    )

    # 检查错误是否被反馈给模型
    second_request_messages = completions.requests[1]["messages"]

    assert any(
        message.get("role") == "tool"
        and "simulated temporary timeout"
        in message.get("content", "")
        for message in second_request_messages
    )

    assert result.status == "completed"

    # 前置状态、前置日志、最终成功的指标查询
    assert len(result.evidence) == 3

    assert result.evidence[-1].source == "query_metrics"


def test_agent_stops_when_max_steps_reached(monkeypatch):
    """达到最大 LLM 交互轮次后，应明确标记未完成。"""

    responses = [
        # Python 已经完成 Pod 状态和日志前置检查。
        # 这里模拟 LLM 再次请求查询监控指标。
        make_response(
            content="",
            tool_calls=[
                FakeToolCall(
                    "query_metrics",
                    {
                        "cluster": "prod-cluster",
                        "namespace": "default",
                        "pod_name": "payment-api-7d9c7d",
                    },
                    "call_metrics",
                )
            ],
        )
    ]

    completions = prepare_test(monkeypatch, responses)

    request = DiagnoseRequest(
        question="检查 payment-api 的状态",
        cluster="prod-cluster",
        namespace="default",
        pod_name="payment-api-7d9c7d",
        mode="llm",
        max_steps=1,
    )

    result = agent_module.run_llm_agent(request)

    assert result.status == "max_steps_reached"

    assert "最大步骤数" in result.summary

    # 两次 Python 前置工具 + 一次 LLM 工具调用
    assert len(result.tool_calls) == 3

    assert [
        item.tool for item in result.tool_calls
    ] == [
        "get_pod_status",
        "get_pod_logs",
        "query_metrics",
    ]

    # max_steps=1，只允许一次 LLM Agent Loop 请求。
    # 没有完成诊断，因此不应该执行 JSON Formatter。
    assert len(completions.requests) == 1

        # 4. LLM 请求次数应该准确记录
    assert result.metrics.llm_call_count == 1

    # 5. 工具调用数量应该与实际记录一致
    assert result.metrics.tool_call_count == 3

    # 6. 三次工具调用均成功，不应产生失败计数
    assert result.metrics.tool_failure_count == 0

    # 7. Pod 状态、日志、监控指标证据都应该保留
    assert len(result.evidence) == 3

    # 8. 已经执行过的工具调用应该有耗时记录
    assert result.metrics.tool_latency_ms_total >= 0

    # 9. 没有完成诊断，不应该进行额外的 Formatter 请求
    assert len(completions.requests) == 1



def test_preflight_tool_failure_is_recorded(monkeypatch):
    """Preflight 工具失败时，应记录错误并继续构造消息历史。"""

    def mock_execute_tool_timed(name, arguments):
        if name == "get_pod_logs":
            return (
                None,
                3.456,
                PermissionError(
                    "simulated permission denied"
                ),
            )

        raise AssertionError(
            f"Unexpected tool: {name}"
        )

    monkeypatch.setattr(
        agent_module,
        "_execute_tool_timed",
        mock_execute_tool_timed,
    )

    messages = []
    calls = []
    evidence = []

    result = agent_module.execute_and_record(
        name="get_pod_logs",
        arguments={
            "cluster": "prod-cluster",
            "namespace": "default",
            "pod_name": "payment-api-7d9c7d",
        },
        messages=messages,
        calls=calls,
        evidence=evidence,
    )

    # 1. 工具失败时返回 None，不向调用者抛出异常
    assert result is None

    # 2. 应记录一次失败的工具调用
    assert len(calls) == 1
    assert calls[0].tool == "get_pod_logs"
    assert calls[0].success is False

    # 3. 错误信息应记录在调用结果中
    assert "simulated permission denied" in (
        calls[0].result_preview
    )

    # 4. 失败的工具不能被记录为有效证据
    assert len(evidence) == 0

    # 5. 应当产生 assistant tool_call 消息和 tool 结果消息
    assert len(messages) == 2

    assert messages[0]["role"] == "assistant"
    assert messages[1]["role"] == "tool"

    # 6. tool_call_id 必须匹配
    assert (
        messages[0]["tool_calls"][0]["id"]
        == messages[1]["tool_call_id"]
    )

    # 7. LLM 能够从工具消息中读取错误
    tool_result = json.loads(messages[1]["content"])

    assert tool_result["tool"] == "get_pod_logs"
    assert (
        tool_result["error"]
        == "simulated permission denied"
    )



def test_decode_report_json_rejects_truncated_json():
    """截断的 JSON 应解析失败，而不是返回不完整对象。"""

    invalid_json = """
    {
        "summary": "Pod is restarting",
        "probable_causes":
    """

    data, trailing = agent_module.decode_report_json(
        invalid_json
    )

    assert data is None
    assert trailing == ""


def test_parse_final_report_returns_fallback_for_invalid_json():
    """非法 JSON 应返回安全的 fallback 报告。"""

    invalid_json = """
    {
        "summary": "Pod is restarting",
        "probable_causes":
    """

    report = agent_module.parse_final_report(
        invalid_json
    )

    assert report["summary"] == invalid_json.strip()
    assert report["probable_causes"] == []
    assert report["recommendations"] == [
        "请结合工具证据人工复核诊断结果。"
    ]



def test_agent_survives_invalid_json_and_formatter_failure(monkeypatch):
    """模型返回非法 JSON，报告修复也失败时，Agent 应使用 fallback。"""

    invalid_json = """
    {
        "summary": "Pod is restarting",
        "probable_causes":
    """

    # 模拟 LLM 返回截断 JSON
    prepare_test(
        monkeypatch,
        [
            make_response(content=invalid_json),
        ],
    )

    # 模拟结构化报告修复失败
    def mock_generate_structured_report(**kwargs):
        raise RuntimeError("simulated formatter failure")

    monkeypatch.setattr(
        agent_module,
        "generate_structured_report",
        mock_generate_structured_report,
    )

    response = agent_module.run_llm_agent(make_request())

    # 1. Agent 整体流程不应崩溃
    assert response.status == "completed"

    # 2. 应使用 fallback summary
    assert response.summary == invalid_json.strip()

    # 3. 无法解析的 probable_causes 应为空
    assert response.probable_causes == []

    # 4. 应提供 fallback recommendation
    assert response.recommendations == [
        "请结合工具证据人工复核诊断结果。"
    ]

    # 5. Preflight 已经采集的证据应该保留
    assert len(response.evidence) > 0



def test_agent_propagates_llm_timeout(monkeypatch):
    """LLM 请求超时时，Agent 应记录日志并重新抛出异常。"""

    import openai

    class TimeoutCompletions:
        def create(self, **kwargs):
            raise openai.APITimeoutError(
                request=None
            )

    class TimeoutClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=TimeoutCompletions()
            )

    monkeypatch.setattr(
        openai,
        "OpenAI",
        TimeoutClient,
    )

    monkeypatch.setattr(
    agent_module,
    "llm_api_key",
    lambda: "test-api-key",
)

    with pytest.raises(openai.APITimeoutError):
        agent_module.run_llm_agent(make_request())



def test_agent_preserves_conflicting_evidence(monkeypatch):
    """存在不同故障线索时，Agent 应保留全部证据并谨慎诊断。"""

    pod_name = "payment-api-7d9c7d"

    # 1. 模拟 Pod 状态：上一次退出原因是 OOMKilled
    pod_status = {
        "cluster": "prod-cluster",
        "found": True,
        "namespace": "default",
        "pod_name": pod_name,
        "phase": "Running",
        "last_termination_reason": "OOMKilled",
        "restart_count": 8,
    }

    # 2. 模拟日志：发现数据库认证失败
    pod_logs = {
        "cluster": "prod-cluster",
        "namespace": "default",
        "pod_name": pod_name,
        "found": True,
        "lines": [
            "2026-11-11 10:00:01 ERROR "
            "FATAL: password authentication failed for user app_user"
        ],
    }

    # 3. 模拟监控指标：当前内存使用率只有 38.1%
    metrics = {
        "cluster": "prod-cluster",
        "namespace": "default",
        "pod_name": pod_name,
        "found": True,
        "cpu_percent": 12.4,
        "memory_percent": 38.1,
        "http_5xx_percent": 7.8,
    }

    # 4. 替换工具执行函数，不访问真实 Kubernetes 或监控系统
    def fake_execute_tool(name, arguments):
        if name == "get_pod_status":
            return pod_status

        if name == "get_pod_logs":
            return pod_logs

        if name == "query_metrics":
            return metrics

        raise AssertionError(f"测试中出现意外工具调用: {name}")

    monkeypatch.setattr(
        agent_module,
        "execute_tool",
        fake_execute_tool,
    )

    # 5. 模拟 LLM 查询日志
    tool_response = make_response(
        content="",
        tool_calls=[
            FakeToolCall(
                "get_pod_logs",
                {
                    "cluster": "prod-cluster",
                    "namespace": "default",
                    "pod_name": pod_name,
                    "tail_lines": 50,
                },
                "call_logs_001",
            )
        ],
    )

    # 6. 模拟 LLM 最终报告
    final_response = make_response(
        content=json.dumps(
            {
                "summary": (
                    "payment-api 存在重启记录。Pod 状态显示 OOMKilled，"
                    "日志同时显示数据库认证失败；当前内存指标不足以"
                    "判断 OOM 发生时的内存情况，暂不能确定唯一根因。"
                ),
                "probable_causes": [
                    "容器可能发生过内存超限，需要核对重启时间附近的历史指标。",
                    "数据库认证失败可能导致应用启动或运行异常，需要进一步核对凭据配置。",
                ],
                "recommendations": [
                    "查询 Pod 最近一次重启时间附近的历史内存指标，并核对容器 memory limit。",
                    "检查数据库认证失败日志的时间范围，并核对应用引用的 Secret 配置是否与数据库凭据一致。",
                ],
            },
            ensure_ascii=False,
        )
    )

    completions = prepare_test(
        monkeypatch,
        [tool_response, final_response],
    )

    # 7. 执行 Agent
    request = DiagnoseRequest(
        question="检查 payment-api 的异常重启原因",
        cluster="prod-cluster",
        namespace="default",
        pod_name=pod_name,
        mode="llm",
        max_steps=3,
    )

    result = agent_module.run_llm_agent(request)

    # 8. Agent 应正常完成
    assert result.status == "completed"

    # 9. 三种工具证据都应该保留
    evidence_by_source = {
        item.source: item for item in result.evidence
    }

    assert "get_pod_status" in evidence_by_source
    assert "query_metrics" in evidence_by_source
    assert "get_pod_logs" in evidence_by_source

    # 10. 检查证据中的关键内容没有丢失
    assert "OOMKilled" in evidence_by_source["get_pod_status"].details

    assert "38.1" in evidence_by_source["query_metrics"].details

    assert (
        "password authentication failed"
        in evidence_by_source["get_pod_logs"].details
    )

    # 11. 检查最终报告保留不确定性
    assert "暂不能确定唯一根因" in result.summary

    assert len(result.probable_causes) >= 2
    assert len(result.recommendations) >= 2

    # 12. Preflight 两次工具 + LLM 一次工具
    assert len(result.tool_calls) == 3

    # 13. 两次 LLM 请求：一次查询日志，一次生成最终报告
    assert len(completions.requests) == 2
