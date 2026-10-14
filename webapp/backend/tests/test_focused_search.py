"""체크한 논문 집중 답변 — "체크한 논문 위주로, 나머지는 참고로" (호야 지시 2026-07-28).

핵심 계약: 집중 논문이 **결과 앞쪽**에 오고, 참고 논문은 뒤에 붙되 절대 앞을 밀어내지 않는다.
프롬프트가 "앞쪽이 선택한 논문"이라고 알려주므로 순서가 곧 정확도다.
"""

import local_search
import store


def _paper(conn, doc_id, title, paragraphs):
    conn.execute(
        "INSERT INTO documents (doc_id,title,filename,pdf_path,source,status,created_at)"
        " VALUES (?,?,?,?, 'upload','ready','t')",
        (doc_id, title, f"{doc_id}.pdf", "x.pdf"),
    )
    for i, p in enumerate(paragraphs, 1):
        conn.execute(
            "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en)"
            " VALUES (?,?, 'text',1,'[]',?)",
            (doc_id, i, p),
        )
    local_search.index_document(conn, doc_id)


def _library(conn):
    _paper(
        conn,
        "P1",
        "Solid Electrolyte Interface Study",
        ["The solid electrolyte interphase governs dendrite growth in this cell chemistry."],
    )
    _paper(
        conn,
        "P2",
        "Cathode Capacity Retention Report",
        ["Capacity retention of the cathode reached ninety percent after cycling."],
    )
    _paper(
        conn,
        "P3",
        "Unrelated Synchrotron Method",
        ["Synchrotron radiation was used for operando structural characterization."],
    )


def test_single_focus_paper_comes_first(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f1.db")
    with store.connect() as conn:
        _library(conn)
        r = local_search.focused_passages(conn, ["P2"], "capacity retention")
    assert r is not None
    assert r["results"][0]["doc_id"] == "P2"
    assert r["focus_ids"] == ["P2"]
    assert r["focus_titles"] == ["Cathode Capacity Retention Report"]


def test_multiple_focus_papers_all_included_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f2.db")
    with store.connect() as conn:
        _library(conn)
        r = local_search.focused_passages(conn, ["P1", "P2"], "dendrite")
    head = [g["doc_id"] for g in r["results"][:2]]
    assert head == ["P1", "P2"]
    assert len(r["focus_titles"]) == 2


def test_reference_papers_never_precede_focus(tmp_path, monkeypatch):
    """참고 논문이 앞에 끼면 모델이 남의 논문을 주인공으로 착각한다"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f3.db")
    with store.connect() as conn:
        _library(conn)
        # 질문은 P3(참고감)에 훨씬 잘 맞지만, 사용자가 체크한 건 P1이다
        r = local_search.focused_passages(conn, ["P1"], "synchrotron radiation")
    assert r["results"][0]["doc_id"] == "P1"
    assert "P1" not in [g["doc_id"] for g in r["results"][1:]]


def test_focus_paper_excluded_from_reference_list(tmp_path, monkeypatch):
    """집중 논문이 참고로 또 들어가면 같은 발췌가 두 번 과금된다"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f4.db")
    with store.connect() as conn:
        _library(conn)
        r = local_search.focused_passages(conn, ["P1"], "dendrite growth interphase")
    ids = [g["doc_id"] for g in r["results"]]
    assert ids.count("P1") == 1
    assert "P1" not in r["reference_titles"]


def test_references_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f5.db")
    with store.connect() as conn:
        _library(conn)
        r = local_search.focused_passages(conn, ["P1"], "dendrite", reference_docs=0)
    assert r["reference_titles"] == []
    assert [g["doc_id"] for g in r["results"]] == ["P1"]


def test_duplicate_ids_are_collapsed(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f6.db")
    with store.connect() as conn:
        _library(conn)
        r = local_search.focused_passages(conn, ["P1", "P1"], "dendrite")
    assert r["focus_ids"] == ["P1"]


def test_empty_selection_returns_none(tmp_path, monkeypatch):
    """선택이 없으면 집중 모드가 아니다 — 호출부가 전체 검색으로 넘어가야 한다"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f7.db")
    with store.connect() as conn:
        _library(conn)
        assert local_search.focused_passages(conn, [], "anything") is None
        assert local_search.focused_passages(conn, ["", "  "], "anything") is None


def test_char_budget_is_split_across_focus_papers(tmp_path, monkeypatch):
    """논문 5편을 체크했다고 프롬프트가 5배로 불면 비용이 5배가 된다"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "f8.db")
    long_para = "Electrochemical impedance spectroscopy of the cathode catalyst layer. " * 60
    with store.connect() as conn:
        _paper(conn, "L1", "Long One", [long_para])
        _paper(conn, "L2", "Long Two", [long_para])
        r = local_search.focused_passages(conn, ["L1", "L2"], "impedance", total_chars=8_000)
    total = sum(len(p["text"]) for g in r["results"] for p in g["passages"])
    assert total <= 8_000 + 4_000  # 편당 하한(4000) 보정을 감안한 상한
