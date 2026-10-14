"""오픈액세스 PDF 다운로드 → Article_Battery/input/ (기존 01_extract.py가 그대로 집어감)."""

from __future__ import annotations

import hashlib
import re
import sqlite3

import requests

from . import config, db


def _safe_filename(paper_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", paper_id) + ".pdf"


def download_pending(conn: sqlite3.Connection) -> int:
    """local_pdf_path가 비어있는 논문들의 PDF를 내려받는다. 성공 개수 반환.

    개별 실패(404/타임아웃/PDF 아닌 랜딩페이지 등)는 조용히 스킵하고 다음 크롤 런에서
    자동 재시도된다 (local_pdf_path가 NULL인 채로 남으므로).
    """
    config.PDF_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for row in db.papers_without_pdf(conn):
        dest = config.PDF_DOWNLOAD_DIR / _safe_filename(row["paper_id"])
        try:
            resp = requests.get(row["pdf_url"], timeout=config.REQUEST_TIMEOUT_SEC)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type and not resp.content.startswith(b"%PDF"):
                continue  # 오픈액세스 링크가 PDF가 아닌 랜딩페이지인 경우
            dest.write_bytes(resp.content)
            sha256 = hashlib.sha256(resp.content).hexdigest()
            db.set_pdf_downloaded(conn, row["paper_id"], str(dest), sha256)
            downloaded += 1
        except Exception:
            continue
    return downloaded
