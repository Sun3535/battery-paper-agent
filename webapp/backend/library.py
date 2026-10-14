"""라이브러리 표시용 — 진짜 논문 제목 + 표지 이미지.

문제(2026-07-28 호야 지적): 카드에 파일명(`oa_W7169633968`)만 떠서 91편 중 원하는 논문을
찾을 수가 없었다. E-book 서가처럼 **제목과 표지**가 보여야 한다.

제목 출처(우선순위):
  ① 크롤러 DB(papers.title) — 크롤링해 온 논문은 정식 제목을 이미 알고 있다
  ② PDF 첫 텍스트 블록 — 직접 업로드한 PDF는 보통 첫 블록이 제목
  ③ 파일명 — 위 둘 다 실패했을 때

표지: PDF **1페이지를 그대로 렌더**한다. 책 표지처럼 보이고, 그림이 없는 논문에도 항상 있다.
전부 로컬 처리 — 네트워크·비용 0.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

COVER_NAME = "_cover.png"
COVER_ZOOM = 0.9  # 카드 썸네일 크기 — 너무 크면 디스크·전송만 낭비
MIN_TITLE_LEN = 12
MAX_TITLE_LEN = 200

# 제목이 아닌 첫 블록들 (arXiv 스탬프, 저널 헤더 등)
_NOT_TITLE = re.compile(
    r"^\s*(arxiv:|doi:|https?://|www\.|submitted|accepted|received|preprint|"
    r"vol\.|volume\s|issn|isbn|copyright|©|\d{4}\s*$)",
    re.IGNORECASE,
)


def _demath(inner: str) -> str:
    """$…$ 안쪽만 평문으로: _{0.5} → 0.5, ^{+} → +, _2 → 2"""
    inner = re.sub(r"[_^]\{([^{}]*)\}", r"\1", inner)
    inner = re.sub(r"[_^]([A-Za-z0-9+\-])", r"\1", inner)
    return inner


def clean_title(raw: str) -> str:
    """공백 정리 + LaTeX 잔재 제거.

    크롤러가 가져온 제목에는 수식 표기가 그대로 남아 있다
    (예: `Na$_{0.5}$CoO$_2` → `Na0.5CoO2`). 화면에 그대로 뜨면 읽기 어렵다.
    """
    t = raw or ""
    # ① \textit{...} 같은 명령을 먼저 벗긴다
    t = re.sub(r"\\[A-Za-z]+\s*\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\[A-Za-z]+\s*", "", t)  # 인자 없는 명령(\alpha 등)
    # ② 첨자 제거는 **$…$ 수식 구간 안에서만** 한다.
    #    바깥까지 손대면 `oa_W123` 같은 파일명·식별자의 밑줄까지 지워진다(실측 회귀).
    #    닫는 $ 가 없는 경우(`CoO$_2` 로 끝나는 제목)도 함께 처리된다.
    t = re.sub(r"\$([^$]*)\$?", lambda m: _demath(m.group(1)), t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^\W+|\W+$", "", t)  # 앞뒤 기호 제거
    return t[:MAX_TITLE_LEN]


def title_from_crawler(conn: sqlite3.Connection, filename: str) -> str | None:
    """크롤러가 받아온 논문이면 정식 제목을 그대로 쓴다 (파일명으로 매칭)."""
    try:
        rows = conn.execute(
            "SELECT title, local_pdf_path FROM papers WHERE local_pdf_path IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    for r in rows:
        if os.path.basename(r["local_pdf_path"]) == filename:
            t = clean_title(r["title"])
            return t or None
    return None


def title_from_blocks(conn: sqlite3.Connection, doc_id: str) -> str | None:
    """PDF 앞부분 텍스트 블록에서 제목처럼 보이는 첫 줄을 고른다."""
    rows = conn.execute(
        "SELECT text_en FROM blocks WHERE doc_id=? AND kind='text' AND text_en != ''"
        " ORDER BY block_order LIMIT 8",
        (doc_id,),
    ).fetchall()
    for r in rows:
        t = clean_title(r["text_en"])
        if len(t) < MIN_TITLE_LEN or _NOT_TITLE.match(t):
            continue
        if t.count(" ") < 2:  # 단어 2개 미만이면 제목이 아닐 가능성이 높다
            continue
        return t
    return None


def resolve_title(conn: sqlite3.Connection, doc_id: str, filename: str, fallback: str) -> str:
    return (
        title_from_crawler(conn, filename)
        or title_from_blocks(conn, doc_id)
        or clean_title(fallback)
        or filename
    )


def make_cover(pdf_path: Path, images_dir: Path) -> bool:
    """PDF 1페이지를 표지 PNG로 렌더. 이미 있으면 건너뛴다."""
    import fitz

    out = images_dir / COVER_NAME
    if out.exists():
        return True
    try:
        doc = fitz.open(str(pdf_path))
        if doc.page_count == 0:
            doc.close()
            return False
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(COVER_ZOOM, COVER_ZOOM))
        out.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out))
        doc.close()
        return True
    except Exception:
        return False


def backfill(conn: sqlite3.Connection, images_root: Path) -> tuple[int, int]:
    """기존 문서들의 제목·표지를 채운다 (전부 로컬, 비용 0). (제목갱신수, 표지생성수)"""
    titled = covered = 0
    rows = conn.execute("SELECT doc_id, title, filename, pdf_path FROM documents").fetchall()
    for r in rows:
        good = resolve_title(conn, r["doc_id"], r["filename"], r["title"])
        if good and good != r["title"]:
            conn.execute(
                "UPDATE documents SET title = ? WHERE doc_id = ?", (good, r["doc_id"])
            )
            titled += 1
        if make_cover(Path(r["pdf_path"]), images_root / r["doc_id"]):
            covered += 1
    return titled, covered
