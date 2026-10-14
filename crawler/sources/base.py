"""논문 소스 공통 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from ..schema import Paper


class PaperSource(ABC):
    name: str

    @abstractmethod
    def search(self, query: str, max_results: int, keyword_label: str = "") -> list[Paper]:
        """키워드로 검색해 Paper 목록 반환.

        네트워크/파싱 실패 시 예외를 던진다 — 호출부(run_crawl)가 키워드 단위로 잡아서
        한 키워드 실패가 전체 크롤을 중단시키지 않게 한다.
        """
        raise NotImplementedError


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
