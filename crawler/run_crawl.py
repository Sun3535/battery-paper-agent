"""크롤러 CLI.

사용법 (Article_Battery/ 루트에서):
    python -m crawler.run_crawl                # 메타데이터 수집 + PDF 다운로드
    python -m crawler.run_crawl --no-download   # 메타데이터만 (PDF는 나중에)
"""

from __future__ import annotations

import argparse
import sys
import time

from . import config, db
from .pdf_fetcher import download_pending
from .relevance import is_relevant
from .sources.arxiv_source import ArxivSource
from .sources.base import utcnow_iso
from .sources.openalex_source import OpenAlexSource
from .sources.semantic_scholar_source import SemanticScholarSource

SOURCES = [ArxivSource(), OpenAlexSource(), SemanticScholarSource()]


def run(download: bool = True) -> None:
    total_new = 0
    with db.connect() as conn:
        for source in SOURCES:
            for kw in config.KEYWORDS:
                started = utcnow_iso()
                new_count = 0
                status = "success"
                try:
                    papers = source.search(
                        kw["query"], config.MAX_RESULTS_PER_KEYWORD, keyword_label=kw["label_ko"]
                    )
                    for paper in papers:
                        if config.RELEVANCE_FILTER and not is_relevant(paper.title, paper.abstract):
                            continue  # 엄격 필터: 배터리 핵심어 없는 논문 스킵
                        if db.upsert_paper(conn, paper, collected_at=started):
                            new_count += 1
                except Exception as e:  # noqa: BLE001 - 한 키워드 실패가 전체 크롤을 막으면 안 됨
                    status = f"failed: {e}"
                    print(f"[crawl] {source.name}/{kw['label_ko']} 실패: {e}", file=sys.stderr)

                finished = utcnow_iso()
                db.record_run(conn, source.name, kw["label_ko"], started, finished, new_count, status)
                total_new += new_count
                print(f"[crawl] {source.name}/{kw['label_ko']}: 신규 {new_count}건 ({status})")
                time.sleep(3)  # 소스 예의 페이싱(특히 Semantic Scholar 익명 레이트리밋 예방)

        if download:
            downloaded = download_pending(conn)
            print(f"[crawl] PDF 다운로드 완료: {downloaded}건 → {config.PDF_DOWNLOAD_DIR}")

    print(f"[crawl] 총 신규 논문 {total_new}건")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 콘솔 한글 깨짐 방지(cp949 환경)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-download", action="store_true", help="메타데이터만 수집, PDF 다운로드 스킵"
    )
    args = parser.parse_args()
    run(download=not args.no_download)
