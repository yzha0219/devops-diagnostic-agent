"""Read-only diagnostic tools backed by safe, deterministic fixture data.

Replace these implementations with authenticated Kubernetes / Prometheus / logging APIs
only after the demo is understood. Do not point write-capable tools at production by default.
"""
from __future__ import annotations

from typing import Any
import logging

logger = logging.getLogger(__name__)


POD_FIXTURES: dict[str, dict[str, Any]] = {
    "payment-api-7d9c7d": {
        "pod_name": "payment-api-7d9c7d",
        "namespace": "default",
        "phase": "Running",
        "container_status": "CrashLoopBackOff",
        "ready": False,
        "restart_count": 8,
        "last_exit_code": 1,
        "node": "ip-10-0-12-31",
        "events": ["Back-off restarting failed container payment-api"],
    },
    "order-api-54df8b": {
        "pod_name": "order-api-54df8b",
        "namespace": "default",
        "phase": "Running",
        "container_status": "Running",
        "ready": True,
        "restart_count": 0,
        "last_exit_code": 0,
        "node": "ip-10-0-12-42",
        "events": [],
    },
    "inventory-api-6f8c9d": {
        "pod_name": "inventory-api-6f8c9d",
        "namespace": "default",
        "phase": "Running",
        "container_status": "CrashLoopBackOff",
        "ready": False,
        "restart_count": 5,
        "last_exit_code": 137,
        "last_termination_reason": "OOMKilled",
        "node": "ip-10-0-12-55",
        "events": [
            "Container inventory-api was OOMKilled",
            "Back-off restarting failed container inventory-api"
        ],
    },
}

LOG_FIXTURES: dict[str, list[str]] = {
    "payment-api-7d9c7d": [
        "2026-10-18T10:02:11Z INFO starting payment-api",
        "2026-10-18T10:02:12Z INFO loading database configuration",
        '2026-10-18T10:02:13Z ERROR FATAL: password authentication failed for user "app_user"',
        "2026-10-18T10:02:13Z ERROR application startup failed",
    ],
    "order-api-54df8b": [
        "2026-10-18T10:02:11Z INFO starting order-api",
        "2026-10-18T10:02:12Z INFO HTTP server listening on port 8080",
    ],
    "inventory-api-6f8c9d": [
        "2026-10-18T11:02:11Z INFO starting inventory-api",
        "2026-10-18T11:02:12Z INFO loading inventory cache",
        "2026-10-18T11:02:13Z INFO processing product batch",
        "2026-10-18T11:02:14Z WARN memory consumption approaching container limit",
        "2026-10-18T11:02:15Z WARN large cache allocation detected",
    ],
}

METRIC_FIXTURES: dict[str, dict[str, Any]] = {
    "payment-api-7d9c7d": {
        "cpu_usage_percent": 12.4,
        "memory_usage_percent": 38.1,
        "http_5xx_rate_percent": 7.8,
        "request_rate_per_second": 21.3,
        "window": "last 15 minutes",
    },
    "order-api-54df8b": {
        "cpu_usage_percent": 22.1,
        "memory_usage_percent": 44.6,
        "http_5xx_rate_percent": 0.0,
        "request_rate_per_second": 18.2,
        "window": "last 15 minutes",
    },
        "inventory-api-6f8c9d": {
        "cpu_usage_percent": 42.3,
        "memory_usage_percent": 97.8,
        "http_5xx_rate_percent": 12.6,
        "request_rate_per_second": 85.0,
        "window": "last 15 minutes",
    },
}

RUNBOOKS = [
    {
        "title": "CrashLoopBackOff 基础排查",
        "keywords": ["crashloopbackoff", "restart", "启动失败", "重启", "exit code"],
        "content": (
            "先检查 Pod events、容器退出码和上一轮容器日志。区分应用启动异常、"
            "配置错误、依赖不可用和资源不足。先收集证据，不要直接删除 Pod 或修改生产配置。"
        ),
    },
    {
        "title": "数据库认证失败排查",
        "keywords": ["password authentication", "database", "数据库", "password", "app_user", "认证失败"],
        "content": (
            "核对应用引用的 Secret 名称、目标数据库用户名以及凭据轮换记录；"
            "不要在日志、聊天记录或工单中输出明文密码。先确认是否发生过 Secret 更新或数据库账号轮换，"
            "再由授权人员按变更流程处理。"
        ),
    },
    {
        "title": "高 CPU / 内存排查",
        "keywords": ["cpu", "memory", "内存", "资源", "oom", "性能"],
        "content": (
            "排查 CPU 或内存资源问题时，应结合 Prometheus 指标、"
            "容器退出原因和 Kubernetes Events。"
            "如果容器出现 OOMKilled，应检查内存使用峰值、"
            "容器 memory limit、内存申请量、近期流量变化和应用内存泄漏。"
            "不要仅凭退出码 137 判断为 OOM。"
            "调整资源配额或发布修复必须经过影响评估和变更审批。"
        ),
    },
]


def get_pod_status(cluster: str, namespace: str = "default", pod_name: str | None = None) -> dict[str, Any]:
    """Return pod status. Demo data only; cluster is echoed for context."""
    if pod_name:
        fixture = POD_FIXTURES.get(pod_name)
        if not fixture or fixture["namespace"] != namespace:
            return {"cluster": cluster, "namespace": namespace, "pod_name": pod_name, "found": False}
        return {"cluster": cluster, "found": True, **fixture}
    pods = [v for v in POD_FIXTURES.values() if v["namespace"] == namespace]
    return {"cluster": cluster, "namespace": namespace, "found": bool(pods), "pods": pods}


def get_pod_logs(cluster: str, namespace: str, pod_name: str, tail_lines: int = 50) -> dict[str, Any]:
    """Return recent fixture logs, capped to avoid unbounded output."""
    lines = LOG_FIXTURES.get(pod_name)
    pod = POD_FIXTURES.get(pod_name)
    if not lines or not pod or pod["namespace"] != namespace:
        return {"cluster": cluster, "namespace": namespace, "pod_name": pod_name, "found": False, "lines": []}
    safe_tail = max(1, min(int(tail_lines), 100))
    return {"cluster": cluster, "namespace": namespace, "pod_name": pod_name, "found": True, "lines": lines[-safe_tail:]}


def query_metrics(cluster: str, namespace: str, pod_name: str) -> dict[str, Any]:
    """Return fixture metrics for a pod."""
    metrics = METRIC_FIXTURES.get(pod_name)
    pod = POD_FIXTURES.get(pod_name)
    if not metrics or not pod or pod["namespace"] != namespace:
        return {"cluster": cluster, "namespace": namespace, "pod_name": pod_name, "found": False}
    return {"cluster": cluster, "namespace": namespace, "pod_name": pod_name, "found": True, **metrics}


def search_runbook(query: str) -> dict[str, Any]:
    """A tiny keyword-based runbook search for the MVP (not embedding-based RAG yet)."""
    lowered = query.lower()
    ranked: list[tuple[int, dict[str, Any]]] = []
    for runbook in RUNBOOKS:
        score = sum(1 for keyword in runbook["keywords"] if keyword.lower() in lowered)
        if score:
            ranked.append((score, runbook))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return {
        "query": query,
        "results": [
            {"title": item["title"], "content": item["content"], "score": score}
            for score, item in ranked[:3]
        ],
    }


TOOL_FUNCTIONS = {
    "get_pod_status": get_pod_status,
    "get_pod_logs": get_pod_logs,
    "query_metrics": query_metrics,
    "search_runbook": search_runbook,
}

# OpenAI-compatible Chat Completions tool schema. These are all read-only tools.
LLM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_pod_status",
            "description": (
                "查询指定 Kubernetes Pod 的状态、重启次数、"
                "退出码、最近一次容器终止原因和 Kubernetes Events。只读。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cluster": {"type": "string", "description": "集群名称"},
                    "namespace": {"type": "string", "description": "Kubernetes namespace"},
                    "pod_name": {"type": "string", "description": "Pod 名称"},
                },
                "required": ["cluster", "namespace", "pod_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pod_logs",
            "description": "查询指定 Pod 最近的日志。只读，不返回或请求 Secret 明文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cluster": {"type": "string"},
                    "namespace": {"type": "string"},
                    "pod_name": {"type": "string"},
                    "tail_lines": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["cluster", "namespace", "pod_name", "tail_lines"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_metrics",
            "description": (
                "查询指定 Pod 的 CPU、内存使用率、HTTP 5xx 比例"
                "和请求速率，用于分析资源瓶颈。只读。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cluster": {"type": "string"},
                    "namespace": {"type": "string"},
                    "pod_name": {"type": "string"},
                },
                "required": ["cluster", "namespace", "pod_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_runbook",
            "description": "按故障现象搜索本地运维手册；传入错误信息或故障关键词。只读。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute only allow-listed tools with basic argument validation."""
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        raise ValueError(f"Tool not allow-listed: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object")
    # Defensive cap even if a provider returns unexpected arguments.
    if name == "get_pod_logs":
        arguments = {**arguments, "tail_lines": min(max(int(arguments.get("tail_lines", 50)), 1), 100)}
    result = function(**arguments)
    if not isinstance(result, dict):
        raise TypeError("Tool must return a dictionary")
    return result