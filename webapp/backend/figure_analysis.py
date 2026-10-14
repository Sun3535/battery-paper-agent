"""그림·표 멀티모달 AI 분석 (Gemini Vision).

추출기가 만든 그림/표 PNG에 **캡션 + 주변 본문 맥락**을 함께 넣어, "이 그래프가 논문에서
무엇을 보여주는가"를 한국어로 분석한다. scripts/02_analyze_image.py(단독 이미지 해설)의
웹앱 통합·맥락 강화판.

비용: Gemini API 직접 호출 = 유료(카드). App Builder 크레딧 적용 안 됨.
  - flash 기준 그림 1장 ≈ ₩3~6 (이미지 입력 + 한국어 분석 출력)
  - 하드락(PAID_APIS_ENABLED)에 걸리며, 자동 실행 없음 — 논문별 버튼으로만 트리거.
  - 분석 결과는 DB 캐시 → 같은 그림 재분석 없음(재과금 0). 그림 단위로 즉시 저장(중단 안전).
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

import store
from translate import _get_client_and_model  # 채널 선택 + 하드락 검사 재사용

PACING_SEC = 2.0  # vision 호출은 무겁다 — rate limit 예방
CONTEXT_CHARS = 700  # 그림 앞뒤 본문에서 가져올 맥락 길이

SYSTEM_RULE = """너는 이차전지·재료과학 논문의 그림과 표를 해설하는 전문 분석가다.

규칙:
1. 제공된 [캡션]과 [본문 맥락]을 반드시 반영해서, 이 그림이 논문 주장에서 어떤 역할인지 연결하라.
2. 학술 용어·단위·축 라벨은 **영어 원문 그대로** 쓰고, 서술어만 한국어로 옮겨라.
   - 옳음: "이 cathode의 exchange current density는 ..." / "CCL proton conductivity가 증가한다"
   - 틀림: "음극", "교환 전류 밀도", "촉매층", "양성자 전도도" ← 학술 용어를 한글로 바꾸지 마라.
3. 그림에서 실제로 읽을 수 있는 것만 말하라. 수치는 그림에 보이는 대로만 인용하고, 안 보이면 추측하지 마라.
4. **순수 텍스트만 출력하라.** 마크다운(**, ##, - )과 LaTeX($, \\, _{}, ^{})을 절대 쓰지 마라.
   아래첨자·위첨자는 일반 문자로 (예: i*, sigma_p 대신 σp, 10^-4 대신 10-4 처럼 보이는 대로).
5. 형식 (각 항목 1~3문장, 항목 앞에 ①②③만 붙임):
   ① 데이터 개요: 축/구성이 무엇을 보여주는가
   ② 핵심 발견: 가장 중요한 경향·비교·수치
   ③ 논문 맥락: 본문 주장과 어떻게 연결되는가
6. 전체 350자 이내로 간결하게."""

DDL = """
CREATE TABLE IF NOT EXISTS figure_analyses (
    doc_id TEXT NOT NULL,
    block_order INTEGER NOT NULL,
    analysis_ko TEXT NOT NULL,
    model TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (doc_id, block_order)
);
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def get_analyses(conn: sqlite3.Connection, doc_id: str) -> dict[int, str]:
    ensure_table(conn)
    rows = conn.execute(
        "SELECT block_order, analysis_ko FROM figure_analyses WHERE doc_id = ?", (doc_id,)
    ).fetchall()
    return {r["block_order"]: r["analysis_ko"] for r in rows}


def pending_figures(conn: sqlite3.Connection, doc_id: str) -> list[dict]:
    """아직 분석 안 된 그림/표 블록 목록 (캐시 히트분 제외 → 재과금 0)."""
    ensure_table(conn)
    blocks = store.get_blocks(conn, doc_id)
    done = get_analyses(conn, doc_id)
    out = []
    for i, b in enumerate(blocks):
        if b["kind"] in ("image", "table") and b["image_path"] and b["order"] not in done:
            out.append({"index": i, "block": b})
    return out


def _context_for(blocks: list[dict], idx: int) -> str:
    """그림 앞뒤의 본문 텍스트를 맥락으로 모은다 (캡션 제외 일반 문단 우선)."""
    parts: list[str] = []
    for j in range(idx - 1, max(-1, idx - 4), -1):
        if blocks[j]["kind"] == "text" and not blocks[j]["is_caption"]:
            parts.append(blocks[j]["text_en"][-CONTEXT_CHARS:])
            break
    for j in range(idx + 1, min(len(blocks), idx + 4)):
        if blocks[j]["kind"] == "text" and not blocks[j]["is_caption"]:
            parts.append(blocks[j]["text_en"][:CONTEXT_CHARS])
            break
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════
# 챗봇 주입 — 사용자가 돈 내고 만든 그림 분석을 챗봇이 반드시 활용하게 한다.
#
# 왜 필요한가: 클라우드 챗봇(Vertex AI Search)은 GCS의 PDF **텍스트**만 색인한다.
# 그림 속 수치(예: 임피던스 320→120)는 PDF 텍스트에 없으므로 챗봇이 "자료 없음"이라 답한다.
# (실측: 2026-07-16 QA에서 Nyquist 변화 질문에 답 못 함) → 로컬 분석문을 프롬프트에 실어준다.
# 회수는 로컬 FTS(0원), 과금은 주입 입력토큰뿐.
# ══════════════════════════════════════════════════════════════════

# 그림 질문 판별 — 오탐(false positive)을 피하는 게 핵심이다.
#   ❌ 맨 '축'은 압축/구축/축전지에 걸린다 → 축 앞뒤 문맥을 요구
#   ❌ 맨 '표'는 표면/표현/발표에 걸린다 → '표 1' 처럼 번호가 붙을 때만
#   ❌ 영어는 \b 없으면 exploit(plot)/acceptable(table)/curvature(curve)에 걸린다
_FIGURE_PATTERNS = [
    r"그림|그래프|도표|도식|모식도|삽도",
    r"표\s*\d|테이블",  # '표 1' — 맨 '표'는 제외(표면·표현 오탐)
    r"[xyzXYZ]\s*축|가로축|세로축|종축|횡축|축\s*(?:라벨|이름|눈금|값|범위)",
    r"피크|봉우리|곡선|스펙트럼|범례|반원|아크|기울기",
    r"이미지|사진|현미경",
    r"\bfig(?:ure)?s?\b|\bgraph\b|\bplot(?:s|ted)?\b|\bchart\b|\bdiagram\b|\bschematic\b",
    r"\btable\s*\d|\bpanel\b|\blegend\b",
    r"\bax(?:is|es)\b|\bx-axis\b|\by-axis\b",
    r"\bpeak(?:s)?\b|\bcurve(?:s)?\b|\bspectr(?:a|um)\b|\bslope\b",
    r"\bnyquist\b|\bbode\b|\bhistogram\b|\bscatter\b",
    r"\bsem\b|\btem\b|\bmicrograph\b|\bmapping\b",
]
FIGURE_WORDS = re.compile("|".join(_FIGURE_PATTERNS), re.IGNORECASE)


def is_figure_question(question: str) -> bool:
    """그림·표·그래프에 대해 묻는 질문인지 (오탐 최소화)."""
    return bool(FIGURE_WORDS.search(question or ""))


def relevant_analyses(
    conn: sqlite3.Connection, question: str, limit: int | None = None, doc_id: str | None = None
) -> list[dict]:
    """질문과 관련된 그림 분석문을 로컬 FTS로 회수 (0원). 없으면 빈 리스트.

    비용 최적화 — 질문 유형에 따라 매칭 강도를 바꾼다:
      · 그림 질문  → OR 매칭·최대 3건 (사용자가 그림을 묻고 있으니 넉넉히 준다)
      · 일반 질문  → AND 매칭·최대 2건 (강하게 관련될 때만. 안 그러면 토큰만 낭비)
    실측: "무시한 손실은?"(본문 질문)이 OR 매칭에선 무관한 그림분석 2건을 끌어와 211토큰을
    낭비했다 → AND 로 좁히면 0건이 되어 주입 비용이 사라진다.
    """
    ensure_table(conn)
    terms = [t for t in re.split(r"\s+", (question or "").strip()) if len(t) >= 3]
    if not terms:
        return []

    fig_q = is_figure_question(question)
    joiner = " OR " if fig_q else " AND "
    if limit is None:
        limit = 3 if fig_q else 2
    match = joiner.join('"' + t.replace('"', '""') + '"' for t in terms)
    sql = """SELECT fa.analysis_ko, d.title, b.page, bm25(blocks_fts) AS score
             FROM blocks_fts f
             JOIN figure_analyses fa ON fa.doc_id = f.doc_id AND fa.block_order = f.block_order
             JOIN documents d ON d.doc_id = f.doc_id
             JOIN blocks b ON b.doc_id = f.doc_id AND b.block_order = f.block_order
             WHERE blocks_fts MATCH ?"""
    params: list = [match]
    if doc_id:  # 특정 논문으로 범위 지정 시 그 논문 그림만
        sql += " AND f.doc_id = ?"
        params.append(doc_id)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {"analysis": r["analysis_ko"], "title": r["title"], "page": r["page"]} for r in rows
    ]


def build_figure_block(analyses: list[dict]) -> str:
    """회수한 그림 분석을 프롬프트에 넣을 텍스트로. 비면 빈 문자열(주입 비용 0)."""
    if not analyses:
        return ""
    lines = [
        "다음은 이 논문들의 그림·표를 시각적으로 분석한 결과다(PDF 텍스트에는 없는 정보).",
        "그림 속 수치·경향을 묻는 질문이면 이 내용을 근거로 답하라.",
    ]
    for a in analyses:
        body = re.sub(r"\s+", " ", a["analysis"])[:400]
        lines.append(f"[그림분석 · {a['title']} p{a['page']}] {body}")
    return "\n".join(lines)


def has_any_analysis(conn: sqlite3.Connection) -> bool:
    ensure_table(conn)
    return bool(conn.execute("SELECT 1 FROM figure_analyses LIMIT 1").fetchone())


def upsell_note(conn: sqlite3.Connection, question: str, used_analyses: int) -> str:
    """그림 질문인데 쓸 분석이 없을 때 — 유료 기능을 켜면 답할 수 있다고 안내."""
    if used_analyses or not is_figure_question(question):
        return ""
    ensure_table(conn)
    total = conn.execute("SELECT COUNT(*) c FROM figure_analyses").fetchone()["c"]
    if total == 0:
        return (
            "\n\n💡 그림·그래프에 대한 질문 같습니다. 지금은 **그림 AI 분석을 실행하지 않아** "
            "그래프 속 수치·경향은 확실히 답할 수 없습니다. 좌측 [그림·표 AI 분석]의 [실행]을 누르면"
            "(그림 1장 ≈ ₩3~6) 축 라벨·수치까지 읽어 답할 수 있습니다."
        )
    return (
        "\n\n💡 이 질문과 맞는 그림 분석이 아직 없습니다. 해당 논문을 선택하고 "
        "[그림·표 AI 분석]의 [실행]을 누르면 그래프 속 수치까지 답할 수 있습니다."
    )


def analyze_document(doc_id: str, api_key: str | None = None, max_figures: int | None = None) -> int:
    """문서의 미분석 그림/표를 분석. 그림 단위 즉시 저장(중단돼도 보존). 분석 수 반환.

    max_figures: 지정 시 그만큼만 (시범/비용 상한용). 하드락이 걸려 있으면
    _get_client_and_model 이 PaidApiLocked 를 던진다.
    """
    from google.genai import types

    client, model_name = _get_client_and_model(api_key)  # 하드락 검사 포함
    model_name = os.getenv("FIGURE_ANALYSIS_MODEL", model_name)

    with store.connect() as conn:
        blocks = store.get_blocks(conn, doc_id)
        targets = pending_figures(conn, doc_id)
    if max_figures is not None:
        targets = targets[:max_figures]

    done = 0
    for t in targets:
        b = t["block"]
        png = store.IMAGES_DIR / doc_id / b["image_path"]
        if not png.exists():
            continue

        caption = b["text_en"] or b["text_ko"] or "(캡션 없음)"
        context = _context_for(blocks, t["index"])
        prompt = (
            f"[캡션]\n{caption}\n\n[본문 맥락]\n{context or '(맥락 없음)'}\n\n"
            "위 정보를 반영해 이 그림을 규칙대로 분석하라."
        )

        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=png.read_bytes(), mime_type="image/png"),
                    prompt,
                ],
                config=types.GenerateContentConfig(system_instruction=SYSTEM_RULE),
            )
            analysis = (resp.text or "").strip()
        except Exception:
            continue  # 개별 그림 실패는 스킵 — 다음 실행 때 자동 재시도(미저장 상태 유지)

        if not analysis:
            continue
        with store.connect() as conn:
            ensure_table(conn)
            conn.execute(
                "INSERT OR REPLACE INTO figure_analyses (doc_id, block_order, analysis_ko, model, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (doc_id, b["order"], analysis, model_name, store.utcnow()),
            )
        done += 1
        time.sleep(PACING_SEC)

    # 분석문을 로컬 검색에도 태운다 → "이 그래프 내용" 질문이 검색에 걸린다
    if done:
        import local_search

        with store.connect() as conn:
            local_search.index_document(conn, doc_id)

    return done
