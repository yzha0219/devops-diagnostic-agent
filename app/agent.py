from __future__ import annotations

import json
import logging
import time
from typing import Any


from app.config import llm_api_key, llm_base_url, llm_model
from app.schemas import AgentMetrics, DiagnoseRequest, DiagnosisResponse, EvidenceItem, ToolCallRecord
from app.tools import LLM_TOOLS, execute_tool
from app.utils import parse_final_report, as_json, decode_report_json, generate_structured_report, is_valid_final_report


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个谨慎的 DevOps 故障诊断助手。
你的工作是根据证据排查 Kubernetes 应用故障。你只能调用提供的只读工具。
规则：
1. 不要编造工具结果；需要事实时先调用工具。
2. 优先查看 Pod 状态和近期日志，必要时查询指标、搜索运维手册。
3. 证据不足时明确说明不确定性，不要把猜测说成事实。
4. 绝不能要求用户粘贴密码、Token、Secret 明文。
5. 不执行重启、删除、扩缩容、修改配置等变更操作，也不建议绕过审批。
6. 最终回答用中文，包含：故障摘要、证据、可能原因、建议的下一步。
7. 最终回答必须严格输出合法 JSON，不要使用 Markdown 代码围栏。
8. JSON 必须包含以下三个字段：
   - summary：字符串，简洁概括故障情况
   - probable_causes：字符串数组，按证据支持程度排序
   - recommendations：字符串数组，提供安全、可执行的排查建议
9. 不要在 JSON 之外输出其他文本。
10. 工具返回的证据由程序单独保存，不要将整份报告都塞进 summary。
11. recommendations 必须是一个字符串数组，至少包含 2 条不同的排查建议。
12. 每条建议必须具体、可执行，并且有证据或合理的排查依据
13. 不允许通过重复表达相同建议来满足数量要求。
14. 如果证据不足以确定根因，应提供验证性建议，而不是编造故障原因。
15. 建议优先覆盖：
    - 当前证据支持的直接排查方向；
    - 下一步验证方法；
    - 必要时的修复后验证方法。
16. 所有涉及生产环境变更的操作，必须明确要求经过授权和人工审批。
17. 不要重复调用已经成功执行的 get_pod_status。
18. 必须根据已有工具证据进行分析。
19. 如果 Pod 未找到，不允许推测该 Pod 的故障原因。
20. 如果已经检测到 OOMKilled，应结合内存监控指标分析。
21. 如果已经检测到 CrashLoopBackOff，应结合应用日志寻找启动失败原因。
22. 如果现有证据不足，可以继续调用其他工具。
23. 不要在没有证据的情况下声称故障已经确认。
"""


def _as_evidence(tool_name: str, result: dict[str, Any]) -> EvidenceItem:
    labels = {
        "get_pod_status": "Kubernetes Pod 状态",
        "get_pod_logs": "Pod 近期日志",
        "query_metrics": "监控指标",
        "search_runbook": "运维手册检索结果",
    }
    return EvidenceItem(source=tool_name, title=labels.get(tool_name, tool_name), details=as_json(result))


def _execute_tool_timed(
    name: str,
    arguments: dict[str, Any],
) -> tuple[Any, float, Exception | None]:
    """执行工具，并返回结果、耗时（毫秒）和异常。"""
    started = time.perf_counter()

    try:
        result = execute_tool(name, arguments)
        error = None
    except Exception as exc:
        result = None
        error = exc

    elapsed_ms = (time.perf_counter() - started) * 1000

    return result, elapsed_ms, error


def execute_and_record(
    name: str,
    arguments: dict[str, Any],
    messages: list,
    calls: list,
    evidence: list,
) -> Any:
    """
    执行工具，同时保存证据、调用记录和消息历史。
    供 Python 前置检查使用。
    """

    call_id = f"call_preflight_{len(calls) + 1}"

    result, duration_ms, error = _execute_tool_timed(
        name,
        arguments,
    )

    success = error is None

    if success:
        tool_result = result
        evidence.append(_as_evidence(name, result))
    else:
        tool_result = {
            "tool": name,
            "error": str(error),
        }

    duration_ms = round(duration_ms, 2)

    calls.append(
        ToolCallRecord(
            tool=name,
            arguments=arguments,
            success=success,
            result_preview=as_json(tool_result)[:400],
            duration_ms=duration_ms,
        )
    )

    # 把 Python 执行的工具调用作为有效的对话历史交给 LLM
    messages.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        arguments,
                        ensure_ascii=False,
                    ),
                },
            }
        ],
    })

    messages.append({
        "role": "tool",
        "tool_call_id": call_id,
        "content": as_json(tool_result),
    })

    logger.info(
        "agent_preflight_tool name=%s success=%s latency_ms=%.2f",
        name,
        success,
        duration_ms,
    )

    return result if success else None


def _run_demo_tool(
    name: str,
    arguments: dict[str, Any],
) -> tuple[Any, float]:
    """执行 Demo 工具，记录耗时和日志。"""
    result, elapsed_ms, error = _execute_tool_timed(
        name, arguments
    )

    if error is not None:
        logger.warning(
            "agent_tool mode=demo name=%s success=false "
            "error_type=%s latency_ms=%.2f",
            name,
            type(error).__name__,
            elapsed_ms,
        )
        raise error

    logger.info(
        "agent_tool mode=demo name=%s success=true latency_ms=%.2f",
        name,
        elapsed_ms,
    )

    return result, round(elapsed_ms, 2)


def run_demo_agent(request: DiagnoseRequest) -> DiagnosisResponse:
    """Deterministic, offline demo so the project runs without credentials."""
    calls: list[ToolCallRecord] = []
    evidence: list[EvidenceItem] = []
    run_started = time.perf_counter()

    target_pod = request.pod_name or "payment-api-7d9c7d"
    status, status_ms = _run_demo_tool("get_pod_status", {
        "cluster": request.cluster,
        "namespace": request.namespace,
        "pod_name": target_pod,
    })
    calls.append(ToolCallRecord(tool="get_pod_status", arguments={"cluster": request.cluster, "namespace": request.namespace, "pod_name": target_pod}, success=True, result_preview=as_json(status)[:400], duration_ms=status_ms))
    evidence.append(_as_evidence("get_pod_status", status))

    logs, log_ms = _run_demo_tool("get_pod_logs", {
        "cluster": request.cluster,
        "namespace": request.namespace,
        "pod_name": target_pod,
        "tail_lines": 50,
    })
    calls.append(ToolCallRecord(tool="get_pod_logs", arguments={"cluster": request.cluster, "namespace": request.namespace, "pod_name": target_pod, "tail_lines": 50}, success=True, result_preview=as_json(logs)[:400], duration_ms=log_ms))
    evidence.append(_as_evidence("get_pod_logs", logs))

    metrics, metrics_ms = _run_demo_tool("query_metrics", {
        "cluster": request.cluster,
        "namespace": request.namespace,
        "pod_name": target_pod,
    })
    calls.append(ToolCallRecord(tool="query_metrics", arguments={"cluster": request.cluster, "namespace": request.namespace, "pod_name": target_pod}, success=True, result_preview=as_json(metrics)[:400], duration_ms=metrics_ms))
    evidence.append(_as_evidence("query_metrics", metrics))

    runbook_query = f"{request.question} {as_json(status)} {as_json(logs)}"
    runbook, runbook_ms = _run_demo_tool("search_runbook", {"query": runbook_query})
    calls.append(ToolCallRecord(tool="search_runbook", arguments={"query": runbook_query[:300]}, success=True, result_preview=as_json(runbook)[:400], duration_ms=runbook_ms))
    evidence.append(_as_evidence("search_runbook", runbook))

    if not status.get("found"):
        summary = f"没有在 Demo 数据中找到 Pod `{target_pod}`（namespace: `{request.namespace}`）。当前工具使用的是模拟数据，不代表真实集群状态。"
        causes = ["目标 Pod 不在当前 Demo fixture 中，或 namespace 不匹配。"]
        recommendations = ["确认集群、namespace 和 Pod 名称。", "接入真实 Kubernetes API 后，再对真实资源执行只读查询。"]
    else:
        container_status = status.get("container_status", "unknown")
        log_text = "\n".join(logs.get("lines", []))
        if "password authentication failed" in log_text.lower():
            summary = (
                f"Pod `{target_pod}` 处于 `{container_status}`，已重启 {status.get('restart_count', '未知')} 次。"
                "日志显示数据库用户 `app_user` 认证失败；当前证据更支持数据库凭据或凭据配置不一致，"
                "而不是 CPU / 内存耗尽。以上来自模拟数据。"
            )
            causes = [
                "应用使用的数据库用户名或密码与数据库当前配置不一致。",
                "凭据轮换后，应用引用的 Kubernetes Secret 可能未同步更新或未被应用正确加载。",
            ]
            recommendations = [
                "由有权限的人员核对应用引用的 Secret 名称、数据库用户名及近期凭据轮换记录；不要输出明文密码。",
                "确认应用实际读取到的配置版本，并查看数据库侧认证日志。",
                "按变更审批流程修复配置后，在测试环境验证，再观察 Pod 重启次数和 HTTP 5xx 指标。",
            ]
        elif container_status == "CrashLoopBackOff":
            summary = f"Pod `{target_pod}` 处于 `{container_status}`。现有模拟证据不足以确定唯一根因，需要进一步检查容器日志、退出码和依赖服务。"
            causes = ["应用启动失败；需要结合日志和退出码继续确认。"]
            recommendations = ["检查最近一次容器日志和 Pod events。", "确认依赖服务可用性、配置与资源限制。"]
        else:
            summary = f"Pod `{target_pod}` 的模拟状态为 `{container_status}`，ready={status.get('ready')}。请结合监控窗口和用户报告确认是否存在实际故障。"
            causes = ["当前 Demo 数据未显示 CrashLoopBackOff；需要进一步明确故障时间和影响范围。"]
            recommendations = ["确认告警发生时间、受影响请求和相邻服务状态。"]

    return DiagnosisResponse(
        mode="demo",
        question=request.question,
        summary=summary,
        probable_causes=causes,
        recommendations=recommendations,
        evidence=evidence,
        tool_calls=calls,
        metrics=AgentMetrics(
            total_elapsed_ms=round(
                (time.perf_counter() - run_started) * 1000, 2
            ) ,
            tool_call_count=len(calls),
            tool_latency_ms_total=round(sum(call.duration_ms for call in calls), 2),
            tool_failure_count=sum(1 for call in calls if not call.success),
        )
    )


def run_llm_agent(request: DiagnoseRequest) -> DiagnosisResponse:
    """OpenAI-compatible Chat Completions tool-calling loop."""
    run_started = time.perf_counter()

    llm_call_count = 0
    llm_latency_ms_total = 0.0

    prompt_tokens_sum = 0
    completion_tokens_sum = 0
    total_tokens_sum = 0
    token_usage_available = False

    key = llm_api_key()
    if not key:
        raise ValueError("缺少 LLM_API_KEY。请复制 .env.example 为 .env 并配置模型 API Key，或使用 mode='demo'。")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ValueError("LLM 模式需要安装 openai 依赖：pip install openai") from exc

    client_kwargs: dict[str, Any] = {"api_key": key, "timeout": 45.0, "max_retries": 1}
    if llm_base_url():
        client_kwargs["base_url"] = llm_base_url()
    client = OpenAI(**client_kwargs)

    user_prompt = (
        f"故障问题：{request.question}\n"
        f"集群：{request.cluster}\nNamespace：{request.namespace}\n"
        f"目标 Pod：{request.pod_name or '未指定，请先查询相关 Pod'}\n"
        "请使用只读工具调查，不要猜测工具结果。"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    calls: list[ToolCallRecord] = []
    evidence: list[EvidenceItem] = []
    final_text = ""
    status = "max_steps_reached"

    # 第一步：强制查询 Pod 状态
    status_arguments = {
        "cluster": request.cluster,
        "namespace": request.namespace,
        "pod_name": request.pod_name,
    }

    pod_status = execute_and_record(
        name="get_pod_status",
        arguments=status_arguments,
        messages=messages,
        calls=calls,
        evidence=evidence,
    )

    # 第二步：根据 Pod 状态选择必要的诊断工具
    if pod_status is not None:

        if not pod_status.get("found", False):
            logger.info(
                "agent_routing reason=pod_not_found "
                "skip_additional_diagnostics=true"
            )

        elif pod_status.get("last_termination_reason") == "OOMKilled":

            # OOMKilled：必须检查内存监控指标
            logger.info(
                "agent_routing reason=OOMKilled next_tool=query_metrics"
            )

            execute_and_record(
                name="query_metrics",
                arguments={
                    "cluster": request.cluster,
                    "namespace": request.namespace,
                    "pod_name": request.pod_name,
                },
                messages=messages,
                calls=calls,
                evidence=evidence,
            )

        elif pod_status.get("container_status") == "CrashLoopBackOff":

            # 其他 CrashLoopBackOff：必须查询应用日志
            logger.info(
                "agent_routing reason=CrashLoopBackOff next_tool=get_pod_logs"
            )

            execute_and_record(
                name="get_pod_logs",
                arguments={
                    "cluster": request.cluster,
                    "namespace": request.namespace,
                    "pod_name": request.pod_name,
                    "tail_lines": 100,
                },
                messages=messages,
                calls=calls,
                evidence=evidence,
            )

    for step_index in range(request.max_steps):
        llm_started = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=llm_model(),
                messages=messages,
                tools=LLM_TOOLS,
                tool_choice="auto",
                max_completion_tokens=2048,
                response_format={
                    "type": "json_object",
                }
            )
        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - llm_started
            ) * 1000

            logger.warning(
                "agent_llm_call_failed step=%d error_type=%s "
                "latency_ms=%.2f",
                step_index + 1,
                type(exc).__name__,
                elapsed_ms,
            )
            raise
        llm_elapsed_ms = (
            time.perf_counter() - llm_started
        ) * 1000

        llm_call_count += 1
        llm_latency_ms_total += llm_elapsed_ms

        choice = response.choices[0]
        message = choice.message
        usage = getattr(response, "usage", None)

        prompt_value = getattr(usage, "prompt_tokens", None)
        completion_value = getattr(usage, "completion_tokens", None)
        total_value = getattr(usage, "total_tokens", None)

        if any(
            value is not None
            for value in (prompt_value, completion_value, total_value)
        ):
            token_usage_available = True

            prompt_count = int(prompt_value or 0)
            completion_count = int(completion_value or 0)

            if total_value is None:
                total_count = prompt_count + completion_count
            else:
                total_count = int(total_value)

            prompt_tokens_sum += prompt_count
            completion_tokens_sum += completion_count
            total_tokens_sum += total_count

        logger.info(
            "agent_llm_call step=%d latency_ms=%.2f "
            "finish_reason=%s tool_calls=%d usage_reported=%s "
            "prompt_tokens=%d completion_tokens=%d total_tokens=%d",
            step_index + 1,
            llm_elapsed_ms,
            getattr(choice, "finish_reason", "unknown"),
            len(message.tool_calls or []),
            usage is not None and token_usage_available,
            int(prompt_value or 0),
            int(completion_value or 0),
            int(total_value or 0)
            if total_value is not None
            else int(prompt_value or 0) + int(completion_value or 0),
        )

        message = response.choices[0].message
        assistant_message: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            assistant_message["tool_calls"] = [tc.model_dump(exclude_none=True) for tc in message.tool_calls]
        messages.append(assistant_message)

        if not message.tool_calls:
            if message.content and message.content.strip():
                final_text = message.content
                status = "completed"
            else:
                final_text = message.content or "模型没有返回文本内容。"
                status = "no_final_answer"
            break

        for tool_call in message.tool_calls:
            name = tool_call.function.name
            arguments: dict[str, Any] = {}

            tool_started = time.perf_counter()
            tool_duration_ms: float | None = None
            tool_error_type: str | None = None

            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object")
                # Fill in trusted request context when the model omits shared scope.
                if name in {"get_pod_status", "get_pod_logs", "query_metrics"}:
                    arguments.setdefault("cluster", request.cluster)
                    arguments.setdefault("namespace", request.namespace)
                if name in {"get_pod_logs", "query_metrics"}:
                    arguments.setdefault("pod_name", request.pod_name)
                result, tool_duration_ms, tool_error = (
                    _execute_tool_timed(name, arguments)
                )
                if tool_error is not None:
                    result = {
                        "error": str(tool_error),
                        "tool": name,
                    }
                    success = False
                    tool_error_type = type(tool_error).__name__
                else:
                    success = True
                    evidence.append(_as_evidence(name, result))
            except Exception as exc:  # Surface tool errors to the model; don't crash the whole loop.
                result = {"error": str(exc), "tool": name}
                success = False
                tool_error_type = type(exc).__name__

                if tool_duration_ms is None:
                    tool_duration_ms = (
                        time.perf_counter() - tool_started
                    ) * 1000

            if tool_duration_ms is None:
                tool_duration_ms = (
                    time.perf_counter() - tool_started
                ) * 1000

            tool_duration_ms = round(tool_duration_ms, 2)

            if success:
                logger.info(
                    "agent_tool mode=llm name=%s success=true latency_ms=%.2f",
                    name,
                    tool_duration_ms,
                )
            else:
                logger.warning(
                    "agent_tool mode=llm name=%s success=false "
                    "error_type=%s latency_ms=%.2f",
                    name,
                    tool_error_type or "UnknownError",
                    tool_duration_ms,
                )
            calls.append(ToolCallRecord(
                tool=name,
                arguments=arguments,
                success=success,
                result_preview=as_json(result)[:400],
                duration_ms=tool_duration_ms,
            ))
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": as_json(result),
            })
    else:
        final_text = "达到本次诊断的最大步骤数，已停止继续调用工具。请查看已有证据并谨慎判断。"
        status = "max_steps_reached"

    # 检查模型原始 JSON 中的 recommendations
    raw_json_valid = False
    raw_rec_count = 0
    raw_rec_string_count = 0
    raw_rec_invalid_count = 0

    try:
        raw_report, trailing_suffix = decode_report_json(final_text)

        if isinstance(raw_report, dict):
            raw_json_valid = True

            raw_recommendations = raw_report.get(
                "recommendations", []
            )

            if isinstance(raw_recommendations, list):
                raw_rec_count = len(raw_recommendations)

                raw_rec_string_count = sum(
                    isinstance(item, str) and bool(item.strip())
                    for item in raw_recommendations
                )

                raw_rec_invalid_count = (
                    raw_rec_count - raw_rec_string_count
                )

    except json.JSONDecodeError as exc:
        logger.warning(
            "agent_report_json_error "
            "message=%s position=%d line=%d column=%d "
            "context=%r tail=%r",
            exc.msg,
            exc.pos,
            exc.lineno,
            exc.colno,
            final_text[
                max(0, exc.pos - 80):
                min(len(final_text), exc.pos + 120)
            ],
            final_text[-200:],
        )

    except TypeError as exc:
        logger.warning(
            "agent_report_json_type_error error=%s",
            type(exc).__name__,
        )

    logger.info(
        "agent_report_raw json_valid=%s "
        "recommendations=%d string_items=%d invalid_items=%d trailing_suffix=%r",
        raw_json_valid,
        raw_rec_count,
        raw_rec_string_count,
        raw_rec_invalid_count,
        trailing_suffix,
    )
    if not raw_json_valid:
        logger.warning(
            "agent_report_invalid_json length=%d preview=%r",
            len(final_text),
            final_text[:500],
        )

    # 只在 Agent 正常完成诊断后生成结构化报告
    report_is_valid = is_valid_final_report(
        final_text,
        min_recommendations=2,
    )

    if status == "completed" and not report_is_valid:
        logger.info(
            "agent_structured_report reason=invalid_initial_report"
        )  

        format_started = time.perf_counter()

        try:
            format_response = generate_structured_report(
                client=client,
                model=llm_model(),
                question=request.question,
                evidence=evidence,
                draft_text=final_text,
            )

            format_latency_ms = (
                time.perf_counter() - format_started
            ) * 1000

            # 这也是一次真实的 LLM 请求，必须计入性能统计
            llm_call_count += 1
            llm_latency_ms_total += format_latency_ms

            format_usage = getattr(
                format_response,
                "usage",
                None,
            )

            if format_usage is not None:
                format_prompt = int(
                    getattr(format_usage, "prompt_tokens", 0) or 0
                )
                format_completion = int(
                    getattr(format_usage, "completion_tokens", 0) or 0
                )
                format_total = getattr(
                    format_usage,
                    "total_tokens",
                    None,
                )

                prompt_tokens_sum += format_prompt
                completion_tokens_sum += format_completion

                total_tokens_sum += (
                    int(format_total)
                    if format_total is not None
                    else format_prompt + format_completion
                )

                token_usage_available = True

            formatted_text = (
                format_response.choices[0].message.content
            )

            if not formatted_text or not formatted_text.strip():
                raise ValueError("结构化报告生成结果为空")

            final_text = formatted_text

            logger.info(
                "agent_structured_report latency_ms=%.2f success=true",
                format_latency_ms,
            )

        except Exception as exc:
            logger.warning(
                "agent_structured_report success=false error_type=%s",
                type(exc).__name__,
            )
    elif status == "completed" and report_is_valid:
        logger.info(
            "agent_structured_report skipped reason=initial_report_valid"
        )

    # 原来的解析逻辑
    report = parse_final_report(final_text)

    logger.info(
        "agent_report_parsed recommendations=%d",
        len(report["recommendations"]),
    )

    recommendations = report["recommendations"] or [
        "请根据工具证据复核诊断结果；涉及生产变更时必须走授权和审批流程。"
    ]

    metrics = AgentMetrics(
        total_elapsed_ms=round(
            (time.perf_counter() - run_started) * 1000, 2
        ),
        llm_call_count=llm_call_count,
        llm_latency_ms_total=round(llm_latency_ms_total, 2),
        llm_latency_ms_avg=round(
            llm_latency_ms_total / llm_call_count, 2
        ) if llm_call_count else 0.0,
        prompt_tokens=prompt_tokens_sum,
        completion_tokens=completion_tokens_sum,
        total_tokens=total_tokens_sum,
        token_usage_available=token_usage_available,
        tool_call_count=len(calls),
        tool_latency_ms_total=round(
            sum(call.duration_ms for call in calls), 2
        ),
        tool_failure_count=sum(
            not call.success for call in calls
        ),
    )

    logger.info(
        "agent_run_completed mode=llm elapsed_ms=%.2f "
        "llm_calls=%d total_tokens=%d token_usage_available=%s "
        "tool_calls=%d tool_failures=%d",
        metrics.total_elapsed_ms,
        metrics.llm_call_count,
        metrics.total_tokens,
        metrics.token_usage_available,
        metrics.tool_call_count,
        metrics.tool_failure_count,
    )

    return DiagnosisResponse(
        mode="llm",
        question=request.question,
        summary=report["summary"],
        probable_causes=report["probable_causes"],
        recommendations=recommendations,
        evidence=evidence,
        tool_calls=calls,
        status=status,
        metrics=metrics
    )


def run_agent(request: DiagnoseRequest) -> DiagnosisResponse:
    if request.mode == "demo":
        return run_demo_agent(request)
    return run_llm_agent(request)
