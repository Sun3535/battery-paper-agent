"""search_client 응답 파싱 + credit_guard 단위 테스트 — 실 API 호출 없음(urlopen 모킹)."""

import io
import json
from unittest.mock import patch

from rag import config, credit_guard, search_client
import pytest


@pytest.fixture(autouse=True)
def _project_id(monkeypatch):
    # 배포본에는 개인 프로젝트 ID 기본값이 없다(.env 에서 읽음) — 시험은 가짜 ID 로 돈다
    monkeypatch.setattr(config, "GCP_PROJECT_ID", "test-project")


SAMPLE_RESPONSE = {
    "summary": {"summaryText": "실리콘 음극재의 부피 팽창을 억제하려면 [1] 나노구조화가 효과적이다."},
    "results": [
        {
            "document": {
                "derivedStructData": {
                    "title": "Silicon Anode Volume Expansion",
                    "link": "gs://test-bucket/papers/arxiv_2606.21467.pdf",
                    "snippets": [{"snippet": "nano-structuring mitigates volume expansion..."}],
                }
            }
        }
    ],
}


@patch.object(search_client, "_access_token", return_value="fake-token")
@patch("rag.search_client.urllib.request.urlopen")
def test_ask_parses_summary_and_citations(mock_urlopen, _tok, tmp_path, monkeypatch):
    monkeypatch.setenv("PAID_APIS_ENABLED", "true")  # 하드락 우회 (모킹이라 실호출 없음)
    monkeypatch.setattr(credit_guard, "STATE_PATH", tmp_path / "state.json")
    mock_urlopen.return_value.__enter__.return_value = io.BytesIO(
        json.dumps(SAMPLE_RESPONSE).encode("utf-8")
    )
    res = search_client.ask("실리콘 음극재 부피 팽창 억제 방법은?")
    assert "나노구조화" in res["summary"]
    assert len(res["citations"]) == 1
    c = res["citations"][0]
    assert c["title"] == "Silicon Anode Volume Expansion"
    assert c["gcs_uri"].endswith("arxiv_2606.21467.pdf")
    assert "volume expansion" in c["snippet"]


def test_credit_guard_accumulates(tmp_path, monkeypatch):
    monkeypatch.setattr(credit_guard, "STATE_PATH", tmp_path / "state.json")
    assert credit_guard.estimated_balance_krw() == config.INITIAL_CREDIT_KRW
    credit_guard.record_usage(0.01)  # $0.01
    bal = credit_guard.estimated_balance_krw()
    assert bal < config.INITIAL_CREDIT_KRW
    assert round(config.INITIAL_CREDIT_KRW - bal, 1) == round(0.01 * config.USD_TO_KRW, 1)


def test_ask_blocked_by_hard_lock(monkeypatch):
    """하드락(기본 false)이면 API를 부르지 않고 잠김 안내를 반환해야 한다."""
    monkeypatch.delenv("PAID_APIS_ENABLED", raising=False)
    r = search_client.ask("질문")
    assert "하드락" in r["summary"]
    assert r["citations"] == []


@patch.object(search_client, "_access_token", return_value="fake-token")
@patch("rag.search_client.urllib.request.urlopen")
def test_ask_handles_empty_summary(mock_urlopen, _tok, tmp_path, monkeypatch):
    monkeypatch.setenv("PAID_APIS_ENABLED", "true")  # 하드락 우회 (모킹이라 실호출 없음)
    monkeypatch.setattr(credit_guard, "STATE_PATH", tmp_path / "state.json")
    mock_urlopen.return_value.__enter__.return_value = io.BytesIO(json.dumps({}).encode("utf-8"))
    res = search_client.ask("질문")
    assert res["summary"] == ""
    assert res["citations"] == []
