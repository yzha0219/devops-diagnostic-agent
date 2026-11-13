from __future__ import annotations
import os
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.agent import run_agent
from app.schemas import DiagnoseRequest, DiagnosisResponse

log_level = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
app = FastAPI(
    title="DevOps Diagnostic Agent",
    description="面向 Kubernetes 故障排查的只读 Agent Demo。默认使用模拟数据。",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "devops-diagnostic-agent"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DevOps Diagnostic Agent</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:900px;margin:40px auto;padding:0 18px;line-height:1.55;color:#222}
textarea,input,select,button{font:inherit;padding:9px;border:1px solid #bbb;border-radius:7px}textarea{width:100%;box-sizing:border-box}label{display:block;margin:12px 0 5px}button{cursor:pointer;background:#222;color:white}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:14px;border-radius:8px}
.note{padding:12px;background:#fff6dd;border-radius:8px}
</style></head><body>
<h1>DevOps 故障诊断 Agent</h1>
<p>第一版使用模拟 Kubernetes、监控和日志数据。不会连接或修改真实集群。</p>
<div class="note">默认选择 Demo 模式即可直接运行；LLM 模式需要先配置 .env。</div>
<label for="question">故障现象</label><textarea id="question" rows="3">payment-api 为什么频繁重启？请检查状态、日志、指标并查找处理手册。</textarea>
<label for="cluster">集群名称</label><input id="cluster" value="prod-cluster">
<label for="namespace">Namespace</label><input id="namespace" value="default">
<label for="pod">Pod 名称</label><input id="pod" value="payment-api-7d9c7d">
<label for="mode">模式</label><select id="mode"><option value="demo">Demo（离线模拟数据）</option><option value="llm">LLM（需要配置 API）</option></select>
<p><button onclick="diagnose()">开始诊断</button> <a href="/docs">打开 API 文档</a></p>
<h2>诊断结果</h2><pre id="result">等待提交。</pre>
<script>
async function diagnose(){const out=document.getElementById('result');out.textContent='诊断中…';try{const r=await fetch('/diagnose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:document.getElementById('question').value,cluster:document.getElementById('cluster').value,namespace:document.getElementById('namespace').value,pod_name:document.getElementById('pod').value,mode:document.getElementById('mode').value})});const data=await r.json();out.textContent=JSON.stringify(data,null,2)}catch(e){out.textContent='请求失败：'+e}}
</script></body></html>"""


@app.post("/diagnose", response_model=DiagnosisResponse)
def diagnose(request: DiagnoseRequest) -> DiagnosisResponse:
    try:
        return run_agent(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Keep a friendly API error; production apps should log exception details privately.
        raise HTTPException(status_code=502, detail=f"诊断失败：{type(exc).__name__}: {exc}") from exc
