"""사용자별 Gemini API 키 저장소.

설계 (호야 2026-07-15 지시):
  - 프론트에서 사용자명·비밀번호·API 키를 등록 → 백엔드 SQLite에 저장.
  - 평소 프론트에는 **사용자명만** 노출. 비밀번호·API 키는 절대 목록에 안 나온다.
  - 사용자명 옆 [API] 버튼 → 비밀번호 확인 통과 시에만 API 키 조회/수정.
  - 사용자명 클릭(그 사용자의 키로 번역) → 비밀번호 팝업(도용 방지) → 통과 시 active 지정.
  - 개발자는 DB를 직접 보거나 admin 라우트로 평문 비번을 볼 수 있다(비번찾기 용도).

⚠️ 보안: password/api_key는 **평문** 저장. "개발자 비번찾기" 요구상 불가피.
   localhost 개인/소규모 전용. 공개 배포 절대 금지.
"""

from __future__ import annotations

import sqlite3

from store import utcnow

ACTIVE_KEY = "active_translator_user"


def list_usernames(conn: sqlite3.Connection) -> list[dict]:
    """평소 노출용 — 사용자명 + 키 등록 여부만. 비번·키 값은 절대 반환 안 함."""
    rows = conn.execute(
        "SELECT username, (api_key != '') AS has_key FROM users ORDER BY username"
    ).fetchall()
    return [{"username": r["username"], "has_key": bool(r["has_key"])} for r in rows]


def exists(conn: sqlite3.Connection, username: str) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None


DEFAULT_PREFERRED = "credit"  # 기본 사용 옵션 (호야 지시 2026-07-16)


def create(conn: sqlite3.Connection, username: str, password: str, api_key: str = "") -> None:
    """사용자 생성.

    ⚠️ preferred 는 **명시적으로** 넣는다. ALTER TABLE 의 DEFAULT 는 이미 만들어진 테이블에
    소급 적용되지 않아, 기존 DB에서는 옛 기본값('free')으로 생성되던 버그가 있었다(실측).
    """
    conn.execute(
        "INSERT INTO users (username, password, api_key, created_at, preferred)"
        " VALUES (?, ?, ?, ?, ?)",
        (username, password, api_key, utcnow(), DEFAULT_PREFERRED),
    )


def verify(conn: sqlite3.Connection, username: str, password: str) -> bool:
    row = conn.execute("SELECT password FROM users WHERE username = ?", (username,)).fetchone()
    return bool(row) and row["password"] == password


def get_api_key(conn: sqlite3.Connection, username: str) -> str:
    row = conn.execute("SELECT api_key FROM users WHERE username = ?", (username,)).fetchone()
    return row["api_key"] if row else ""


def set_api_key(conn: sqlite3.Connection, username: str, api_key: str) -> None:
    conn.execute("UPDATE users SET api_key = ? WHERE username = ?", (api_key, username))


# ══════════════════════════════════════════════════════════════════
# 자격증명 3종 (2026-07-16)
#   free   : 무료 AI Studio API 키 (rate limit·데이터 학습 주의)
#   paid   : 유료 AI Studio API 키 (결제 계정 연결)
#   credit : GCP 프로젝트 + 이 PC의 gcloud 인증 → Vertex 경로 (App Builder 크레딧)
# 저장 위치는 이 PC의 SQLite(crawler/papers.db) — 코드 옆 로컬 파일. 외부 전송 없음.
# UI로는 항상 마스킹된 값만 내려가고, 원문은 비밀번호 확인을 통과해야 반환된다.
# ══════════════════════════════════════════════════════════════════
KINDS = ("free", "paid", "credit")
_COL = {"free": "key_free", "paid": "key_paid", "credit": "gcp_project"}


def credit_enabled() -> bool:
    """크레딧(Vertex) 옵션을 쓸지. 사내망 배포처럼 gcloud 로그인이 막힌 환경은 false.

    false 면: UI에서 크레딧 칸이 숨겨지고, 자격증명 후보에서도 완전히 빠진다(시도조차 안 함).
    """
    import os

    return os.getenv("ENABLE_CREDIT", "true").strip().lower() == "true"


def usable_kinds() -> tuple[str, ...]:
    return KINDS if credit_enabled() else ("free", "paid")


def mask(value: str) -> str:
    """UI 표시용 마스킹. 앞 6·뒤 4만 남긴다. 짧으면 전부 가린다."""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 12:
        return "•" * len(v)
    return f"{v[:6]}{'•' * 12}{v[-4:]}"


def get_credentials(conn: sqlite3.Connection, username: str) -> dict:
    """마스킹된 자격증명 상태. 원문은 절대 포함하지 않는다(목록·기본 조회용)."""
    row = conn.execute(
        "SELECT key_free, key_paid, gcp_project, preferred FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if not row:
        return {}
    pref = row["preferred"]
    if pref == "credit" and not credit_enabled():
        pref = "free"  # 크레딧이 꺼진 환경에선 API 키를 기본으로 보여준다
    return {
        "preferred": pref,
        "credit_enabled": credit_enabled(),
        "free": {"set": bool(row["key_free"]), "masked": mask(row["key_free"])},
        "paid": {"set": bool(row["key_paid"]), "masked": mask(row["key_paid"])},
        "credit": {"set": bool(row["gcp_project"]), "masked": row["gcp_project"] or ""},
    }


def get_credential_raw(conn: sqlite3.Connection, username: str, kind: str) -> str:
    """원문 반환 — 비밀번호 확인을 통과한 호출자만 써야 한다(수정란 프리필)."""
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 종류: {kind}")
    row = conn.execute(
        f"SELECT {_COL[kind]} AS v FROM users WHERE username = ?", (username,)
    ).fetchone()
    return row["v"] if row else ""


def set_credential(conn: sqlite3.Connection, username: str, kind: str, value: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 종류: {kind}")
    conn.execute(
        f"UPDATE users SET {_COL[kind]} = ? WHERE username = ?", ((value or "").strip(), username)
    )
    # 레거시 단일 컬럼도 동기화 (기존 코드 경로 호환)
    if kind in ("free", "paid"):
        conn.execute(
            "UPDATE users SET api_key = COALESCE(NULLIF(key_paid,''), key_free) WHERE username = ?",
            (username,),
        )


def set_preferred(conn: sqlite3.Connection, username: str, kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 종류: {kind}")
    if kind == "credit" and not credit_enabled():
        raise ValueError("이 환경에서는 크레딧 옵션이 비활성화되어 있습니다 (ENABLE_CREDIT=false).")
    conn.execute("UPDATE users SET preferred = ? WHERE username = ?", (kind, username))


def active_credential(conn: sqlite3.Connection) -> dict:
    """활성 사용자가 고른 자격증명. 호출 채널 결정에 쓴다.

    반환: {"kind": free|paid|credit|None, "key": str, "project": str}
    - free/paid → AI Studio 키로 호출(aistudio 채널)
    - credit    → gcloud 인증 + 프로젝트로 Vertex 호출(vertex 채널)
    """
    u = get_active(conn)
    if not u:
        return {"kind": None, "key": "", "project": ""}
    row = conn.execute(
        "SELECT key_free, key_paid, gcp_project, preferred FROM users WHERE username = ?", (u,)
    ).fetchone()
    if not row:
        return {"kind": None, "key": "", "project": ""}

    kind = row["preferred"] or "credit"
    if kind == "credit" and not credit_enabled():
        kind = "free"  # 크레딧이 꺼진 환경 → API 키로 대체
    if kind == "credit":
        return {"kind": "credit", "key": "", "project": row["gcp_project"] or ""}
    key = row["key_paid"] if kind == "paid" else row["key_free"]
    return {"kind": kind, "key": key or "", "project": ""}


def delete(conn: sqlite3.Connection, username: str) -> None:
    conn.execute("DELETE FROM users WHERE username = ?", (username,))
    # active 사용자였다면 해제
    if get_active(conn) == username:
        set_active(conn, None)


# ── active 사용자 (번역에 쓸 키의 주인) ─────────────────────────────
def set_active(conn: sqlite3.Connection, username: str | None) -> None:
    if username is None:
        conn.execute("DELETE FROM app_state WHERE key = ?", (ACTIVE_KEY,))
    else:
        conn.execute(
            "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (ACTIVE_KEY, username)
        )


def get_active(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (ACTIVE_KEY,)).fetchone()
    return row["value"] if row else None


def credential_chain(conn: sqlite3.Connection) -> list[dict]:
    """시도 순서대로 정렬된 자격증명 후보.

    조건1(유료/무료 혼용 무관) + 조건2(Vertex 없는 사용자 대비):
      ① 사용자가 고른 슬롯  ② 나머지 API 키 슬롯  ③ 크레딧(Vertex)
    API 키 두 칸은 코드상 완전히 동일하게 취급된다 — 라벨은 사용자 메모일 뿐이다.
    """
    u = get_active(conn)
    if not u:
        return []
    row = conn.execute(
        "SELECT key_free, key_paid, gcp_project, preferred FROM users WHERE username = ?", (u,)
    ).fetchone()
    if not row:
        return []

    slots = {
        "free": {"kind": "free", "key": row["key_free"] or "", "project": ""},
        "paid": {"kind": "paid", "key": row["key_paid"] or "", "project": ""},
        "credit": {"kind": "credit", "key": "", "project": row["gcp_project"] or ""},
    }
    kinds = usable_kinds()  # 크레딧이 꺼져 있으면 후보에서 아예 제외
    pref = row["preferred"] or "credit"
    if pref not in kinds:
        pref = kinds[0]
    order = [pref] + [k for k in kinds if k != pref]

    chain = []
    for k in order:
        s = slots[k]
        if (s["kind"] == "credit" and s["project"]) or (s["kind"] != "credit" and s["key"]):
            chain.append(s)
    return chain


def active_api_key(conn: sqlite3.Connection) -> str | None:
    """번역/그림분석이 쓸 API 키. 고른 칸이 비었으면 다른 API 키 칸으로 폴백한다."""
    for c in credential_chain(conn):
        if c["kind"] in ("free", "paid") and c["key"]:
            return c["key"]
    return None


# ── 개발자 전용 (비번찾기) ──────────────────────────────────────────
def raw_all(conn: sqlite3.Connection) -> list[dict]:
    """평문 전체 — admin 라우트에서만 호출. 절대 일반 API로 노출 금지."""
    rows = conn.execute(
        "SELECT username, password, api_key, created_at FROM users ORDER BY username"
    ).fetchall()
    return [dict(r) for r in rows]
