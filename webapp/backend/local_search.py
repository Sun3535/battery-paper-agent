"""완전 로컬 무료 검색 (비용 0원, GCP 미사용).

Vertex AI Search(데이터스토어)를 대체한다. 논문 전문이 이미 SQLite blocks 테이블에 들어와
있으므로, SQLite 내장 FTS5 전문검색 + BM25 랭킹만으로 "어느 논문이 이 주제를 다루고,
뭐라고 썼는지"를 찾을 수 있다. 외부 호출 0회 → 과금 0원, 오프라인에서도 동작.

토크나이저는 **trigram**을 쓴다. 기본 unicode61은 한국어 조사를 못 떼서
"음극재"로 검색하면 "음극재의"를 못 찾는다(실측 확인). trigram은 부분 문자열 매칭이라
한국어·영어·혼합 문체("이 cathode는 높은 capacity retention을 보인다")에 모두 걸린다.

⚠️ 클라우드 RAG와의 차이: LLM 요약(그라운딩 답변)은 없다. 대신 **매칭된 원문 구절**을
논문별로 묶어 보여준다. 요약이 필요하면 그때만 LLM을 부르면 되고, 그건 유료 경로라
하드락(PAID_APIS_ENABLED)에 걸린다.
"""

from __future__ import annotations

import re
import sqlite3

FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5(
    doc_id UNINDEXED,
    block_order UNINDEXED,
    page UNINDEXED,
    body,
    tokenize='trigram'
);
"""

# trigram은 3글자 이상이어야 매칭된다 — 그보다 짧은 검색어는 무시(경고로 알림)
MIN_TERM_LEN = 3


def ensure_index(conn: sqlite3.Connection) -> None:
    conn.executescript(FTS_DDL)


def index_document(conn: sqlite3.Connection, doc_id: str) -> int:
    """한 문서의 블록을 색인. 원문(text_en)과 번역(text_ko)을 모두 넣어
    한국어 질문·영어 질문 어느 쪽으로도 찾을 수 있게 한다. 재색인 시 기존 항목은 교체."""
    ensure_index(conn)
    conn.execute("DELETE FROM blocks_fts WHERE doc_id = ?", (doc_id,))

    # figure_analyses 테이블이 아직 없을 수 있으므로 먼저 보장 (그림 AI 분석 기능과 공존)
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS figure_analyses ("
        " doc_id TEXT NOT NULL, block_order INTEGER NOT NULL, analysis_ko TEXT NOT NULL,"
        " model TEXT, created_at TEXT NOT NULL, PRIMARY KEY (doc_id, block_order));"
    )
    rows = conn.execute(
        """SELECT b.block_order, b.page, b.text_en, t.text_ko, fa.analysis_ko
           FROM blocks b
           LEFT JOIN translations t ON t.doc_id = b.doc_id AND t.block_order = b.block_order
           LEFT JOIN figure_analyses fa ON fa.doc_id = b.doc_id AND fa.block_order = b.block_order
           WHERE b.doc_id = ? AND (b.text_en != '' OR fa.analysis_ko IS NOT NULL)""",
        (doc_id,),
    ).fetchall()

    payload = []
    for r in rows:
        # 원문 + 번역 + 그림분석을 한 필드에 → 어떤 언어/형태의 질의도 같은 구절에 걸린다
        body = r["text_en"] or ""
        if r["text_ko"]:
            body = f"{body}\n{r['text_ko']}"
        if r["analysis_ko"]:
            body = f"{body}\n{r['analysis_ko']}"
        payload.append((doc_id, r["block_order"], r["page"], body.strip()))

    conn.executemany(
        "INSERT INTO blocks_fts (doc_id, block_order, page, body) VALUES (?, ?, ?, ?)",
        payload,
    )
    return len(payload)


def rebuild_all(conn: sqlite3.Connection) -> int:
    """전체 문서 재색인 (기존 문서들을 처음 로컬검색에 태울 때 1회 실행)."""
    ensure_index(conn)
    conn.execute("DELETE FROM blocks_fts")
    total = 0
    for r in conn.execute("SELECT doc_id FROM documents").fetchall():
        total += index_document(conn, r["doc_id"])
    return total


def document_passages(
    conn: sqlite3.Connection, doc_id: str, max_chars: int = 40_000
) -> dict | None:
    """논문 1편 전체를 읽기순서 그대로 '구절'로 반환 (검색 없이). 없거나 너무 크면 None.

    왜 검색을 안 쓰나: 질문에 조사가 붙으면("impedance를") trigram이 영문 원문과 매칭되지
    않아 핵심 문장을 놓친다(실측). 한 편만 볼 때는 후보가 이미 좁으므로 통째로 읽히는 게
    정확하다. 논문 1편은 보통 1.5만~4만 자라 한 번에 넣을 수 있다.
    """
    row = conn.execute("SELECT title, page_count FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if not row:
        return None

    rows = conn.execute(
        """SELECT b.block_order, b.page, b.text_en, t.text_ko
           FROM blocks b
           LEFT JOIN translations t ON t.doc_id=b.doc_id AND t.block_order=b.block_order
           WHERE b.doc_id=? AND b.kind='text' AND b.text_en != ''
           ORDER BY b.block_order""",
        (doc_id,),
    ).fetchall()

    passages, total, all_chars, truncated = [], 0, 0, False
    for r in rows:
        text = (r["text_ko"] or r["text_en"]).strip()
        if len(text) < 15:  # 수식 조각·페이지 번호 등은 건너뛴다
            continue
        all_chars += len(text)
        if truncated:
            continue  # 예산이 찼다 — 전체 분량을 알려 주려고 글자 수만 계속 센다
        room = max_chars - total
        if len(text) > room:
            # 예산을 넘기는 문단: 남은 만큼만(문장 끝에 맞춰) 넣고 멈춘다. 예전에는 이 문단을 통째로 버리고 멈췄다.
            truncated = True
            if room >= 200:
                cut = text[:room]
                dot = max(cut.rfind(". "), cut.rfind("다. "), cut.rfind("。"))
                cut = cut[: dot + 1] if dot >= room // 2 else cut
                total += len(cut)
                passages.append({"page": r["page"], "order": r["block_order"], "text": cut})
            continue
        total += len(text)
        passages.append({"page": r["page"], "order": r["block_order"], "text": text})

    if not passages:
        return None
    # 어디까지 읽었는지 — 챗봇이 "전문을 읽었다" 고 말하지 않게, 화면에도 그대로 알린다(2026-10-14 점검:
    # 91편 중 75편이 예산에 걸려 뒤쪽을 못 읽는데 AI 에게는 "전문" 이라고 말하고 있었다).
    coverage = {
        "doc_id": doc_id,
        "title": row["title"],
        "pages": row["page_count"] or 0,
        "read_until_page": passages[-1]["page"],
        "read_chars": total,
        "total_chars": all_chars,
        "truncated": truncated,
    }
    return {
        # full=True: 이 묶음은 검색 조각이 아니라 논문을 읽기 순서대로 읽은 것이다
        "results": [{"doc_id": doc_id, "title": row["title"], "score": 0, "passages": passages, "full": True}],
        "total_hits": len(passages),
        "note": "",
        "full_document": True,
        "chars": total,
        "coverage": [coverage],
    }


def focused_passages(
    conn: sqlite3.Connection,
    doc_ids: list[str],
    query: str,
    total_chars: int = 40_000,
    reference_docs: int = 3,
) -> dict | None:
    """체크한 논문들을 **집중** 근거로 읽고, 라이브러리 나머지는 **참고**로 붙인다.

    호야 지시(2026-07-28): "체크박스한 논문에 대해 집중적으로 답변하되, 기본 저장된
    논문은 참고할 수 있도록." → 집중 논문은 통째로(조사 때문에 검색이 새는 걸 피함),
    나머지는 검색 상위 몇 편만 얹는다. 전부 로컬 FTS/SQLite — 비용 0.
    """
    ids = [d for d in dict.fromkeys(doc_ids) if d]  # 순서 유지 + 중복 제거
    if not ids:
        return None

    # 편당 몫 = 전체 예산 ÷ 편수. 예전에는 편당 4천 자를 밑으로 깔아 30편쯤 고르면 프롬프트가 17만 자로 불었고,
    # 문단 400개 상한에서 뒤 논문들이 소리 없이 빠졌다(2차 점검). 이제 안내(coverage)가 실제로 들어간 양과 같다.
    budget = max(400, total_chars // len(ids))
    focus_results: list[dict] = []
    focus_titles: list[str] = []
    coverage: list[dict] = []

    for d in ids:
        whole = document_passages(conn, d, max_chars=budget)
        if whole:
            focus_results.extend(whole["results"])
            focus_titles.extend(g["title"] for g in whole["results"])
            coverage.extend(whole["coverage"])
            continue
        # 본문이 없는(추출 실패) 논문은 검색으로라도 건진다
        hit = search(conn, query, doc_id=d)
        for g in hit["results"]:
            focus_results.append(g)
            focus_titles.append(g["title"])

    if not focus_results:
        return None

    # 참고 — 체크하지 않은 논문 중 질문과 맞는 것 몇 편
    refs: list[dict] = []
    if reference_docs > 0:
        chosen = set(ids)
        wide = search(conn, query, max_docs=reference_docs + len(ids), per_doc=2)
        refs = []
        for g in wide["results"]:
            if g["doc_id"] in chosen:
                continue
            # 저작권·라이선스 안내문은 참고 근거가 아니다(한국어 질문이 "논문의" 같은 낱말로 그 문단에 걸렸다)
            ps = [p for p in g["passages"] if not _BOILERPLATE.search(p["text"])]
            if ps:
                refs.append({**g, "passages": ps, "ref": True})  # ref: 고른 논문이 아니라 참고로 붙인 다른 논문
        refs = refs[:reference_docs]

    return {
        "results": focus_results + refs,
        "focus_ids": ids,
        "focus_titles": focus_titles,
        "reference_titles": [g["title"] for g in refs],
        "total_hits": sum(len(g["passages"]) for g in focus_results + refs),
        "note": "",
        "full_document": True,
        "coverage": coverage,
    }


PASSAGE_WINDOW = 700  # 검색으로 찾은 문단에서 AI·화면에 넘기는 글자 수(찾은 낱말 둘레)
_BOILERPLATE = re.compile(r"creative\s*commons|licen[cs]e|all rights reserved|©|저작권|라이선스|이용\s*허락", re.IGNORECASE)


def _passage_window(text_ko: str | None, text_en: str | None, terms: list[str], width: int = PASSAGE_WINDOW) -> str:
    """찾은 블록의 글을 읽어, 검색어 둘레 width 자를 「」 강조와 함께 돌려준다.

    예전에는 FTS5 snippet() 을 썼는데, 색인이 trigram 이라 "토큰 26개" 가 30자 남짓이었다(늘려도 68자가 끝).
    AI 도 사용자도 `…ial 「Coulombic」 「Efficiency」 and…` 같은 조각만 보고 있었다(2026-10-14 점검).
    """
    # 검색어가 실제로 들어 있는 쪽(번역문 / 원문)을 고른다. 둘 다 없으면 번역문 우선.
    cands = [c for c in ((text_ko or "").strip(), (text_en or "").strip()) if c]
    if not cands:
        return ""
    low_terms = [t.lower() for t in terms]
    text = next((c for c in cands if any(t in c.lower() for t in low_terms)), cands[0])
    text = re.sub(r"\s+", " ", text)
    low = text.lower()
    hits = [low.find(t) for t in low_terms if low.find(t) >= 0]
    start, end = 0, len(text)
    if len(text) > width:
        center = min(hits) if hits else 0
        start = max(0, center - width // 3)
        end = min(len(text), start + width)
        start = max(0, end - width)
        # 낱말 중간에서 자르지 않는다
        if start > 0:
            sp = text.find(" ", start)
            start = sp + 1 if 0 <= sp < start + 40 else start
        if end < len(text):
            sp = text.rfind(" ", start, end)
            end = sp if sp > end - 40 else end
    out = text[start:end]
    if terms:
        # 한 번에 씌운다 — 낱말마다 따로 씌우면 겹친 낱말("sodium-ion" 과 "sodium")에 괄호가 겹쳐 「「…」…」 가 된다
        pat = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
        out = re.sub("(" + pat + ")", "「\\1」", out, flags=re.IGNORECASE)
    return ("…" if start > 0 else "") + out + ("…" if end < len(text) else "")


def _build_match(query: str, mode: str = "and") -> str | None:
    """사용자 질문 → FTS5 MATCH 식. 특수문자는 따옴표로 감싸 무력화한다."""
    terms = [t for t in re.split(r"\s+", query.strip()) if len(t) >= MIN_TERM_LEN]
    if not terms:
        return None
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms]
    return (" AND " if mode == "and" else " OR ").join(quoted)


def search(
    conn: sqlite3.Connection,
    query: str,
    max_docs: int = 5,
    per_doc: int = 3,
    doc_id: str | None = None,
) -> dict:
    """BM25 랭킹으로 관련 구절을 찾아 논문별로 묶어 반환. 외부 호출 없음 → 0원.

    모든 단어를 포함(AND)하는 구절을 먼저 찾고, 없으면 일부만 포함(OR)으로 완화한다.

    doc_id: 지정하면 **그 논문 안에서만** 찾는다. 사용자가 특정 논문(예: Nature 논문 한 편)에
    대해 물을 때 다른 논문 내용이 섞이지 않게 하는 안전장치.
    """
    ensure_index(conn)

    match = _build_match(query, "and")
    if not match:
        return {
            "results": [],
            "total_hits": 0,
            "note": f"{MIN_TERM_LEN}글자 이상인 검색어를 넣어주세요.",
        }

    # 한 논문만 볼 때는 정밀도보다 **재현율**이 중요하다. 후보가 그 논문 안으로 이미 좁혀져
    # 있으므로 AND(모든 단어)로 조이면 핵심 문장을 놓친다(실측: 논문의 결론 문장을 못 집음).
    # → OR 매칭 + 구절 수 확대로 LLM에 충분한 맥락을 준다.
    if doc_id:
        max_docs, per_doc = 1, max(per_doc, 12)
        match = _build_match(query, "or") or match

    def run(m: str) -> list[sqlite3.Row]:
        sql = """SELECT f.doc_id, f.block_order, f.page,
                        snippet(blocks_fts, 3, '「', '」', '…', 26) AS snip,
                        bm25(blocks_fts) AS score,
                        d.title, b.text_en, t.text_ko
                 FROM blocks_fts f
                 JOIN documents d ON d.doc_id = f.doc_id
                 LEFT JOIN blocks b ON b.doc_id = f.doc_id AND b.block_order = f.block_order
                 LEFT JOIN translations t ON t.doc_id = f.doc_id AND t.block_order = f.block_order
                 WHERE blocks_fts MATCH ?"""
        params: list = [m]
        if doc_id:
            sql += " AND f.doc_id = ?"
            params.append(doc_id)
        sql += " ORDER BY score LIMIT 60"
        return conn.execute(sql, params).fetchall()

    rows = run(match)
    relaxed = False
    if not rows:
        or_match = _build_match(query, "or")
        if or_match:
            rows = run(or_match)
            relaxed = bool(rows)

    terms = [t for t in re.split(r"\s+", query.strip()) if len(t) >= MIN_TERM_LEN]

    # 논문별로 묶기 (BM25는 낮을수록 관련도 높음)
    grouped: dict[str, dict] = {}
    for r in rows:
        g = grouped.setdefault(
            r["doc_id"],
            {"doc_id": r["doc_id"], "title": r["title"], "score": r["score"], "passages": []},
        )
        if len(g["passages"]) < per_doc:
            g["passages"].append(
                {
                    "page": r["page"],
                    "order": r["block_order"],
                    "text": _passage_window(r["text_ko"], r["text_en"], terms)
                    or re.sub(r"\s+", " ", r["snip"]).strip(),
                }
            )
        g["score"] = min(g["score"], r["score"])

    results = sorted(grouped.values(), key=lambda g: g["score"])[:max_docs]

    note = ""
    if relaxed:
        note = "모든 단어를 포함한 구절이 없어, 일부 단어만 포함한 결과를 보여줍니다."
    return {"results": results, "total_hits": len(rows), "note": note}
