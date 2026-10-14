"""자격증명 폴백 체인 + API 전용 RAG 검증.

조건1: API 키 두 칸은 완전히 교환 가능해야 한다(어디 넣어도 동작, 서로 폴백).
조건2: Vertex가 없어도 API 키만으로 챗봇 요약이 되어야 한다. 순서는 API → Vertex → 안내.
"""

from unittest.mock import MagicMock, patch

import pytest

import answer as answer_mod
import store
import users


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "fb.db")
    with store.connect() as conn:
        users.create(conn, "u", "pw")
        users.set_active(conn, "u")
    yield


def _set(kind, val):
    with store.connect() as c:
        users.set_credential(c, "u", kind, val)


def _pref(kind):
    with store.connect() as c:
        users.set_preferred(c, "u", kind)


def _chain():
    with store.connect() as c:
        return users.credential_chain(c)


# ── 조건1: 두 API 키 칸은 교환 가능 ───────────────────────────────
def test_key_in_either_slot_is_usable(db):
    """①칸에만 넣어도, ②칸에만 넣어도 키를 찾아낸다"""
    _set("free", "AIzaOnlyInSlot1_000000")
    with store.connect() as c:
        assert users.active_api_key(c).startswith("AIzaOnlyInSlot1")

    _set("free", "")
    _set("paid", "AIzaOnlyInSlot2_000000")
    with store.connect() as c:
        assert users.active_api_key(c).startswith("AIzaOnlyInSlot2")


def test_falls_back_to_other_key_slot(db):
    """고른 칸이 비어 있으면 다른 API 키 칸으로 자동 폴백"""
    _set("paid", "AIzaSlot2Key_00000000")
    _pref("free")  # 비어 있는 칸을 골랐지만
    with store.connect() as c:
        assert users.active_api_key(c).startswith("AIzaSlot2Key"), "다른 칸으로 폴백해야 함"


def test_chain_order_preferred_first(db):
    _set("free", "AIzaFree_000000000000")
    _set("paid", "AIzaPaid_000000000000")
    _set("credit", "proj-x")

    _pref("paid")
    kinds = [c["kind"] for c in _chain()]
    assert kinds[0] == "paid", "고른 것이 첫 번째"
    assert "free" in kinds and "credit" in kinds
    assert kinds[-1] == "credit", "Vertex는 마지막(없는 사용자가 많으므로)"


def test_empty_slots_excluded_from_chain(db):
    _set("free", "AIzaOnly_000000000000")
    assert [c["kind"] for c in _chain()] == ["free"]


def test_no_credentials_means_empty_chain(db):
    assert _chain() == []


# ── 조건2: Vertex 없이 API 키만으로 RAG 요약 ──────────────────────
SAMPLE_RESULTS = [
    {
        "title": "paper_A",
        "passages": [
            {"page": 3, "text": "「Coulombic」 efficiency가 92%까지 향상되었다"},
            {"page": 4, "text": "cathode의 capacity retention은 500 cycles 후 88%"},
        ],
    }
]


def test_build_prompt_includes_passages_and_sources():
    prompt, sources = answer_mod.build_prompt("ICE 개선?", SAMPLE_RESULTS)
    assert "92%" in prompt and "88%" in prompt
    assert "[1]" in prompt and "[2]" in prompt
    assert sources == ["paper_A p3", "paper_A p4"]
    assert "「" not in prompt, "하이라이트 마커는 제거되어야 함"


def test_build_prompt_truncates_long_passage():
    big = [{"title": "t", "passages": [{"page": 1, "text": "가" * 5000}]}]
    prompt, _ = answer_mod.build_prompt("q", big)
    assert len(prompt) < 1500, "발췌 길이 상한으로 비용을 통제해야 함"


def test_build_prompt_handles_no_results():
    prompt, sources = answer_mod.build_prompt("q", [])
    assert "관련 발췌 없음" in prompt
    assert sources == []


def test_extra_context_is_injected():
    prompt, _ = answer_mod.build_prompt("q", SAMPLE_RESULTS, "[그림분석] 임피던스 320→120")
    assert "임피던스 320→120" in prompt


@patch("google.genai.Client")
def test_summarize_uses_api_key_not_vertex(mock_client):
    """API 키 경로는 vertexai=True 를 쓰지 않는다(= GCP 없어도 동작)"""
    inst = MagicMock()
    inst.models.generate_content.return_value = MagicMock(text="ICE는 92%로 향상되었다 [1]")
    mock_client.return_value = inst

    text, sources = answer_mod.summarize("ICE?", SAMPLE_RESULTS, "AIzaTESTKEY")
    assert "92%" in text
    assert sources == ["paper_A p3", "paper_A p4"]
    kwargs = mock_client.call_args.kwargs
    assert kwargs.get("api_key") == "AIzaTESTKEY"
    assert "vertexai" not in kwargs, "API 키 경로에서 Vertex를 켜면 안 됨"
