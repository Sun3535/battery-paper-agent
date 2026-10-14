"""챗봇이 '읽은 만큼만 읽었다'고 말하는가 — 점검(2026-10-14)에서 나온 것들.

- 「이 논문만」은 논문을 통째로 건네지만 한도(4만 자)가 있어, 긴 논문은 앞부분만 간다. 그런데도 "전문을 읽었다"고 했다.
- 통독한 문단 수십 개가 답 밑에 그대로 깔려 답이 화면 밖으로 밀렸다 → 화면에는 "어디까지 읽었는지"만 보낸다.
- 그 바람에 AI 요약이 잠긴 상태에서는 그 논문의 구절이 하나도 안 보였다 → 잠금·키워드 응답에는 '찾은 구절'을 싣는다.
- 검색으로 찾은 구절이 30자짜리 조각이었다 → 찾은 낱말 둘레 700자.
"""

import pytest

import local_search
import main
import store


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "chat.db")
    monkeypatch.setenv("PAID_APIS_ENABLED", "false")
    monkeypatch.setenv("USE_LOCAL_LLM", "false")
    monkeypatch.delenv("SEARCH_MODE", raising=False)
    with store.connect() as conn:
        conn.executescript(
            "INSERT INTO documents (doc_id,title,filename,pdf_path,source,status,created_at,page_count)"
            " VALUES ('A','long_paper','a.pdf','a','upload','ready','t',30),"
            "        ('B','other_paper','b.pdf','b','upload','ready','t',5);"
        )
        local_search.ensure_index(conn)
        rows = [("A", i, i, f"paragraph {i} " + ("filler words about electrolyte " * 60)) for i in range(1, 31)]
        rows[19] = ("A", 20, 20, "the dendrite growth was suppressed at high current density " + "x " * 200)
        rows.append(("B", 1, 2, "dendrite formation in the other paper"))
        for doc, order, page, body in rows:
            conn.execute(
                "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en) VALUES (?,?,?,?,'[]',?)",
                (doc, order, "text", page, body),
            )
            conn.execute("INSERT INTO blocks_fts (doc_id,block_order,page,body) VALUES (?,?,?,?)", (doc, order, page, body))
    yield


def test_long_paper_coverage_says_how_far_it_read(db):
    with store.connect() as c:
        packed = local_search.focused_passages(c, ["A"], "dendrite")
    cov = packed["coverage"][0]
    assert cov["truncated"] is True
    assert cov["read_chars"] <= 40_000 < cov["total_chars"]
    assert 1 <= cov["read_until_page"] < cov["pages"] == 30
    note = main._coverage_note(packed["coverage"])
    assert "📖" in note and str(cov["read_until_page"]) in note


def test_short_paper_has_no_warning(db):
    with store.connect() as c:
        packed = local_search.focused_passages(c, ["B"], "dendrite")
    assert packed["coverage"][0]["truncated"] is False
    assert main._coverage_note(packed["coverage"]) == ""


def test_preamble_does_not_claim_full_text_when_cut(db):
    with store.connect() as c:
        packed = local_search.focused_passages(c, ["A"], "dendrite")
    text = main._focus_preamble(["long_paper"], [], True, packed["coverage"])
    assert "전문" not in text
    assert "발췌" in text


def test_locked_scoped_question_still_shows_found_passages(db):
    """잠금 상태 + 「이 논문만」: 20쪽의 dendrite 문단이 보여야 한다(통독 한도 밖이어도)."""
    r = main.chat(main.ChatRequest(question="dendrite", doc_ids=["A"]))
    assert r["mode"] == "locked"
    assert r["coverage"] == [], "아무도 읽지 않았는데 '어디까지 읽었다'고 하면 안 된다"
    mine = [g for g in r["results"] if g["doc_id"] == "A"]
    assert len(mine) == 1 and not mine[0].get("full")
    assert any(p["page"] == 20 and "dendrite" in p["text"] for p in mine[0]["passages"])
    assert "찾았습니다" in r["answer"]


def test_locked_scoped_question_without_match_says_not_found(db):
    r = main.chat(main.ChatRequest(question="perovskite", doc_ids=["A"]))
    mine = [g for g in r["results"] if g["doc_id"] == "A"]
    assert mine and mine[0]["passages"] == []
    assert "찾지 못했습니다" in r["answer"]


def test_search_passage_is_a_window_not_a_30_char_snippet(db):
    with store.connect() as c:
        r = local_search.search(c, "dendrite suppressed", doc_id="A")
    text = r["results"][0]["passages"][0]["text"]
    assert len(text) > 150
    assert "high current density" in text


def test_sources_are_compacted_per_paper():
    many = [f"long_paper p{n}" for n in range(1, 40)] + ["other_paper p2"]
    out = main._compact_sources(many)
    assert len(out) <= 3
    assert any("long_paper" in s for s in out) and any("other_paper" in s for s in out)
