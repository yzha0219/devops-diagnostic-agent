# DevOps 故障诊断 Agent（MVP）

这是一个面向学习与面试展示的、可在本地运行的 DevOps 故障诊断 Agent。第一版使用**模拟数据**，不会连接或修改真实 Kubernetes 集群。

## 当前功能

- FastAPI HTTP API 与一个简单的中文网页。
- 4 个只读工具：Pod 状态、Pod 日志、监控指标、运维手册检索。
- `demo` 模式：无 API Key 也能运行，用固定演示数据走完工具调用链路。
- `llm` 模式：可选接入支持 OpenAI-compatible Chat Completions + tool calling 的模型服务。
- 工具白名单、基础参数限制、最大 Agent 步骤数。
- pytest 自动化测试。

> `search_runbook` 目前是关键词检索，只是为了让 MVP 依赖少、便于理解；它还不是基于 Embedding 的完整 RAG。下一阶段再加入真正的向量检索。

## 环境要求

- Python 3.11 或更高版本（推荐 Python 3.12）
- macOS、Linux 或 Windows

## 1. 创建虚拟环境并安装依赖

```bash
cd devops-diagnostic-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Windows PowerShell 激活方式：

```powershell
.venv\\Scripts\\Activate.ps1
```

## 2. 启动服务

```bash
uvicorn app.main:app --reload
```

打开以下地址：

- 网页：<http://127.0.0.1:8000/>
- Swagger API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

## 3. 调用诊断 API

```bash
curl -X POST http://127.0.0.1:8000/diagnose \\
  -H 'Content-Type: application/json' \\
  -d '{
    "question": "payment-api 为什么频繁重启？请检查状态、日志、指标并查找处理手册。",
    "cluster": "prod-cluster",
    "namespace": "default",
    "pod_name": "payment-api-7d9c7d",
    "mode": "demo"
  }'
```

期望观察到：

- `summary` 提示 Pod 为 `CrashLoopBackOff`，日志里出现数据库认证失败。
- `evidence` 有 4 类证据。
- `tool_calls` 记录调用了哪些工具以及参数。
- `recommendations` 给出先核对 Secret 引用、凭据轮换记录和数据库认证日志等只读排查建议。

这些是**预设的模拟数据**，不是实际集群观测结果。

## 4. 运行测试

在项目根目录执行：

```bash
pytest -q
```

## 5. 可选：连接真实模型

复制环境变量模板：

```bash
cp .env.example .env
```

将 `.env` 中的 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL` 设置为你的模型服务提供的值。应用会通过 `python-dotenv` 自动加载项目根目录的 `.env` 文件。

修改 `.env` 后重启服务即可。也可以直接通过环境变量配置：

```bash
export LLM_API_KEY='你的 API Key'
export LLM_BASE_URL='你的 OpenAI-compatible API 地址'
export LLM_MODEL='该服务支持的模型名'
uvicorn app.main:app --reload
```

然后在网页中选 `LLM` 模式，或在请求 JSON 中设置 `"mode": "llm"`。

不要把 Key 提交到 Git，也不要在真实生产环境中直接接入具有写权限的工具。

## 6. Docker 运行

```bash
docker build -t devops-diagnostic-agent .
docker run --rm -p 8000:8000 devops-diagnostic-agent
```

## 架构概览

```text
用户 / Web UI
    |
    v
FastAPI /diagnose
    |
    v
Agent Loop (demo 模式为确定性流程；llm 模式为模型 tool-calling 循环)
    |
    +--> get_pod_status   (模拟 Kubernetes)
    +--> get_pod_logs     (模拟日志)
    +--> query_metrics    (模拟 Prometheus)
    +--> search_runbook   (关键词运维手册检索)
    |
    v
汇总摘要、可能原因、建议、证据、工具调用记录
```

## 下一阶段路线

1. 用 `kubectl` 或 Kubernetes Python client 实现只读的真实 Pod 查询。
2. 对接 Prometheus HTTP API 和日志平台查询 API。
3. 用 Embedding + Chroma / FAISS 替换关键词手册检索，加入 RAG 评测。
4. 增加可观测性：每个请求的耗时、模型用量、工具失败率和 trace ID。
5. 建立 30–50 个故障案例，量化工具选择成功率、诊断正确率、延迟和成本。
6. 任何重启、删除、修改配置等写操作都应保持关闭，直到有明确的权限、审计和人工审批设计。
