"""챗봇 대화 기억 (맞춤형 스킬).

사용자가 던진 질문 = 그 사람이 궁금해하는 지점. 다음 논문에서도 비슷한 걸 묻는다.
그래서 Q&A를 압축 저장해두고, 새 질문이 오면 **관련된 과거 Q&A만 골라** 프롬프트에 얹는다.
챗봇이 "이 사용자는 이런 걸 이렇게 물어봤고 이런 답이 맞았다"를 참고하므로 오답률이 준다.

비용 설계 (핵심):
  - **저장·압축: 0원.** LLM 요약을 쓰지 않는다(매 대화마다 과금되면 배보다 배꼽).
    규칙 기반으로 답변의 핵심 문장만 남겨 ~MAX_ANSWER_CHARS 로 줄인다.
  - **검색: 0원.** SQLite FTS5(trigram)로 관련 기억만 뽑는다. 임베딩 API 안 씀.
  - **과금되는 곳은 딱 하나** — 뽑은 기억 2~3개를 프롬프트에 넣는 입력 토큰뿐.
    그래서 주입 개수(MEMORY_TOP_K)와 길이를 좁게 묶어두고, 스위치로 끌 수 있게 했다.
"""

from __future__ import annotations

import re
import sqlite3

from store import utcnow

MAX_ANSWER_CHARS = 260  # 저장할 답변 압축 상한 (주입 비용의 대부분을 좌우)
MAX_QUESTION_CHARS = 120
DEFAULT_TOP_K = 3
SETTING_KEY = "chat_memory_enabled"

DDL = """
CREATE TABLE IF NOT EXISTS chat_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer_summary TEXT NOT NULL,
    doc_titles TEXT,            -- 근거로 쓰인 논문들 (쉼표)
    mode TEXT,                  -- local | cloud
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chat_memory_fts USING fts5(
    mem_id UNINDEXED,
    body,
    tokenize='trigram'
);
"""

# "정보 없음" 류 답변은 학습 가치가 없다 — 저장하면 오히려 잡음
_USELESS = re.compile(r"(정보(가|를)?\s*(없|찾을 수 없)|자료 없음|찾지 못했|근거를 찾지)")


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


# ── 스위치 ────────────────────────────────────────────────────────
def is_enabled(conn: sqlite3.Connection) -> bool:
    """기본 OFF — 입력 토큰이 늘어나므로 사용자가 명시적으로 켜야 한다."""
    ensure(conn)
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (SETTING_KEY,)).fetchone()
    return bool(row) and row["value"] == "1"


def set_enabled(conn: sqlite3.Connection, on: bool) -> None:
    ensure(conn)
    conn.execute(
        "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
        (SETTING_KEY, "1" if on else "0"),
    )


# ── 압축 (LLM 없이, 0원) ──────────────────────────────────────────
def compact(answer: str) -> str:
    """답변에서 핵심만 남긴다. 문장 단위로 자르되 상한을 넘지 않게."""
    text = re.sub(r"\s+", " ", (answer or "").strip())
    text = re.sub(r"\s*\[\d+(?:,\s*\d+)*\]", "", text)  # [1], [2, 3] 인용 마커 제거(앞 공백 포함)
    text = re.sub(r"\s+([.!?,])", r"\1", text)  # 마커 제거로 생긴 " ." 정리
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) <= MAX_ANSWER_CHARS:
        return text
    out = ""
    for sent in re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s*", text):
        if not sent:
            continue
        if len(out) + len(sent) > MAX_ANSWER_CHARS:
            break
        out += sent + " "
    return (out.strip() or text[:MAX_ANSWER_CHARS]).strip()


def remember(
    conn: sqlite3.Connection, question: str, answer: str, doc_titles: list[str], mode: str
) -> bool:
    """Q&A를 압축 저장. 학습 가치 없는 답변(정보 없음 등)은 저장하지 않는다."""
    ensure(conn)
    q = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not q or not answer or _USELESS.search(answer):
        return False

    summary = compact(answer)
    if len(summary) < 15:
        return False

    titles = ", ".join(t for t in doc_titles[:3] if t)
    cur = conn.execute(
        "INSERT INTO chat_memory (question, answer_summary, doc_titles, mode, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (q, summary, titles, mode, utcnow()),
    )
    conn.execute(
        "INSERT INTO chat_memory_fts (mem_id, body) VALUES (?, ?)",
        (cur.lastrowid, f"{q}\n{summary}"),
    )
    return True


# ── 검색 (FTS5, 0원) ──────────────────────────────────────────────
def recall(conn: sqlite3.Connection, question: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """새 질문과 관련된 과거 Q&A만 골라 반환. 관련 없으면 빈 리스트(→ 주입 비용 0)."""
    ensure(conn)
    terms = [t for t in re.split(r"\s+", (question or "").strip()) if len(t) >= 3]
    if not terms:
        return []
    match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)

    try:
        rows = conn.execute(
            """SELECT m.id, m.question, m.answer_summary, m.doc_titles, bm25(chat_memory_fts) AS score
               FROM chat_memory_fts f JOIN chat_memory m ON m.id = f.mem_id
               WHERE chat_memory_fts MATCH ? ORDER BY score LIMIT ?""",
            (match, top_k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "id": r["id"],
            "question": r["question"],
            "answer_summary": r["answer_summary"],
            "doc_titles": r["doc_titles"] or "",
        }
        for r in rows
    ]


def build_preamble_block(memories: list[dict]) -> str:
    """회수한 기억을 프롬프트에 넣을 짧은 텍스트로. 비면 빈 문자열(주입 안 함)."""
    if not memories:
        return ""
    lines = [
        "다음은 이 사용자가 과거에 묻고 확인한 내용이다. 같은 주제라면 일관되게 답하되,",
        "이번 논문 발췌와 충돌하면 반드시 발췌를 우선하라(과거 기억은 참고일 뿐이다).",
    ]
    for i, m in enumerate(memories, 1):
        lines.append(f"[과거{i}] Q: {m['question']} / A: {m['answer_summary']}")
    return "\n".join(lines)


def list_memories(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    ensure(conn)
    rows = conn.execute(
        "SELECT id, question, answer_summary, doc_titles, mode, created_at "
        "FROM chat_memory ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_memory(conn: sqlite3.Connection, mem_id: int) -> None:
    ensure(conn)
    conn.execute("DELETE FROM chat_memory WHERE id = ?", (mem_id,))
    conn.execute("DELETE FROM chat_memory_fts WHERE mem_id = ?", (mem_id,))


def clear_all(conn: sqlite3.Connection) -> int:
    ensure(conn)
    n = conn.execute("SELECT COUNT(*) c FROM chat_memory").fetchone()["c"]
    conn.execute("DELETE FROM chat_memory")
    conn.execute("DELETE FROM chat_memory_fts")
    return n
