"""웹앱 저장소 — 문서/블록/번역 캐시/참고문헌.

crawler/papers.db 와 같은 SQLite 파일을 쓰되 테이블을 분리한다(크롤러 데이터와 공존).
번역은 반드시 캐시한다 — 같은 블록을 두 번 번역하면 그만큼 API 비용이 또 나간다.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent.parent  # Article_Battery/

# ══════════════════════════════════════════════════════════════════
# 라이브러리 저장 위치 (사용자가 바꿀 수 있다)
#
# 기본값은 **기존 경로 그대로** 둔다 — 이미 쌓인 논문을 옮기지 않기 위해서다
# (DB는 크롤러와 공유하는 crawler/papers.db, 파일은 webapp/data/).
# 사용자가 다른 폴더를 지정하면 그 폴더 안에 {papers.db, uploads/, images/} 를 만들어
# **독립된 라이브러리**로 쓴다. 경로는 아래 설정 파일에 기록된다(코드 옆, 로컬).
# ══════════════════════════════════════════════════════════════════
CONFIG_PATH = PROJECT_ROOT / "webapp" / "library_config.json"

DEFAULT_DB_PATH = PROJECT_ROOT / "crawler" / "papers.db"
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "webapp" / "data" / "uploads"
DEFAULT_IMAGES_DIR = PROJECT_ROOT / "webapp" / "data" / "images"


def _apply_root(root: Path | None) -> None:
    """전역 경로를 다시 세팅. root=None 이면 기본(기존) 경로."""
    global LIBRARY_ROOT, DB_PATH, UPLOAD_DIR, IMAGES_DIR
    if root is None:
        LIBRARY_ROOT = None
        DB_PATH, UPLOAD_DIR, IMAGES_DIR = DEFAULT_DB_PATH, DEFAULT_UPLOAD_DIR, DEFAULT_IMAGES_DIR
    else:
        LIBRARY_ROOT = Path(root)
        DB_PATH = LIBRARY_ROOT / "papers.db"
        UPLOAD_DIR = LIBRARY_ROOT / "uploads"
        IMAGES_DIR = LIBRARY_ROOT / "images"


def load_library_root() -> Path | None:
    """설정 파일에서 사용자가 지정한 경로를 읽는다. 없으면 None(기본 경로)."""
    try:
        if CONFIG_PATH.exists():
            v = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("library_root")
            return Path(v) if v else None
    except Exception:
        pass
    return None


def save_library_root(root: Path | None) -> None:
    """경로를 설정 파일에 기록하고 즉시 적용한다."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"library_root": str(root) if root else None}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _apply_root(root)


def current_paths() -> dict:
    return {
        "library_root": str(LIBRARY_ROOT) if LIBRARY_ROOT else None,
        "is_default": LIBRARY_ROOT is None,
        "db": str(DB_PATH),
        "uploads": str(UPLOAD_DIR),
        "images": str(IMAGES_DIR),
        "default_root": str(DEFAULT_UPLOAD_DIR.parent),
    }


LIBRARY_ROOT: Path | None = None
DB_PATH = DEFAULT_DB_PATH
UPLOAD_DIR = DEFAULT_UPLOAD_DIR
IMAGES_DIR = DEFAULT_IMAGES_DIR
_apply_root(load_library_root())  # 저장된 설정이 있으면 시작할 때 적용

DDL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'upload',   -- upload | crawl
    paper_id TEXT,                           -- crawler.papers.paper_id (있으면)
    page_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|extracting|translating|indexing|ready|failed
    error TEXT,
    progress INTEGER NOT NULL DEFAULT 0,     -- 0~100
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
    doc_id TEXT NOT NULL,
    block_order INTEGER NOT NULL,
    kind TEXT NOT NULL,          -- text | image | table
    page INTEGER NOT NULL,
    bbox TEXT NOT NULL,          -- JSON [x0,y0,x1,y1]
    text_en TEXT DEFAULT '',
    image_path TEXT,
    table_rows TEXT,             -- JSON
    is_caption INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (doc_id, block_order)
);

CREATE TABLE IF NOT EXISTS translations (
    doc_id TEXT NOT NULL,
    block_order INTEGER NOT NULL,
    text_ko TEXT NOT NULL,
    model TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (doc_id, block_order)
);

CREATE TABLE IF NOT EXISTS refs (
    doc_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    raw TEXT NOT NULL,
    PRIMARY KEY (doc_id, idx)
);

-- 사용자별 Gemini API 키 보관 (webapp/backend/users.py 참고).
-- ⚠️ password/api_key는 평문 저장 — "개발자 비번찾기" 요구를 위해 의도적. localhost 전용.
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password TEXT NOT NULL,
    api_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migrate(conn: sqlite3.Connection) -> None:
    """기존 DB 스키마 확장 (파괴적 변경 없이 컬럼만 추가)."""
    # 업로드 시 번역/그림분석 선택 체크박스 (2026-07-16)
    for col in ("opt_translate", "opt_analyze"):
        try:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # 이미 있음

    # 자격증명 3종 슬롯: 유료키 / 무료키 / 크레딧(GCP 프로젝트) (2026-07-16)
    for col, default in (
        ("key_paid", "''"),
        ("key_free", "''"),
        ("gcp_project", "''"),
        # 기본 사용 옵션 (호야 지시 2026-07-16): 크레딧 우선.
        # 크레딧 칸이 비어 있으면 credential_chain 이 자동으로 API 키로 넘어가므로 안전하다.
        ("preferred", "'credit'"),  # free | paid | credit
    ):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
        except sqlite3.OperationalError:
            pass
    # 기존 단일 api_key → ①칸 이관. **반드시 한 번만** 실행한다.
    # (매 연결마다 돌면 ②칸에 저장한 키가 ①칸으로 복사되고, ①칸을 지워도 되살아난다 — 실측 버그)
    try:
        done = conn.execute(
            "SELECT 1 FROM app_state WHERE key = 'migrated_api_key_to_slots'"
        ).fetchone()
        if not done:
            conn.execute(
                "UPDATE users SET key_free = api_key WHERE key_free = '' AND api_key != ''"
            )
            conn.execute(
                "INSERT OR REPLACE INTO app_state (key, value) VALUES ('migrated_api_key_to_slots','1')"
            )
    except sqlite3.OperationalError:
        pass


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(DDL)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_document(
    conn,
    doc_id: str,
    title: str,
    filename: str,
    pdf_path: Path,
    opt_translate: bool = False,
    opt_analyze: bool = False,
) -> None:
    conn.execute(
        """INSERT INTO documents
           (doc_id, title, filename, pdf_path, source, status, created_at, opt_translate, opt_analyze)
           VALUES (?, ?, ?, ?, 'upload', 'pending', ?, ?, ?)""",
        (doc_id, title, filename, str(pdf_path), utcnow(), int(opt_translate), int(opt_analyze)),
    )


def set_status(conn, doc_id: str, status: str, progress: int | None = None, error: str | None = None) -> None:
    if progress is None:
        conn.execute("UPDATE documents SET status=?, error=? WHERE doc_id=?", (status, error, doc_id))
    else:
        conn.execute(
            "UPDATE documents SET status=?, progress=?, error=? WHERE doc_id=?",
            (status, progress, error, doc_id),
        )


def save_blocks(conn, doc_id: str, blocks: list[dict], page_count: int) -> None:
    conn.execute("DELETE FROM blocks WHERE doc_id=?", (doc_id,))
    conn.executemany(
        """INSERT INTO blocks (doc_id, block_order, kind, page, bbox, text_en, image_path, table_rows, is_caption)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                doc_id,
                b["order"],
                b["kind"],
                b["page"],
                json.dumps(b["bbox"]),
                b.get("text", ""),
                b.get("image_path"),
                json.dumps(b["table_rows"], ensure_ascii=False) if b.get("table_rows") else None,
                1 if b.get("is_caption") else 0,
            )
            for b in blocks
        ],
    )
    conn.execute("UPDATE documents SET page_count=? WHERE doc_id=?", (page_count, doc_id))


def save_translations(conn, doc_id: str, mapping: dict[int, str], model: str) -> None:
    ts = utcnow()
    conn.executemany(
        """INSERT OR REPLACE INTO translations (doc_id, block_order, text_ko, model, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        [(doc_id, order, ko, model, ts) for order, ko in mapping.items()],
    )


def untranslated_blocks(conn, doc_id: str) -> list[dict]:
    """아직 번역 안 된 블록만 반환 — 캐시 히트분은 재번역하지 않는다(비용 절감)."""
    rows = conn.execute(
        """SELECT b.block_order, b.text_en FROM blocks b
           LEFT JOIN translations t ON t.doc_id=b.doc_id AND t.block_order=b.block_order
           WHERE b.doc_id=? AND t.block_order IS NULL AND b.text_en != ''""",
        (doc_id,),
    ).fetchall()
    return [{"order": r["block_order"], "text": r["text_en"]} for r in rows]


def save_refs(conn, doc_id: str, refs: list[str]) -> None:
    conn.execute("DELETE FROM refs WHERE doc_id=?", (doc_id,))
    conn.executemany(
        "INSERT INTO refs (doc_id, idx, raw) VALUES (?, ?, ?)",
        [(doc_id, i, r) for i, r in enumerate(refs, 1)],
    )


def get_document(conn, doc_id: str):
    return conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()


def list_documents(conn) -> list:
    return conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()


def get_blocks(conn, doc_id: str) -> list[dict]:
    """리더용 블록 + 번역문 + 그림 AI 분석(있으면) 조인."""
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS figure_analyses ("
        " doc_id TEXT NOT NULL, block_order INTEGER NOT NULL, analysis_ko TEXT NOT NULL,"
        " model TEXT, created_at TEXT NOT NULL, PRIMARY KEY (doc_id, block_order));"
    )
    rows = conn.execute(
        """SELECT b.*, t.text_ko, fa.analysis_ko FROM blocks b
           LEFT JOIN translations t ON t.doc_id=b.doc_id AND t.block_order=b.block_order
           LEFT JOIN figure_analyses fa ON fa.doc_id=b.doc_id AND fa.block_order=b.block_order
           WHERE b.doc_id=? ORDER BY b.block_order""",
        (doc_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "order": r["block_order"],
                "kind": r["kind"],
                "page": r["page"],
                "bbox": json.loads(r["bbox"]),
                "text_en": r["text_en"] or "",
                "text_ko": r["text_ko"] or "",
                "image_path": r["image_path"],
                "table_rows": json.loads(r["table_rows"]) if r["table_rows"] else None,
                "is_caption": bool(r["is_caption"]),
                "analysis_ko": r["analysis_ko"] or "",
            }
        )
    # 캡션 없는 그림에 남는 캡션을 짝지어 준다(같은 쪽 → 다음 쪽 맨 위). 저장된 블록은 그대로 둔다.
    import captions

    return captions.pair_for_reader(out)


def get_refs(conn, doc_id: str) -> list[dict]:
    rows = conn.execute("SELECT idx, raw FROM refs WHERE doc_id=? ORDER BY idx", (doc_id,)).fetchall()
    return [{"idx": r["idx"], "raw": r["raw"]} for r in rows]


# ══════════════════════════════════════════════════════════════════
# 유료 산출물 현황 — "이 논문은 번역까지 됐나? 그림분석까지 됐나?"
#
# 화면의 '완료' 하나로는 둘 중 무엇이 끝났는지 알 수 없어, 사용자가 이미 돈을 낸
# 논문에 또 결제 버튼을 누를 위험이 있었다(2026-07-28 호야 지적).
# 카드 배지와 버튼 잠금이 **같은 집계**를 쓰도록 여기서 한 번에 계산한다.
# ══════════════════════════════════════════════════════════════════
def ensure_figure_table(conn) -> None:
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS figure_analyses ("
        " doc_id TEXT NOT NULL, block_order INTEGER NOT NULL, analysis_ko TEXT NOT NULL,"
        " model TEXT, created_at TEXT NOT NULL, PRIMARY KEY (doc_id, block_order));"
    )


def paid_status_map(conn) -> dict[str, dict]:
    """문서별 {번역/그림분석} 진행 현황. 전부 로컬 집계 — 비용 0."""
    ensure_figure_table(conn)

    text_total = {
        r["doc_id"]: r["n"]
        for r in conn.execute(
            "SELECT doc_id, COUNT(*) n FROM blocks WHERE text_en != '' GROUP BY doc_id"
        )
    }
    text_done = {
        r["doc_id"]: r["n"]
        for r in conn.execute("SELECT doc_id, COUNT(*) n FROM translations GROUP BY doc_id")
    }
    fig_total = {
        r["doc_id"]: r["n"]
        for r in conn.execute(
            "SELECT doc_id, COUNT(*) n FROM blocks WHERE image_path IS NOT NULL GROUP BY doc_id"
        )
    }
    fig_done = {
        r["doc_id"]: r["n"]
        for r in conn.execute("SELECT doc_id, COUNT(*) n FROM figure_analyses GROUP BY doc_id")
    }

    out: dict[str, dict] = {}
    for r in conn.execute("SELECT doc_id FROM documents"):
        d = r["doc_id"]
        tt, td = text_total.get(d, 0), text_done.get(d, 0)
        ft, fd = fig_total.get(d, 0), fig_done.get(d, 0)
        out[d] = {
            "text_blocks": tt,
            "translated_blocks": td,
            # 부분 번역도 '돈을 낸' 상태다 — 재실행 판단은 UI가 아니라 여기 숫자로 한다
            "translated": td > 0,
            "translate_complete": tt > 0 and td >= tt,
            "figure_blocks": ft,
            "analyzed_figures": fd,
            "analyzed": fd > 0,
            "analyze_complete": ft > 0 and fd >= ft,
        }
    return out


# ── 앱 설정값 (유료 API 스위치 등) ────────────────────────────────
PAID_STATE_KEY = "paid_apis_enabled"


def get_state(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM app_state WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (key, value)
        )
