from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class DiagnoseRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000, description="故障现象或排查目标")
    cluster: str = Field(default="prod-cluster", min_length=1, max_length=128)
    namespace: str = Field(default="default", min_length=1, max_length=128)
    pod_name: str | None = Field(default="payment-api-7d9c7d", max_length=253)
    mode: Literal["demo", "llm"] = "demo"
    max_steps: int = Field(default=6, ge=1, le=10)


class EvidenceItem(BaseModel):
    source: str
    title: str
    details: str


class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict[str, Any]
    success: bool
    result_preview: str
    duration_ms: float = Field(default=0.0, ge=0)


class AgentMetrics(BaseModel):
    total_elapsed_ms: float = 0.0

    # 模型请求
    llm_call_count: int = 0
    llm_latency_ms_total: float = 0.0
    llm_latency_ms_avg: float = 0.0

    # Token 使用量
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_usage_available: bool = False

    # 工具执行
    tool_call_count: int = 0
    tool_latency_ms_total: float = 0.0
    tool_failure_count: int = 0


class DiagnosisResponse(BaseModel):
    mode: Literal["demo", "llm"]
    question: str
    summary: str
    probable_causes: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    safety_note: str = "此 Demo 仅执行只读诊断；任何变更操作都应经过权限校验和人工审批。"
    status: Literal[
        "completed",
        "max_steps_reached",
        "no_final_answer",
    ] = "completed"
    metrics: AgentMetrics | None = None