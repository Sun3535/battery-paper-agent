"""DB dedup/CRUD 단위 테스트 — 테스트마다 임시 파일 DB로 격리."""

import pytest

from crawler import config, db
from crawler.schema import Paper


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test_papers.db")
    yield


def _sample_paper(paper_id: str = "arxiv:1234", pdf_url: str | None = "http://example.com/x.pdf") -> Paper:
    return Paper(
        paper_id=paper_id,
        source="arxiv",
        title="Test Title",
        authors=["Author A"],
        abstract="abstract text",
        published_date="2026-01-01",
        keyword_matched="테스트",
        pdf_url=pdf_url,
    )


def test_upsert_dedup():
    with db.connect() as conn:
        assert db.upsert_paper(conn, _sample_paper(), collected_at="now") is True
        assert db.upsert_paper(conn, _sample_paper(), collected_at="now") is False


def test_papers_without_pdf():
    with db.connect() as conn:
        db.upsert_paper(conn, _sample_paper(), collected_at="now")
        db.upsert_paper(conn, _sample_paper(paper_id="arxiv:5678", pdf_url=None), collected_at="now")
        rows = db.papers_without_pdf(conn)
        assert len(rows) == 1
        assert rows[0]["paper_id"] == "arxiv:1234"


def test_set_pdf_downloaded_removes_from_pending():
    with db.connect() as conn:
        db.upsert_paper(conn, _sample_paper(), collected_at="now")
        db.set_pdf_downloaded(conn, "arxiv:1234", "/path/x.pdf", "deadbeef")
        assert db.papers_without_pdf(conn) == []


def test_record_run():
    with db.connect() as conn:
        db.record_run(conn, "arxiv", "테스트", "start", "end", 3, "success")
        cur = conn.execute("SELECT * FROM crawl_runs")
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["new_papers_found"] == 3


def test_papers_ready_for_search_index_empty_until_gcs_uri_set():
    with db.connect() as conn:
        db.upsert_paper(conn, _sample_paper(), collected_at="now")
        assert db.papers_ready_for_search_index(conn) == []
        conn.execute("UPDATE papers SET gcs_uri = ? WHERE paper_id = ?", ("gs://bucket/x.pdf", "arxiv:1234"))
        assert len(db.papers_ready_for_search_index(conn)) == 1
