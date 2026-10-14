"""유료 산출물 현황 + 유료 API 스위치.

배경(2026-07-28 호야 지적):
  - 카드의 '완료' 하나로는 번역이 끝난 건지 그림분석이 끝난 건지 알 수 없다.
    버튼이 두 개(둘 다 유료)라 헷갈리면 이미 낸 돈을 또 낸다.
  - 상단 배지를 눌러 그 자리에서 유료 API를 잠글 수 있어야 한다.
"""

import guard
import store


def _doc(conn, doc_id):
    conn.execute(
        "INSERT INTO documents (doc_id,title,filename,pdf_path,source,status,created_at)"
        " VALUES (?,?,?,?, 'upload','ready','t')",
        (doc_id, f"제목 {doc_id}", f"{doc_id}.pdf", "x.pdf"),
    )


def _text(conn, doc_id, order, translated=False):
    conn.execute(
        "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en)"
        " VALUES (?,?, 'text',1,'[]','body text')",
        (doc_id, order),
    )
    if translated:
        conn.execute(
            "INSERT INTO translations (doc_id,block_order,text_ko,model,created_at)"
            " VALUES (?,?,'본문','m','t')",
            (doc_id, order),
        )


def _figure(conn, doc_id, order, analyzed=False):
    conn.execute(
        "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en,image_path)"
        " VALUES (?,?, 'image',1,'[]','Fig. 1',?)",
        (doc_id, order, f"p1_fig_{order}.png"),
    )
    if analyzed:
        store.ensure_figure_table(conn)
        conn.execute(
            "INSERT INTO figure_analyses (doc_id,block_order,analysis_ko,model,created_at)"
            " VALUES (?,?,'분석','m','t')",
            (doc_id, order),
        )


# ── 현황 집계 ────────────────────────────────────────────────────
def test_untouched_document_reports_nothing_paid(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "a.db")
    with store.connect() as conn:
        _doc(conn, "A")
        _text(conn, "A", 1)
        _figure(conn, "A", 2)
        s = store.paid_status_map(conn)["A"]
    assert s["translated"] is False and s["analyzed"] is False
    assert s["translate_complete"] is False and s["analyze_complete"] is False


def test_fully_translated_document(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "b.db")
    with store.connect() as conn:
        _doc(conn, "B")
        _text(conn, "B", 1, translated=True)
        _text(conn, "B", 2, translated=True)
        s = store.paid_status_map(conn)["B"]
    assert s["translated"] is True
    assert s["translate_complete"] is True
    assert (s["translated_blocks"], s["text_blocks"]) == (2, 2)


def test_partial_translation_still_counts_as_paid(tmp_path, monkeypatch):
    """절반만 번역돼도 이미 돈은 나갔다 — 버튼을 다시 열어주면 안 된다"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "c.db")
    with store.connect() as conn:
        _doc(conn, "C")
        _text(conn, "C", 1, translated=True)
        _text(conn, "C", 2)
        s = store.paid_status_map(conn)["C"]
    assert s["translated"] is True
    assert s["translate_complete"] is False
    assert (s["translated_blocks"], s["text_blocks"]) == (1, 2)


def test_translation_and_analysis_are_tracked_separately(tmp_path, monkeypatch):
    """핵심 요구: 두 유료 작업이 서로 다른 배지를 가져야 한다.

    그림 블록의 캡션("Fig. 1")도 번역 대상이다(store.untranslated_blocks 가 text_en 있는
    블록을 전부 집는다). 그래서 '번역 완료'가 되려면 캡션까지 번역돼 있어야 한다.
    """
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "d.db")
    with store.connect() as conn:
        _doc(conn, "D")
        _text(conn, "D", 1, translated=True)
        _figure(conn, "D", 2, analyzed=False)
        s = store.paid_status_map(conn)["D"]
        assert s["translate_complete"] is False  # 캡션이 아직 안 됐다
        # 캡션까지 번역하면 비로소 완료
        conn.execute(
            "INSERT INTO translations (doc_id,block_order,text_ko,model,created_at)"
            " VALUES ('D',2,'그림 1','m','t')"
        )
        s = store.paid_status_map(conn)["D"]

    assert s["translated"] is True and s["translate_complete"] is True
    # 번역이 끝나도 그림분석은 여전히 '안 함' — 두 배지가 독립이라는 게 요구사항의 핵심
    assert s["analyzed"] is False and s["analyze_complete"] is False


def test_analysis_without_translation(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "e.db")
    with store.connect() as conn:
        _doc(conn, "E")
        _text(conn, "E", 1)
        _figure(conn, "E", 2, analyzed=True)
        s = store.paid_status_map(conn)["E"]
    assert s["translated"] is False
    assert s["analyzed"] is True and s["analyze_complete"] is True


def test_document_with_no_figures_is_not_analyze_complete(tmp_path, monkeypatch):
    """그림이 0장인 논문을 '분석 완료'로 칠하면 안 된다(한 적이 없다)"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f.db")
    with store.connect() as conn:
        _doc(conn, "F")
        _text(conn, "F", 1, translated=True)
        s = store.paid_status_map(conn)["F"]
    assert s["figure_blocks"] == 0
    assert s["analyze_complete"] is False


def test_status_map_isolates_documents(tmp_path, monkeypatch):
    """한 논문의 번역이 다른 논문 배지에 새면 안 된다"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "g.db")
    with store.connect() as conn:
        _doc(conn, "G1")
        _doc(conn, "G2")
        _text(conn, "G1", 1, translated=True)
        _text(conn, "G2", 1)
        m = store.paid_status_map(conn)
    assert m["G1"]["translated"] is True
    assert m["G2"]["translated"] is False


# ── 화면 스위치 (유료 API 잠금) ──────────────────────────────────
def test_override_locks_even_when_env_is_true(monkeypatch):
    monkeypatch.setenv("PAID_APIS_ENABLED", "true")
    monkeypatch.setenv("OFFLINE_MODE", "false")
    guard.set_paid_override(None)
    assert guard.paid_apis_enabled() is True
    try:
        guard.set_paid_override(False)
        assert guard.paid_apis_enabled() is False
    finally:
        guard.set_paid_override(None)


def test_offline_mode_beats_override(monkeypatch):
    """오프라인 모드에서는 스위치를 켜도 절대 열리지 않는다"""
    monkeypatch.setenv("OFFLINE_MODE", "true")
    try:
        guard.set_paid_override(True)
        assert guard.paid_apis_enabled() is False
    finally:
        guard.set_paid_override(None)


def test_clearing_override_returns_to_env(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "false")
    monkeypatch.setenv("PAID_APIS_ENABLED", "false")
    guard.set_paid_override(True)
    assert guard.paid_apis_enabled() is True
    guard.set_paid_override(None)
    assert guard.paid_apis_enabled() is False


def test_state_roundtrip(tmp_path, monkeypatch):
    """잠근 상태로 서버를 재시작해도 다시 열리면 안 된다 → DB에 남는다"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "s.db")
    with store.connect() as conn:
        assert store.get_state(conn, store.PAID_STATE_KEY) is None
        store.set_state(conn, store.PAID_STATE_KEY, "0")
    with store.connect() as conn:
        assert store.get_state(conn, store.PAID_STATE_KEY) == "0"
        store.set_state(conn, store.PAID_STATE_KEY, None)
    with store.connect() as conn:
        assert store.get_state(conn, store.PAID_STATE_KEY) is None
