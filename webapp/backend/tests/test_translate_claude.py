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
    # 범위 밖 번호는 이제 묶음 전체를 실패로 본다(2차 점검) — 아래 test_bad_item_numbers_fail_only_that_batch
    client = FakeClient(_msg([{"i": 0, "t": "하나"}, {"i": 2, "t": "  "}]))
    out = translate_claude.translate_batch(["one", "two", "three"], "RULE", client=client)
    assert out == ["하나", None, None]


def test_refusal_raises(monkeypatch):
    client = FakeClient(_msg([], stop_reason="refusal", category="bio"))
    with pytest.raises(translate_claude.ClaudeBatchError, match="거절"):
        translate_claude.translate_batch(["one"], "RULE", client=client)


def test_truncated_output_raises():
    client = FakeClient(_msg([{"i": 0, "t": "하"}], stop_reason="max_tokens"))
    with pytest.raises(translate_claude.ClaudeBatchError, match="잘린"):
        translate_claude.translate_batch(["one"], "RULE", client=client)


def test_unreadable_response_raises():
    msg = _msg([])
    msg.content[1].text = "not json"
    with pytest.raises(translate_claude.ClaudeBatchError, match="읽지 못"):
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


# ── 블록 단위: 실패한 자리는 저장되지 않고, 한 묶음의 실패가 뒤 묶음을 막지 않는다 ──

def _three_batches(monkeypatch, replies):
    monkeypatch.setenv("TRANSLATE_PROVIDER", "claude")
    monkeypatch.setattr(translate, "PACING_SEC", 0)
    monkeypatch.setattr(translate, "MAX_CHARS_PER_CALL", 14)  # "text 10" 은 7자 → 2개씩 한 묶음
    it = iter(replies)
    calls = []

    def fake(texts, rule, usage=None, client=None):
        calls.append(list(texts))
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(translate_claude, "translate_batch", fake)
    return calls


def test_failed_batch_is_skipped_and_later_batches_still_run(monkeypatch):
    """점검(2026-10-14): 한 묶음이 거절·잘림으로 실패하면 거기서 멈춰, 다시 눌러도 그 뒤는 영영 번역되지 않았다."""
    calls = _three_batches(monkeypatch, [
        ["십", None],                                        # 11번은 번역문이 안 돌아옴
        translate_claude.ClaudeBatchError("거절한 묶음"),      # 둘째 묶음 통째 실패
        ["십사", "십오"],                                     # 셋째 묶음은 그래도 번역돼야 한다
    ])
    blocks = [{"order": n, "text": f"text {n}"} for n in (10, 11, 12, 13, 14, 15)]
    saved: dict[int, str] = {}
    with pytest.raises(translate.TranslationIncomplete) as e:
        translate.translate_blocks(blocks, on_batch=lambda m, d, t: saved.update(m))
    assert len(calls) == 3
    assert saved == {10: "십", 14: "십사", 15: "십오"}  # 실패한 자리는 원문으로 채우지 않는다
    assert "문단 3개" in str(e.value) and "거절한 묶음" in str(e.value)  # 사유가 사용자에게 간다


def test_fatal_error_stops_immediately(monkeypatch):
    """키 없음·잠금처럼 어느 묶음이든 똑같이 실패할 오류는 묶음마다 되풀이하지 않고 바로 멈춘다."""
    calls = _three_batches(monkeypatch, [translate_claude.ClaudeTranslateError("키 없음"), ["x", "y"], ["z", "w"]])
    blocks = [{"order": n, "text": f"text {n}"} for n in (10, 11, 12, 13, 14, 15)]
    with pytest.raises(translate_claude.ClaudeTranslateError, match="키 없음"):
        translate.translate_blocks(blocks)
    assert len(calls) == 1


def test_same_text_is_sent_once_and_saved_to_every_block(monkeypatch):
    """캡션은 그림 블록과 캡션 글 블록에 같은 글로 들어 있다 — 한 번만 번역해 양쪽에 저장한다."""
    calls = _three_batches(monkeypatch, [["캡션", "본문"]])
    monkeypatch.setattr(translate, "MAX_CHARS_PER_CALL", 6000)
    blocks = [
        {"order": 5, "text": "Fig. 1 XRD patterns"},   # 그림 블록에 붙은 캡션
        {"order": 6, "text": "Fig. 1 XRD patterns"},   # 같은 글의 캡션 블록
        {"order": 7, "text": "Body paragraph here."},
    ]
    out = translate.translate_blocks(blocks)
    assert calls == [["Fig. 1 XRD patterns", "Body paragraph here."]]
    assert out == {5: "캡션", 6: "캡션", 7: "본문"}


# ── Gemini 경로: 실패를 원문으로 채워 "번역됨" 으로 저장하지 않는다 ──

class _FakeGemini:
    def __init__(self, text):
        self.text = text
        self.models = self

    def generate_content(self, **kw):
        return SimpleNamespace(text=self.text)


def test_gemini_missing_item_is_none_not_source_text(monkeypatch):
    fake = _FakeGemini(json.dumps([{"i": 0, "t": "하나"}, {"i": 1, "t": ""}], ensure_ascii=False))
    monkeypatch.setattr(translate, "_get_client_and_model", lambda api_key=None: (fake, "m"))
    assert translate.translate_batch(["one", "two"]) == ["하나", None]


def test_gemini_unreadable_response_is_batch_error_not_saved_as_translation(monkeypatch):
    """예전에는 응답을 못 읽으면 원문을 그대로 돌려줘, 영어가 번역본으로 저장됐다(74c7587c969a 의 Fig. 5 캡션)."""
    monkeypatch.setattr(translate, "_get_client_and_model", lambda api_key=None: (_FakeGemini("not json"), "m"))
    with pytest.raises(translate.BatchError, match="읽지 못"):
        translate.translate_batch(["one", "two"])


# ── "번역 대상" 은 한 가지 기준 ───────────────────────────────

def test_number_only_blocks_do_not_block_completion(tmp_path, monkeypatch):
    """숫자·기호뿐인 블록은 번역기가 보내지 않는다 — 그런 블록 때문에 '번역 완료' 가 안 되면 안 된다."""
    import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "t.db")
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO documents (doc_id,title,filename,pdf_path,source,status,created_at)"
            " VALUES ('d','t','d.pdf','x.pdf','upload','ready','t')"
        )
        for order, text in ((1, "A real sentence."), (2, "0 100 200 300"), (3, "12.5")):
            conn.execute(
                "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en) VALUES ('d',?, 'text',1,'[]',?)",
                (order, text),
            )
        assert [b["order"] for b in store.untranslated_blocks(conn, "d")] == [1]
        st = store.paid_status_map(conn)["d"]
        assert (st["text_blocks"], st["translated_blocks"], st["translate_complete"]) == (1, 0, False)
        store.save_translations(conn, "d", {1: "진짜 문장."}, "m")
        st = store.paid_status_map(conn)["d"]
        assert (st["text_blocks"], st["translated_blocks"], st["translate_complete"]) == (1, 1, True)
        assert store.untranslated_blocks(conn, "d") == []


# ── 화면에 보여 줄 비용 어림값 ─────────────────────────────────

def test_cost_hint_follows_provider_and_model(monkeypatch):
    assert translate.cost_hint() == {
        "provider": "gemini", "model": "gemini-2.5-flash", "per_page_krw": None, "per_paper_krw": 121,
    }
    monkeypatch.setenv("TRANSLATE_PROVIDER", "claude")
    assert translate.cost_hint()["per_page_krw"] == 70  # 기본 Opus 5.5 (실측)
    monkeypatch.setenv("CLAUDE_TRANSLATE_MODEL", "claude-sonnet-5-5")
    assert translate.cost_hint()["per_page_krw"] == 35
    monkeypatch.setenv("CLAUDE_TRANSLATE_MODEL", "claude-haiku-5-5")
    assert translate.cost_hint()["per_page_krw"] == 2


# ── 2차 점검: 번호가 이상한 응답은 그 묶음만 실패로 ─────────────────────

@pytest.mark.parametrize("items", [
    [{"t": "가"}, {"i": 1, "t": "나"}],                 # 번호 없음
    [{"i": 0, "t": "가"}, {"i": 0, "t": "나"}],          # 번호 겹침
    [{"i": 1, "t": "가"}, {"i": 2, "t": "나"}],          # 1부터 매김(하나 밀림)
])
def test_bad_item_numbers_fail_only_that_batch(monkeypatch, items):
    import json as _json

    monkeypatch.setenv("PAID_APIS_ENABLED", "true")
    import guard

    monkeypatch.setattr(guard, "paid_apis_enabled", lambda: True)

    class Msg:
        stop_reason = "end_turn"
        usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
        content = [type("B", (), {"type": "text", "text": _json.dumps({"items": items})})()]

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return Msg()

    class Client:
        class messages:
            @staticmethod
            def stream(**kw):
                return Stream()

    import translate
    import translate_claude as tc

    with pytest.raises(tc.ClaudeBatchError):
        tc.translate_batch(["a", "b"], "rule", client=Client())
    assert issubclass(tc.ClaudeBatchError, translate.BatchError)  # → translate_blocks 가 건너뛰고 계속한다


def test_interrupted_documents_are_released_on_start(tmp_path, monkeypatch):
    import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "r.db")
    with store.connect() as conn:
        conn.executescript(
            "INSERT INTO documents (doc_id,title,filename,pdf_path,source,status,created_at) VALUES"
            " ('a','t','a.pdf','a','upload','translating','t'), ('b','t','b.pdf','b','upload','extracting','t'),"
            " ('c','t','c.pdf','c','upload','ready','t');"
        )
        assert store.recover_interrupted(conn) == 2
        rows = dict(conn.execute("SELECT doc_id, status FROM documents").fetchall())
    assert rows == {"a": "ready", "b": "failed", "c": "ready"}


def test_recovery_runs_on_server_start_not_on_import():
    """2차 감독 점검: import 때 돌면 시험·두 번째 실행이 진행 중인 번역을 '꺼졌다' 로 바꾼다."""
    import importlib

    import main

    src = importlib.util.find_spec("main").origin
    text = open(src, encoding="utf-8").read()
    assert "\n_recover_interrupted()\n" not in text
    assert any(getattr(h, "__name__", "") == "_recover_interrupted" for h in main.app.router.on_startup)


def test_second_server_does_not_recover(tmp_path, monkeypatch):
    import main
    import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "x.db")
    monkeypatch.setattr(main, "_INSTANCE_LOCK", None)
    assert main._only_server_running() is True
    first = main._INSTANCE_LOCK
    monkeypatch.setattr(main, "_INSTANCE_LOCK", None)
    assert main._only_server_running() is False  # 첫 번째가 쥐고 있다
    first.close()
