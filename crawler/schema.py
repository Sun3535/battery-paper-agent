"""배터리 논문 크롤러 — 데이터 스키마.

Layer 1(무료): arXiv/Semantic Scholar API로 신규 논문 메타데이터를 모아 SQLite에
적재한다. paper_id가 PK라 소스가 달라도(arxiv/s2) 같은 논문 중복 저장은 안 막지만,
같은 소스 내 재수집은 dedup된다 (paper_id 정규화는 각 source 모듈이 담당).
rag/ 단계가 이 DB를 읽어 GCS 업로드·색인 대상을 고른다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Paper:
    paper_id: str  # "arxiv:2401.01234" / "s2:<paperId>"
    source: str  # "arxiv" | "semantic_scholar"
    title: str
    authors: list[str]
    abstract: str
    published_date: Optional[str]  # ISO "YYYY-MM-DD", 모르면 None
    keyword_matched: str  # 이 논문을 찾아낸 검색 키워드(config.KEYWORDS 중 label_ko)
    pdf_url: Optional[str]
    doi: Optional[str] = None
    raw_metadata: dict = field(default_factory=dict)


DDL = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,          -- JSON array
    abstract TEXT,
    published_date TEXT,
    keyword_matched TEXT,
    pdf_url TEXT,
    doi TEXT,
    local_pdf_path TEXT,
    pdf_sha256 TEXT,
    gcs_uri TEXT,
    ingested_to_search INTEGER NOT NULL DEFAULT 0,
    collected_at TEXT NOT NULL,
    raw_metadata TEXT               -- JSON blob, 원본 API 응답 보존 (디버그/재처리용)
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source TEXT NOT NULL,
    keyword TEXT NOT NULL,
    new_papers_found INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running'  -- running|success|failed: <이유>
);
"""
