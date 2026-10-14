"""arXiv 검색 — 완전 무료, API 키 불요. http://export.arxiv.org/api/query (Atom XML)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from .. import config
from ..schema import Paper
from .base import PaperSource

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
API_URL = "http://export.arxiv.org/api/query"


class ArxivSource(PaperSource):
    name = "arxiv"

    def search(self, query: str, max_results: int, keyword_label: str = "") -> list[Paper]:
        category_filter = " OR ".join(f"cat:{c}" for c in config.ARXIV_CATEGORIES)
        search_query = f"({category_filter}) AND all:{query}"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = requests.get(API_URL, params=params, timeout=config.REQUEST_TIMEOUT_SEC)
        resp.raise_for_status()
        return self._parse(resp.text, keyword_label)

    def _parse(self, xml_text: str, keyword_label: str) -> list[Paper]:
        root = ET.fromstring(xml_text)
        papers: list[Paper] = []
        for entry in root.findall(f"{ATOM_NS}entry"):
            arxiv_id_full = entry.findtext(f"{ATOM_NS}id", default="") or ""
            arxiv_id = arxiv_id_full.rsplit("/", 1)[-1]  # "2401.01234v2"
            arxiv_id_bare = arxiv_id.split("v")[0]
            if not arxiv_id_bare:
                continue

            title = (entry.findtext(f"{ATOM_NS}title", default="") or "").strip().replace("\n", " ")
            abstract = (entry.findtext(f"{ATOM_NS}summary", default="") or "").strip().replace("\n", " ")
            published = entry.findtext(f"{ATOM_NS}published", default="") or ""
            published_date = published[:10] if published else None
            authors = [
                (a.findtext(f"{ATOM_NS}name", default="") or "").strip()
                for a in entry.findall(f"{ATOM_NS}author")
            ]

            pdf_url = None
            for link in entry.findall(f"{ATOM_NS}link"):
                if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                    pdf_url = link.get("href")
                    break

            doi = entry.findtext(f"{ARXIV_NS}doi", default=None)

            papers.append(
                Paper(
                    paper_id=f"arxiv:{arxiv_id_bare}",
                    source=self.name,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    published_date=published_date,
                    keyword_matched=keyword_label,
                    pdf_url=pdf_url,
                    doi=doi,
                    raw_metadata={"arxiv_id": arxiv_id, "entry_id": arxiv_id_full},
                )
            )
        return papers
