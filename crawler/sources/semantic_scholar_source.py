"""Semantic Scholar 검색 — 무료(키 없이도 동작하나 레이트리밋 낮음).

https://api.semanticscholar.org/graph/v1/paper/search
키 없이: 100회/5분. 무료 키 신청 시 5000회/5분로 상승
(https://www.semanticscholar.org/product/api) → .env의 SEMANTIC_SCHOLAR_API_KEY.
"""

from __future__ import annotations

import os

import requests

from .. import config
from ..schema import Paper
from .base import PaperSource

API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,authors,publicationDate,externalIds,openAccessPdf"


class SemanticScholarSource(PaperSource):
    name = "semantic_scholar"

    def __init__(self) -> None:
        self.api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

    def search(self, query: str, max_results: int, keyword_label: str = "") -> list[Paper]:
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        params = {"query": query, "fields": FIELDS, "limit": max_results}
        resp = requests.get(
            API_URL, params=params, headers=headers, timeout=config.REQUEST_TIMEOUT_SEC
        )
        if resp.status_code == 429:
            # 익명 호출은 레이트리밋에 잘 걸림 — 크롤 런 전체를 죽이지 않고 빈 결과만 반환
            return []
        resp.raise_for_status()
        data = resp.json()

        papers: list[Paper] = []
        for item in data.get("data", []):
            paper_id = item.get("paperId")
            title = item.get("title")
            if not paper_id or not title:
                continue
            ext = item.get("externalIds") or {}
            oa = item.get("openAccessPdf") or {}
            papers.append(
                Paper(
                    paper_id=f"s2:{paper_id}",
                    source=self.name,
                    title=title,
                    authors=[a.get("name", "") for a in (item.get("authors") or [])],
                    abstract=item.get("abstract") or "",
                    published_date=item.get("publicationDate"),
                    keyword_matched=keyword_label,
                    pdf_url=oa.get("url"),
                    doi=ext.get("DOI"),
                    raw_metadata=item,
                )
            )
        return papers
