"""논문 1편 한정 질문(scope) 검증 — 타 논문 혼입 차단이 핵심.

배경: Vertex AI Search는 데이터스토어 전체에서 스니펫을 뽑아 **다른 논문 내용을 섞는다**
(2026-07-16 실측: 대상 논문에 없는 synchrotron 문장이 번역/답변에 포함됨).
그래서 "이 논문만" 질문은 문서 경계가 정확한 로컬 경로로만 처리한다.
"""

import pytest

import figure_analysis as fa
import local_search
import store


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "scope.db")
    with store.connect() as conn:
        conn.executescript(
            "INSERT INTO documents (doc_id,title,filename,pdf_path,source,status,created_at)"
            " VALUES ('A','nature_paper','a.pdf','a','upload','ready','t'),"
            "        ('B','other_paper','b.pdf','b','upload','ready','t');"
        )
        local_search.ensure_index(conn)
        fa.ensure_table(conn)
        # 두 논문 모두 'impedance' 를 포함 — 범위 지정이 없으면 둘 다 걸린다
        for doc, order, page, body in [
            ("A", 1, 3, "impedance 반원이 320에서 120으로 감소한다 Nature 고유내용 alpha"),
            ("B", 1, 5, "impedance 측정에 synchrotron 을 사용했다 타논문 내용 beta"),
        ]:
            conn.execute(
                "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en) VALUES (?,?,?,?,'[]',?)",
                (doc, order, "text", page, body),
            )
            conn.execute(
                "INSERT INTO blocks_fts (doc_id,block_order,page,body) VALUES (?,?,?,?)",
                (doc, order, page, body),
            )
            conn.execute(
                "INSERT INTO figure_analyses (doc_id,block_order,analysis_ko,model,created_at)"
                " VALUES (?,?,?,'m','t')",
                (doc, order, f"{doc} 논문의 impedance 그림 분석"),
            )
    yield


# ── 검색 범위 ─────────────────────────────────────────────────────
def test_unscoped_search_returns_both_papers(db):
    with store.connect() as c:
        r = local_search.search(c, "impedance")
    titles = {g["title"] for g in r["results"]}
    assert titles == {"nature_paper", "other_paper"}, "전체 검색은 두 논문 모두 나와야 함"


def test_scoped_search_returns_only_that_paper(db):
    with store.connect() as c:
        r = local_search.search(c, "impedance", doc_id="A")
    assert [g["title"] for g in r["results"]] == ["nature_paper"]
    blob = str(r["results"])
    assert "synchrotron" not in blob, "타 논문 내용이 섞이면 안 됨(실측 오염 사례)"
    assert "beta" not in blob


def test_scoped_search_empty_when_term_only_in_other_paper(db):
    """대상 논문에 없는 단어면, 다른 논문에 있어도 빈 결과여야 한다"""
    with store.connect() as c:
        r = local_search.search(c, "synchrotron", doc_id="A")
    assert r["results"] == []


def test_scoped_search_unknown_doc_returns_empty(db):
    with store.connect() as c:
        assert local_search.search(c, "impedance", doc_id="ZZZ")["results"] == []


# ── 그림 분석 범위 ────────────────────────────────────────────────
def test_scoped_figure_analyses_only_that_paper(db):
    with store.connect() as c:
        got = fa.relevant_analyses(c, "impedance 그림", doc_id="A")
    assert got, "대상 논문의 그림 분석은 나와야 함"
    assert all(g["title"] == "nature_paper" for g in got)


def test_unscoped_figure_analyses_can_span_papers(db):
    with store.connect() as c:
        got = fa.relevant_analyses(c, "impedance 그림")
    assert len({g["title"] for g in got}) >= 1  # 전체 모드는 제한 없음


# ── 논문 1편 통독 모드 ────────────────────────────────────────────
def test_document_passages_returns_whole_paper_in_order(db):
    """검색이 아니라 읽기순서 그대로 전문을 돌려준다"""
    with store.connect() as c:
        c.execute(
            "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en)"
            " VALUES ('A',2,'text',4,'[]','두 번째 문단이며 충분히 길어서 포함되어야 한다')"
        )
    with store.connect() as c:
        whole = local_search.document_passages(c, "A")
    assert whole["full_document"] is True
    orders = [p["order"] for p in whole["results"][0]["passages"]]
    assert orders == sorted(orders), "읽기순서가 유지되어야 함"
    assert whole["results"][0]["title"] == "nature_paper"


def test_document_passages_only_target_doc(db):
    with store.connect() as c:
        whole = local_search.document_passages(c, "A")
    blob = str(whole["results"])
    assert "synchrotron" not in blob and "beta" not in blob


def test_document_passages_unknown_doc(db):
    with store.connect() as c:
        assert local_search.document_passages(c, "NOPE") is None


def test_document_passages_respects_char_cap(db):
    """긴 논문은 상한에서 잘려 비용이 폭주하지 않는다"""
    with store.connect() as c:
        for i in range(3, 30):
            c.execute(
                "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en)"
                " VALUES ('A',?,'text',1,'[]',?)",
                (i, "가" * 500),
            )
    with store.connect() as c:
        whole = local_search.document_passages(c, "A", max_chars=2000)
    assert whole["chars"] <= 2000


def test_full_doc_prompt_includes_more_passages():
    """통독 모드는 문단 상한이 커야 한다(검색 모드 8개 제한과 구분)"""
    import answer as A

    many = [{"title": "t", "passages": [{"page": 1, "text": f"문단{i} 내용입니다"} for i in range(50)]}]
    p_small, _ = A.build_prompt("q", many, full_doc=False)
    p_full, _ = A.build_prompt("q", many, full_doc=True)
    assert p_full.count("문단") > p_small.count("문단") * 3
