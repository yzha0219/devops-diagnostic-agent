import json
from types import SimpleNamespace

from app.agent import parse_final_report
from app.utils import generate_structured_report, is_valid_final_report


def test_parse_valid_report():
    """合法 JSON 应被正确解析。"""
    raw = json.dumps({
        "summary": "Pod 因数据库密码认证失败而反复重启。",
        "probable_causes": [
            "应用使用了过期的数据库凭据。",
            "Kubernetes Secret 引用配置错误。",
        ],
        "recommendations": [
            "核对 Secret 名称和 key。",
            "检查近期凭据轮换记录。",
        ],
    }, ensure_ascii=False)

    report = parse_final_report(raw)

    assert report["summary"] == "Pod 因数据库密码认证失败而反复重启。"
    assert len(report["probable_causes"]) == 2
    assert len(report["recommendations"]) == 2


def test_parse_invalid_json_uses_fallback():
    """非法 JSON 应触发后备逻辑，而不是抛出异常。"""
    report = parse_final_report(
        "模型暂时无法判断故障原因。"
    )

    assert report["summary"] == "模型暂时无法判断故障原因。"
    assert report["probable_causes"] == []
    assert len(report["recommendations"]) > 0


def test_parse_report_with_wrong_field_types():
    """字段类型不符合预期时，应使用安全的默认值。"""
    raw = json.dumps({
        "summary": "Pod 启动失败",
        "probable_causes": "数据库认证失败",
        "recommendations": None,
    }, ensure_ascii=False)

    report = parse_final_report(raw)

    assert report["summary"] == "Pod 启动失败"
    assert report["probable_causes"] == []
    assert report["recommendations"] == []


def test_parse_report_rejects_unknown_suffix():
    raw = json.dumps({
        "summary": "Pod 启动失败",
        "probable_causes": [],
        "recommendations": [
            "检查日志",
            "核对配置",
        ],
    }, ensure_ascii=False)

    raw += " unexpected text"

    report = parse_final_report(raw)

    assert report["summary"] == raw
    assert report["probable_causes"] == []
    assert len(report["recommendations"]) == 1


def test_generate_structured_report_uses_json_mode():
    """最终报告请求必须启用 JSON Mode。"""

    class FakeMessage:
        content = '{"summary":"Pod OOMKilled","probable_causes":[],"recommendations":["检查内存限制","检查缓存"]}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["response_format"] == {
                "type": "json_object"
            }
            assert "messages" in kwargs

            return FakeResponse()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FakeCompletions()
        )
    )

    response = generate_structured_report(
        client=fake_client,
        model="mimo-v2.6-flash",
        question="inventory-api 为什么重启？",
        evidence=[],
        draft_text="容器发生 OOMKilled。",
    )

    report = json.loads(response.choices[0].message.content)

    assert report["summary"] == "Pod OOMKilled"
    assert len(report["recommendations"]) == 2


def test_valid_report_skips_formatter():
    report = json.dumps({
        "summary": "Pod 因数据库认证失败而重启。",
        "probable_causes": [
            "数据库凭据不匹配"
        ],
        "recommendations": [
            "检查 Secret 名称",
            "检查数据库凭据轮换记录",
        ],
    }, ensure_ascii=False)

    assert is_valid_final_report(report) is True


def test_invalid_report_requires_formatter():
    report = json.dumps({
        "summary": "Pod 因数据库认证失败而重启。",
        "probable_causes": [
            "数据库凭据不匹配"
        ],
        "recommendations": [
            "检查 Secret 名称"
        ],
    }, ensure_ascii=False)

    assert is_valid_final_report(report) is False