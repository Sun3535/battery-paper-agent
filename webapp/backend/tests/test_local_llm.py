"""로컬 LLM 경로 검증 — 사내망 배포의 핵심 요건은 "데이터가 PC 밖으로 안 나간다".

회사가 로그인을 막는 이유가 데이터 유출 방지이므로, 외부 LLM API(Gemini)도 같은 유출에
해당한다. 이 경로는 127.0.0.1 의 로컬 LLM만 호출한다.
"""

import json
from unittest.mock import MagicMock, patch

import answer as A

RESULTS = [
    {
        "title": "company_paper",
        "passages": [{"page": 1, "text": "사내 미공개 실험 결과: capacity 250 mAh/g"}],
    }
]


def test_local_host_defaults_to_loopback(monkeypatch):
    """기본 호스트는 반드시 루프백 — 외부로 나가면 안 된다"""
    monkeypatch.delenv("LOCAL_LLM_HOST", raising=False)
    host = A._local_host()
    assert host.startswith("http://127.0.0.1") or host.startswith("http://localhost")


@patch("urllib.request.urlopen")
def test_summarize_local_calls_only_loopback(mock_open, monkeypatch):
    """요약 호출이 루프백 주소로만 나가는지 — 사내 자료 유출 방지의 핵심"""
    monkeypatch.delenv("LOCAL_LLM_HOST", raising=False)
    monkeypatch.setenv("LOCAL_LLM_MODEL", "qwen2.5:7b")

    resp = MagicMock()
    resp.read.return_value = json.dumps({"response": "capacity는 250 mAh/g이다 [1]"}).encode()
    mock_open.return_value.__enter__.return_value = resp

    text, sources = A.summarize_local("capacity는?", RESULTS)

    assert "250 mAh/g" in text
    assert sources == ["company_paper p1"]

    req = mock_open.call_args.args[0]
    url = req.full_url if hasattr(req, "full_url") else str(req)
    assert "127.0.0.1" in url or "localhost" in url, f"외부 주소로 전송됨: {url}"
    assert "googleapis.com" not in url


@patch("urllib.request.urlopen")
def test_local_summarize_sends_document_text_in_body(mock_open, monkeypatch):
    """발췌가 실제로 프롬프트에 담기는지(로컬이므로 전송 자체는 안전)"""
    monkeypatch.delenv("LOCAL_LLM_HOST", raising=False)
    resp = MagicMock()
    resp.read.return_value = json.dumps({"response": "ok"}).encode()
    mock_open.return_value.__enter__.return_value = resp

    A.summarize_local("q", RESULTS)
    body = json.loads(mock_open.call_args.args[0].data.decode())
    assert "250 mAh/g" in body["prompt"]
    assert body["stream"] is False


def test_local_llm_available_false_when_down(monkeypatch):
    """로컬 LLM이 꺼져 있으면 False — 호출부가 다른 경로로 폴백한다"""
    monkeypatch.setenv("LOCAL_LLM_HOST", "http://127.0.0.1:9")  # 닫힌 포트
    assert A.local_llm_available() is False
