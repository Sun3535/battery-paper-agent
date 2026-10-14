"""라이브러리 표시 — 진짜 제목 추출 검증.

문제(2026-07-28): 카드에 파일명(`oa_W7169633968`)만 떠서 91편 중 원하는 논문을 못 찾았다.
"""

import sqlite3

import pytest

import library
import store


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "lib.db")
    with store.connect() as c:
        c.execute(
            "INSERT INTO documents (doc_id,title,filename,pdf_path,source,status,created_at)"
            " VALUES ('D','oa_W123','oa_W123.pdf','x.pdf','upload','ready','t')"
        )
        yield c


def _add_block(c, order, text):
    c.execute(
        "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en) VALUES ('D',?,'text',1,'[]',?)",
        (order, text),
    )


# ── 제목 정리 ─────────────────────────────────────────────────────
def test_clean_title_collapses_whitespace():
    assert library.clean_title("  Solid   State\n Battery  ") == "Solid State Battery"


def test_clean_title_truncates():
    assert len(library.clean_title("가" * 500)) <= library.MAX_TITLE_LEN


# ── 본문에서 제목 뽑기 ────────────────────────────────────────────
def test_title_from_first_meaningful_block(db):
    _add_block(db, 1, "Interface Engineering in All-Solid-State Batteries")
    assert library.title_from_blocks(db, "D") == "Interface Engineering in All-Solid-State Batteries"


def test_skips_arxiv_stamp_and_doi(db):
    """arXiv 스탬프·DOI 같은 건 제목이 아니다"""
    _add_block(db, 1, "arXiv:2606.12999v1 [physics.chem-ph] 11 Jun 2026")
    _add_block(db, 2, "doi:10.1000/example.doi")
    _add_block(db, 3, "Impedance of the Cathode Catalyst Layer")
    assert library.title_from_blocks(db, "D") == "Impedance of the Cathode Catalyst Layer"


def test_skips_too_short_and_single_word(db):
    _add_block(db, 1, "Abstract")  # 단어 1개 → 제목 아님
    _add_block(db, 2, "Li")  # 너무 짧음
    _add_block(db, 3, "Sodium Ion Battery Anode Design")
    assert library.title_from_blocks(db, "D") == "Sodium Ion Battery Anode Design"


def test_returns_none_when_no_candidate(db):
    _add_block(db, 1, "2026")
    assert library.title_from_blocks(db, "D") is None


# ── 크롤러 DB 제목 우선 ───────────────────────────────────────────
def test_crawler_title_wins_over_blocks(db):
    db.executescript(
        "CREATE TABLE IF NOT EXISTS papers (paper_id TEXT, title TEXT, local_pdf_path TEXT);"
    )
    db.execute(
        "INSERT INTO papers VALUES ('p1','Official Journal Title From Crawler','/x/oa_W123.pdf')"
    )
    _add_block(db, 1, "Some Other Heading In The PDF")
    got = library.resolve_title(db, "D", "oa_W123.pdf", "oa_W123")
    assert got == "Official Journal Title From Crawler"


def test_falls_back_to_blocks_then_filename(db):
    # 크롤러 테이블이 없어도 죽지 않고 블록에서 뽑는다
    _add_block(db, 1, "Fallback Title From Document Body")
    assert library.resolve_title(db, "D", "oa_W123.pdf", "oa_W123") == "Fallback Title From Document Body"


def test_filename_used_when_nothing_else(db):
    got = library.resolve_title(db, "D", "oa_W123.pdf", "oa_W123")
    assert got == "oa_W123"


# ── 표지 ─────────────────────────────────────────────────────────
def test_make_cover_missing_pdf_returns_false(tmp_path):
    assert library.make_cover(tmp_path / "none.pdf", tmp_path / "img") is False


def test_cover_name_is_stable():
    """프론트가 이 이름으로 URL을 만든다 — 바뀌면 표지가 전부 깨진다"""
    assert library.COVER_NAME == "_cover.png"


# ── LaTeX 잔재 정리 (화면에 그대로 뜨던 문제) ─────────────────────
@pytest.mark.parametrize(
    "raw,expect",
    [
        ("phase of Na$_{0.5}$CoO$_2", "phase of Na0.5CoO2"),
        ("post-spinel CaV$_2$O$_4$ cathode", "post-spinel CaV2O4 cathode"),  # 공백 보존
        ("Li$^{+}$ transport", "Li+ transport"),
        (r"\textit{solid} electrolytes", "solid electrolytes"),
        ("Normal Title Without Any Math", "Normal Title Without Any Math"),
        ("Silicon anode: 3579 mAh/g capacity", "Silicon anode: 3579 mAh/g capacity"),
    ],
)
def test_clean_title_strips_latex(raw, expect):
    assert library.clean_title(raw) == expect


def test_underscore_outside_math_is_preserved():
    """파일명·식별자의 밑줄은 지우면 안 된다 (실측 회귀: oa_W123 → oaW123)"""
    assert library.clean_title("oa_W7169633968") == "oa_W7169633968"
    assert library.clean_title("arxiv_2606.12999") == "arxiv_2606.12999"
