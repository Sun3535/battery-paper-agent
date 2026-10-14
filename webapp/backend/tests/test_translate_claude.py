"""Claude 번역 채널 — 실제 호출 없이(가짜 클라이언트) 고정하는 것들.

배경(2026-10-14 호야): 번역 비용을 Claude 크레딧으로 임시 사용, 나중에는 사내 API 로 교체 예정.
돈이 나가는 경로라 실제 호출 전에 여기서 먼저 확인한다:
  - 공급자 선택이 정확한가 (claude 를 골랐는데 Gemini 로 새지 않는가, 오타면 멈추는가)
  - 실패가 "번역됨"으로 저장되지 않는가 (거절·잘림·빠진 항목)
  - 하드락·키 없음이 호출 전에 걸리는가
"""

import json
from types import SimpleNamespace

import pytest

import guard
import translate
import translate_claude


def _msg(items, stop_reason="end_turn", in_tok=100, out_tok=50, category=None):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if category else None,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=json.dumps({"items": items}, ensure_ascii=False)),
        ],
        usage=SimpleNamespace(
            input_tokens=in_tok, output_tokens=out_tok,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        ),
    )


class FakeClient:
    """anthropic.Anthropic 의 messages.stream(...) 만 흉내 낸다."""

    def __init__(self, message):
        self.message = message
        self.calls: list[dict] = []
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        outer = self

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return outer.message

        return _Ctx()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in ("TRANSLATE_PROVIDER", "CLAUDE_TRANSLATE_MODEL", "CLAUDE_TRANSLATE_EFFORT",
              "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OFFLINE_MODE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PAID_APIS_ENABLED", "true")
    guard.set_paid_override(None)
    yield
    guard.set_paid_override(None)


# ── 공급자 선택 ──────────────────────────────────────────────

def test_default_provider_is_gemini():
    assert translate.provider() == "gemini"
    assert translate.current_model_name() == "gemini-2.5-flash"


def test_claude_provider_and_model(monkeypatch):
    monkeypatch.setenv("TRANSLATE_PROVIDER", " Claude ")
    assert translate.provider() == "claude"
    assert translate.current_model_name() == "claude-opus-5-5"
    monkeypatch.setenv("CLAUDE_TRANSLATE_MODEL", "claude-haiku-5-5")
    assert translate.current_model_name() == "claude-haiku-5-5"


def test_unknown_provider_stops_instead_of_falling_back(monkeypatch):
    monkeypatch.setenv("TRANSLATE_PROVIDER", "cluade")  # 오타
    with pytest.raises(RuntimeError, match="TRANSLATE_PROVIDER"):
        translate.provider()
    with pytest.raises(RuntimeError):
        translate.translate_batch(["x y z"])


def test_claude_never_touches_gemini(monkeypatch):
    """claude 를 골랐으면 Gemini 클라이언트 생성 경로에 들어가면 안 된다(다른 계정 과금 방지)."""
    monkeypatch.setenv("TRANSLATE_PROVIDER", "claude")
    monkeypatch.setattr(translate, "_get_client_and_model", lambda *a, **k: pytest.fail("Gemini 경로 진입"))
    seen = {}

    def fake(texts, rule, usage=None, client=None):
        seen["rule"] = rule
        return ["가", "나"]

    monkeypatch.setattr(translate_claude, "translate_batch", fake)
    assert translate.translate_batch(["a b c", "d e f"]) == ["가", "나"]
    assert seen["rule"] is translate.SYSTEM_RULE  # 번역 규칙은 한 곳(translate.py)에서만


# ── 한 번의 호출 ─────────────────────────────────────────────

def test_batch_maps_by_index_and_counts_tokens():
    client = FakeClient(_msg([{"i": 1, "t": "둘"}, {"i": 0, "t": "하나"}], in_tok=321, out_tok=123))
    usage = translate.TranslationUsage()
    out = translate_claude.translate_batch(["one", "two"], "RULE", usage, client=client)
    assert out == ["하나", "둘"]  # 순서가 뒤바뀌어 와도 번호로 되찾는다
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (1, 321, 123)

    req = client.calls[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["system"] == "RULE"
    assert req["output_config"]["effort"] == "low"
    assert req["output_config"]["format"]["type"] == "json_schema"
    # Opus 5.5 는 thinking 끄기·샘플링 값·budget 을 보내면 400 — 아예 보내지 않는다
    for banned in ("thinking", "temperature", "top_p", "top_k"):
        assert banned not in req
    sent = json.loads(req["messages"][0]["content"].split("\n\n", 1)[1])
    assert sent == [{"i": 0, "t": "one"}, {"i": 1, "t": "two"}]


def test_missing_or_empty_item_is_none_not_source_text():
    client = FakeClient(_msg([{"i": 0, "t": "하나"}, {"i": 2, "t": "  "}, {"i": 9, "t": "범위 밖"}]))
    out = translate_claude.translate_batch(["one", "two", "three"], "RULE", client=client)
    assert out == ["하나", None, None]


def test_refusal_raises(monkeypatch):
    client = FakeClient(_msg([], stop_reason="refusal", category="bio"))
    with pytest.raises(translate_claude.ClaudeTranslateError, match="거절"):
        translate_claude.translate_batch(["one"], "RULE", client=client)


def test_truncated_output_raises():
    client = FakeClient(_msg([{"i": 0, "t": "하"}], stop_reason="max_tokens"))
    with pytest.raises(translate_claude.ClaudeTranslateError, match="잘렸"):
        translate_claude.translate_batch(["one"], "RULE", client=client)


def test_unreadable_response_raises():
    msg = _msg([])
    msg.content[1].text = "not json"
    with pytest.raises(translate_claude.ClaudeTranslateError, match="읽지 못"):
        translate_claude.translate_batch(["one"], "RULE", client=FakeClient(msg))


# ── 호출 전에 걸러야 하는 것 ──────────────────────────────────

def test_hard_lock_blocks_before_any_client(monkeypatch):
    monkeypatch.setenv("PAID_APIS_ENABLED", "false")
    monkeypatch.setattr(translate_claude, "_client", lambda: pytest.fail("잠겼는데 클라이언트 생성"))
    client = FakeClient(_msg([{"i": 0, "t": "하나"}]))
    with pytest.raises(guard.PaidApiLocked):
        translate_claude.translate_batch(["one"], "RULE", client=client)
    assert client.calls == []


def test_no_key_stops_before_client(monkeypatch):
    monkeypatch.setattr(translate_claude, "_client", lambda: pytest.fail("키 없이 클라이언트 생성"))
    with pytest.raises(translate_claude.ClaudeTranslateError, match="ANTHROPIC_API_KEY"):
        translate_claude.translate_batch(["one"], "RULE")


def test_ready_reports_missing_key(monkeypatch):
    monkeypatch.setenv("TRANSLATE_PROVIDER", "claude")
    ok, why = translate.ready(None)
    assert not ok and "ANTHROPIC_API_KEY" in why
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    assert translate.ready(None)[0] is True


# ── 블록 단위: 실패한 자리는 저장되지 않는다 ───────────────────

def test_blocks_skip_untranslated_and_stop_on_error(monkeypatch):
    monkeypatch.setenv("TRANSLATE_PROVIDER", "claude")
    monkeypatch.setattr(translate, "PACING_SEC", 0)
    monkeypatch.setattr(translate, "MAX_CHARS_PER_CALL", 12)  # 블록 2개씩 한 배치
    blocks = [{"order": n, "text": f"text {n}"} for n in (10, 11, 12, 13)]
    replies = iter([["십", None], translate_claude.ClaudeTranslateError("거절")])

    def fake(texts, rule, usage=None, client=None):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(translate_claude, "translate_batch", fake)
    saved: dict[int, str] = {}
    with pytest.raises(translate_claude.ClaudeTranslateError):
        translate.translate_blocks(blocks, on_batch=lambda m, d, t: saved.update(m))
    # 첫 배치에서 받은 것만 저장. 못 받은 11번과 실패한 둘째 배치(12·13)는 미번역으로 남는다.
    assert saved == {10: "십"}


# ── 화면에 보여 줄 비용 어림값 ─────────────────────────────────

def test_cost_hint_follows_provider_and_model(monkeypatch):
    assert translate.cost_hint() == {
        "provider": "gemini", "model": "gemini-2.5-flash", "per_page_krw": None, "per_paper_krw": 121,
    }
    monkeypatch.setenv("TRANSLATE_PROVIDER", "claude")
    assert translate.cost_hint()["per_page_krw"] == 40  # 기본 Opus 5.5
    monkeypatch.setenv("CLAUDE_TRANSLATE_MODEL", "claude-sonnet-5-5")
    assert translate.cost_hint()["per_page_krw"] == 20
    monkeypatch.setenv("CLAUDE_TRANSLATE_MODEL", "claude-haiku-5-5")
    assert translate.cost_hint()["per_page_krw"] == 1
