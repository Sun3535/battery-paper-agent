"""OpenAlex 검색 — 무료, API 키 불요. Google Scholar의 실질적 대체재.

https://api.openalex.org/works
- 2.5억 편 메타데이터, 오픈액세스 필터·PDF 직링크(best_oa_location) 제공.
- Google Scholar는 공식 API가 없고 스크래핑은 차단/약관위반이라 OpenAlex를 쓴다.
- mailto 파라미터를 붙이면 "polite pool"로 분류되어 레이트리밋이 후해진다.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

from .. import config
from ..schema import Paper
from .base import PaperSource

API_URL = "https://api.openalex.org/works"
# polite pool 용 연락처(인증 아님). 공개 저장소라 개인 이메일을 넣지 않고 .env 의 OPENALEX_MAILTO 로 받는다
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")   # 이미 있는 환경 변수는 덮어쓰지 않는다
except ImportError:
    pass
MAILTO = os.environ.get("OPENALEX_MAILTO", "").strip()


def _reconstruct_abstract(inverted: dict | None) -> str:
    """OpenAlex는 초록을 inverted index({단어: [위치...]})로 준다 → 원문 복원."""
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    return " ".join(w for _, w in sorted(positions))


class OpenAlexSource(PaperSource):
    name = "openalex"

    def search(self, query: str, max_results: int, keyword_label: str = "") -> list[Paper]:
        params = {
            "search": query,
            "filter": "open_access.is_oa:true",  # 오픈액세스만 (PDF 자동 다운로드 전제)
            "sort": "publication_date:desc",
            "per-page": min(max_results, 50),
        }
        if MAILTO:
            params["mailto"] = MAILTO
        resp = requests.get(API_URL, params=params, timeout=config.REQUEST_TIMEOUT_SEC)
        if resp.status_code == 429:
            return []  # 레이트리밋 — 크롤 런 전체를 죽이지 않는다 (semantic_scholar와 동일 방침)
        resp.raise_for_status()
        data = resp.json()

        papers: list[Paper] = []
        for w in data.get("results", []):
            wid = (w.get("id") or "").rsplit("/", 1)[-1]  # "W4281..." 형태
            title = w.get("title")
            if not wid or not title:
                continue
            loc = w.get("best_oa_location") or {}
            doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
            authors = [
                (a.get("author") or {}).get("display_name", "")
                for a in (w.get("authorships") or [])[:20]
            ]
            papers.append(
                Paper(
                    paper_id=f"oa:{wid}",
                    source=self.name,
                    title=title,
                    authors=[a for a in authors if a],
                    abstract=_reconstruct_abstract(w.get("abstract_inverted_index")),
                    published_date=w.get("publication_date"),
                    keyword_matched=keyword_label,
                    pdf_url=loc.get("pdf_url"),
                    doi=doi,
                    raw_metadata={"openalex_id": w.get("id"), "oa_status": (w.get("open_access") or {}).get("oa_status")},
                )
            )
        return papers
