"""SQLite 저장소 — dedup은 paper_id PRIMARY KEY 존재 여부로 판단(재수집해도 중복 저장 안 됨)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from . import config
from .schema import DDL, Paper


@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(DDL)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_paper(conn: sqlite3.Connection, paper: Paper, collected_at: str) -> bool:
    """새 논문이면 INSERT하고 True, 이미 있으면 아무것도 안 하고 False."""
    cur = conn.execute("SELECT 1 FROM papers WHERE paper_id = ?", (paper.paper_id,))
    if cur.fetchone():
        return False
    conn.execute(
        """
        INSERT INTO papers (
            paper_id, source, title, authors, abstract, published_date,
            keyword_matched, pdf_url, doi, collected_at, raw_metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper.paper_id,
            paper.source,
            paper.title,
            json.dumps(paper.authors, ensure_ascii=False),
            paper.abstract,
            paper.published_date,
            paper.keyword_matched,
            paper.pdf_url,
            paper.doi,
            collected_at,
            json.dumps(paper.raw_metadata, ensure_ascii=False, default=str),
        ),
    )
    return True


def record_run(
    conn: sqlite3.Connection,
    source: str,
    keyword: str,
    started_at: str,
    finished_at: str,
    new_papers_found: int,
    status: str,
) -> None:
    conn.execute(
        """INSERT INTO crawl_runs (started_at, finished_at, source, keyword, new_papers_found, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (started_at, finished_at, source, keyword, new_papers_found, status),
    )


def set_pdf_downloaded(conn: sqlite3.Connection, paper_id: str, local_path: str, sha256: str) -> None:
    conn.execute(
        "UPDATE papers SET local_pdf_path = ?, pdf_sha256 = ? WHERE paper_id = ?",
        (local_path, sha256, paper_id),
    )


def papers_without_pdf(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM papers WHERE pdf_url IS NOT NULL AND local_pdf_path IS NULL"
    )
    return cur.fetchall()


def papers_ready_for_search_index(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """gcs_uri는 있고 아직 ingested_to_search=0인 논문 — rag/ 단계가 이 목록을 소비."""
    cur = conn.execute(
        "SELECT * FROM papers WHERE gcs_uri IS NOT NULL AND ingested_to_search = 0"
    )
    return cur.fetchall()
