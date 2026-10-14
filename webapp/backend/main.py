"""통합 AI 논문 에이전트 플랫폼 — FastAPI 백엔드.

실행:
    cd Article_Battery
    python -m uvicorn webapp.backend.main:app --reload --port 8100

엔드포인트:
    POST /api/documents            PDF 업로드(드래그앤드롭) → 백그라운드 처리 시작
    GET  /api/documents            문서 목록 + 처리 상태
    GET  /api/documents/{id}       문서 메타
    GET  /api/documents/{id}/blocks  E-book 리더용 블록(원문+번역, 읽기순서)
    GET  /api/documents/{id}/assets  그림·표·참고문헌 모음
    GET  /api/images/{id}/{name}   추출된 그림/표 PNG
    POST /api/chat                 논문 근거 기반 챗봇 답변(Vertex AI Search)
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent.parent  # Article_Battery/
sys.path.insert(0, str(BACKEND_DIR))  # 백엔드 모듈 평면 임포트
sys.path.insert(0, str(PROJECT_ROOT))  # rag 패키지 임포트

load_dotenv(PROJECT_ROOT / ".env")

import ingest  # noqa: E402
import store  # noqa: E402

app = FastAPI(title="Battery Paper Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str
    doc_id: str | None = None  # 지정 시 그 논문 안에서만 답한다(타 논문 혼입 차단)
    # 라이브러리에서 체크한 논문들 — 이 논문들을 집중적으로 읽고, 나머지는 참고로만 쓴다
    doc_ids: list[str] = []


class UserCreate(BaseModel):
    username: str
    password: str
    api_key: str = ""


class PasswordBody(BaseModel):
    password: str


class KeyUpdate(BaseModel):
    password: str
    api_key: str


class CredentialUpdate(BaseModel):
    password: str
    kind: str  # free | paid | credit
    value: str


class CredentialReveal(BaseModel):
    password: str
    kind: str


class PreferredUpdate(BaseModel):
    password: str
    kind: str


@app.post("/api/documents")
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    translate: bool = Form(False),  # 체크박스: 한국어 번역 (유료 위험 — 사용자 판단)
    analyze: bool = Form(False),  # 체크박스: 그림·표 AI 분석 (유료 위험 — 사용자 판단)
):
    """PDF 드래그앤드롭 수집 → 저장 후 백그라운드 처리.

    추출·로컬색인은 항상(무료). 번역·그림분석은 체크박스로 켠 것만 — 기본 OFF(0원).
    켰더라도 하드락(PAID_APIS_ENABLED=false)이면 건너뛰고 사유를 남긴다.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 업로드할 수 있습니다.")

    doc_id = uuid.uuid4().hex[:12]
    store.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = store.UPLOAD_DIR / f"{doc_id}.pdf"
    content = await file.read()
    if not content.startswith(b"%PDF"):
        raise HTTPException(400, "PDF 형식이 아닙니다.")
    dest.write_bytes(content)

    title = Path(file.filename).stem
    with store.connect() as conn:
        store.create_document(
            conn, doc_id, title, file.filename, dest, opt_translate=translate, opt_analyze=analyze
        )

    background.add_task(ingest.process_document, doc_id)
    return {"doc_id": doc_id, "title": title, "status": "pending"}


@app.get("/api/documents")
def list_documents():
    import library

    with store.connect() as conn:
        rows = store.list_documents(conn)
        paid = store.paid_status_map(conn)  # 번역·그림분석이 어디까지 됐는지 (로컬 집계, 0원)
    out = []
    for r in rows:
        has_cover = (store.IMAGES_DIR / r["doc_id"] / library.COVER_NAME).exists()
        out.append(
            {
                "doc_id": r["doc_id"],
                "title": r["title"],
                "filename": r["filename"],
                "status": r["status"],
                "progress": r["progress"],
                "page_count": r["page_count"],
                "error": r["error"],
                "created_at": r["created_at"],
                # 표지 = PDF 1페이지 렌더 (로컬 생성, 비용 0)
                "cover_url": f"/api/images/{r['doc_id']}/{library.COVER_NAME}" if has_cover else None,
                # 카드 배지 + 재과금 차단이 같은 값을 본다
                **paid.get(r["doc_id"], {}),
            }
        )
    return out


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    with store.connect() as conn:
        r = store.get_document(conn, doc_id)
    if not r:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    return {
        "doc_id": r["doc_id"],
        "title": r["title"],
        "status": r["status"],
        "progress": r["progress"],
        "page_count": r["page_count"],
        "error": r["error"],
    }


@app.get("/api/documents/{doc_id}/blocks")
def get_blocks(doc_id: str):
    """E-book 리더용. order 순서대로 렌더하면 그림이 원래 자리에 들어간다."""
    with store.connect() as conn:
        if not store.get_document(conn, doc_id):
            raise HTTPException(404, "문서를 찾을 수 없습니다.")
        blocks = store.get_blocks(conn, doc_id)
    for b in blocks:
        if b["image_path"]:
            b["image_url"] = f"/api/images/{doc_id}/{b['image_path']}"
    return {"doc_id": doc_id, "blocks": blocks}


@app.get("/api/documents/{doc_id}/assets")
def get_assets(doc_id: str):
    """시각자료·레퍼런스 뷰어용 — 그림/표/참고문헌을 종류별로 모아서 반환."""
    with store.connect() as conn:
        if not store.get_document(conn, doc_id):
            raise HTTPException(404, "문서를 찾을 수 없습니다.")
        blocks = store.get_blocks(conn, doc_id)
        refs = store.get_refs(conn, doc_id)

    figures, tables = [], []
    for b in blocks:
        if not b["image_path"]:
            continue
        item = {
            "order": b["order"],
            "page": b["page"],
            "image_url": f"/api/images/{doc_id}/{b['image_path']}",
            "caption_en": b["text_en"],
            "caption_ko": b["text_ko"],
            "table_rows": b["table_rows"],
            "analysis_ko": b.get("analysis_ko", ""),
        }
        (tables if b["kind"] == "table" else figures).append(item)

    return {"figures": figures, "tables": tables, "references": refs}


@app.post("/api/documents/{doc_id}/translate")
def translate_document(doc_id: str, background: BackgroundTasks):
    """[실행 버튼] 등록된 논문을 지금 번역 (유료 — 하드락 대상). 미번역 블록만(재과금 0)."""
    import guard

    with store.connect() as conn:
        if not store.get_document(conn, doc_id):
            raise HTTPException(404, "문서를 찾을 수 없습니다.")
        pending = store.untranslated_blocks(conn, doc_id)

    if not pending:
        return {"started": False, "pending": 0, "message": "이미 전부 번역되어 있습니다."}
    if not guard.paid_apis_enabled():
        return {"started": False, "pending": len(pending), "locked": True, "message": guard.block_message()}
    import translate

    with store.connect() as conn:
        ok, why = translate.ready(conn)
    if not ok:
        return {"started": False, "pending": len(pending), "message": why}

    background.add_task(ingest.translate_document, doc_id)
    via = f"Claude · {translate.current_model_name()}" if translate.provider() == "claude" else "~₩121/편"
    return {"started": True, "pending": len(pending), "message": f"블록 {len(pending)}개 번역 시작 ({via})."}


@app.post("/api/documents/{doc_id}/figures/analyze")
def analyze_figures(doc_id: str, background: BackgroundTasks):
    """그림·표 멀티모달 AI 분석 (유료 — Gemini Vision, 하드락 대상). 백그라운드 실행.

    미분석 그림만 처리(캐시 히트 재과금 0). 결과는 assets/blocks 응답의 analysis_ko로 조회.
    """
    import figure_analysis
    import guard
    import users

    with store.connect() as conn:
        if not store.get_document(conn, doc_id):
            raise HTTPException(404, "문서를 찾을 수 없습니다.")
        pending = figure_analysis.pending_figures(conn, doc_id)

    if not pending:
        return {"started": False, "pending": 0, "message": "분석할 그림이 없거나 이미 전부 분석됐습니다."}
    if not guard.paid_apis_enabled():
        return {"started": False, "pending": len(pending), "locked": True, "message": guard.block_message()}

    with store.connect() as conn:
        if not guard.usable_api_key(conn):
            return {"started": False, "pending": len(pending), "message": guard.NO_KEY_MESSAGE}
        active_key = users.active_api_key(conn)
    background.add_task(figure_analysis.analyze_document, doc_id, active_key)
    return {
        "started": True,
        "pending": len(pending),
        "message": f"그림 {len(pending)}장 분석 시작 (장당 약 ₩3~6, 그림 단위 저장).",
    }


@app.get("/api/images/{doc_id}/{name}")
def get_image(doc_id: str, name: str):
    # 경로 순회 차단
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "잘못된 파일명입니다.")
    path = store.IMAGES_DIR / doc_id / name
    if not path.exists():
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return FileResponse(path, media_type="image/png")


def _focus_preamble(focus_titles: list[str], ref_titles: list[str], full_doc: bool) -> str:
    """체크한 논문을 '집중', 나머지를 '참고'로 구분해 주는 지시문.

    이걸 안 붙이면 발췌가 섞여 들어가 모델이 어느 논문 이야기인지 헷갈린다(실측).
    """
    if not focus_titles:
        return ""
    names = "」, 「".join(focus_titles)
    what = "전문" if full_doc else "발췌"
    one = len(focus_titles) == 1
    text = (
        f"[중요] 사용자가 선택한 논문은 「{names}」 {'한 편' if one else f'{len(focus_titles)}편'}이다. "
        f"답은 이 논문{'' if one else '들'}의 내용을 중심으로 하라. 앞쪽 발췌가 그 논문{'' if one else '들'}의 {what}이다.\n"
    )
    if ref_titles:
        text += (
            "뒤쪽 발췌는 라이브러리의 다른 논문(참고용: 「"
            + "」, 「".join(ref_titles)
            + "」)이다. 보조 근거로만 쓰고, 선택한 논문의 주장인 것처럼 섞지 마라.\n"
        )
    elif one:
        text += "다른 논문 이야기는 하지 마라.\n"
    return text


@app.post("/api/chat")
def chat(req: ChatRequest):
    """논문 검색.

    SEARCH_MODE=local (기본) → SQLite FTS5 로컬 검색. **비용 0원, 외부 호출 없음.**
    SEARCH_MODE=cloud        → Vertex AI Search (LLM 요약 포함, 크레딧 차감. 하드락 대상)
    """
    if not req.question.strip():
        raise HTTPException(400, "질문이 비어 있습니다.")

    import chat_memory
    import figure_analysis
    import guard
    import local_search

    mode = os.getenv("SEARCH_MODE", "local").strip().lower()

    # 체크한 논문들(복수) 우선, 없으면 기존 단일 doc_id 경로
    focus_ids = [d.strip() for d in (req.doc_ids or []) if d and d.strip()]
    if not focus_ids and (req.doc_id or "").strip():
        focus_ids = [req.doc_id.strip()]
    scope = focus_ids[0] if len(focus_ids) == 1 else None  # 단일 논문일 때만 기존 경로 유지
    focus_titles: list[str] = []

    # 회수는 전부 로컬 FTS = 0원. 관련 자료가 없으면 주입도 없어 추가 비용 0.
    with store.connect() as conn:
        for d in focus_ids:
            row = store.get_document(conn, d)
            if not row:
                raise HTTPException(404, "지정한 논문을 찾을 수 없습니다.")
            focus_titles.append(row["title"])
        mem_on = chat_memory.is_enabled(conn)
        memories = chat_memory.recall(conn, req.question) if mem_on else []
        # 사용자가 돈 내고 만든 그림 분석은 **묻지 않아도 항상** 챗봇에게 전달한다.
        if focus_ids:
            figs = []
            for d in focus_ids:
                figs.extend(figure_analysis.relevant_analyses(conn, req.question, doc_id=d))
        else:
            figs = figure_analysis.relevant_analyses(conn, req.question)
        upsell = figure_analysis.upsell_note(conn, req.question, len(figs))

    scope_title = " · ".join(focus_titles) if focus_titles else None

    memory_block = chat_memory.build_preamble_block(memories) if memories else ""
    figure_block = figure_analysis.build_figure_block(figs)
    context_block = "\n\n".join(b for b in (figure_block, memory_block) if b)

    # ── 근거 수집 (0원) ──────────────────────────────────────────
    # 논문 1편 한정이면 **검색 대신 그 논문을 통째로** 읽힌다. 질문에 조사가 붙으면
    # ("impedance를") trigram 검색이 영문 원문과 매칭되지 않아 핵심 문장을 놓치기 때문
    # (실측: 논문의 결론 문장을 못 집어 "자료에 없다"고 답함).
    full_doc = False
    ref_titles: list[str] = []
    with store.connect() as conn:
        if focus_ids:
            packed = local_search.focused_passages(conn, focus_ids, req.question)
            if packed:
                res, full_doc = packed, True
                ref_titles = packed["reference_titles"]
            else:
                res = local_search.search(conn, req.question, doc_id=scope)
        else:
            res = local_search.search(conn, req.question)
    n_docs = len(res["results"])

    base = {
        "results": res["results"],
        "memories_used": [m["question"] for m in memories],
        "memory_hints": memories,
        "figures_used": [f"{f['title']} p{f['page']}" for f in figs],
        "scope": scope_title,
    }

    # 키워드 검색만 원하면 여기서 끝 (완전 0원)
    if mode == "keyword":
        if focus_ids:
            answer = (
                f"「{scope_title}」에서 관련 구절을 찾았습니다."
                if n_docs
                else f"「{scope_title}」에서는 관련 구절을 찾지 못했습니다."
            )
        else:
            answer = (
                f"논문 {n_docs}편에서 관련 구절을 찾았습니다."
                if n_docs
                else "관련 구절을 찾지 못했습니다. 다른 표현으로 검색해 보세요."
            )
        if res["note"]:
            answer += f" ({res['note']})"
        if figs:
            answer += f" (그림 분석 {len(figs)}건 포함)"
        return {"mode": "keyword", "answer": answer + upsell, "citations": [], **base}

    # ── 로컬 LLM 우선 (사내망) — 논문 내용이 PC 밖으로 나가지 않는다 ──
    # 오프라인 모드에서도 동작한다: 외부 통신이 아니라 127.0.0.1 호출이기 때문.
    import answer as answer_mod

    if os.getenv("USE_LOCAL_LLM", "false").strip().lower() == "true":
        try:
            ctx = _focus_preamble(focus_titles, ref_titles, full_doc) + context_block
            text, sources = answer_mod.summarize_local(
                req.question, res["results"], ctx, full_doc=full_doc
            )
            if text:
                if mem_on:
                    with store.connect() as conn:
                        chat_memory.remember(conn, req.question, text, sources, "local_llm")
                return {
                    "mode": "local_llm",
                    "answer": text + upsell,
                    "citations": [{"title": s, "gcs_uri": "", "snippet": ""} for s in sources],
                    **base,
                }
        except Exception as e:  # 로컬 LLM이 꺼져 있으면 아래 경로로 진행
            base["local_llm_error"] = f"{type(e).__name__}"

    # ── AI 요약 — 유료. 하드락이면 키워드 결과만 돌려준다 ──────────
    if not guard.paid_apis_enabled():
        where = f"「{scope_title}」에서" if focus_ids else f"논문 {n_docs}편에서"
        answer = (
            f"{where} 관련 구절을 찾았습니다. (AI 요약은 잠김) "
            if n_docs
            else f"{where} 관련 구절을 찾지 못했습니다. "
        )
        return {"mode": "locked", "answer": answer + guard.block_message(), "citations": [], **base}

    # ── 폴백 체인 (조건2): ① API 키로 요약 → ② Vertex → ③ 안내 ────
    import users

    with store.connect() as conn:
        chain = users.credential_chain(conn)
    tried: list[str] = []

    for cred in chain:
        try:
            if cred["kind"] in ("free", "paid"):
                # API 키만으로 RAG — Vertex 없는 사용자도 여기서 답을 받는다
                ctx = _focus_preamble(focus_titles, ref_titles, full_doc) + context_block
                text, sources = answer_mod.summarize(
                    req.question, res["results"], cred["key"], ctx, full_doc=full_doc
                )
                if not text:
                    raise RuntimeError("빈 응답")
                if mem_on:
                    with store.connect() as conn:
                        chat_memory.remember(conn, req.question, text, sources, "api")
                return {
                    "mode": "api",
                    "answer": text + upsell,
                    "citations": [{"title": s, "gcs_uri": "", "snippet": ""} for s in sources],
                    **base,
                }

            # 크레딧(Vertex AI Search) 경로
            # ⚠️ 특정 논문으로 범위를 지정한 경우엔 쓰지 않는다. Vertex AI Search는
            #    데이터스토어 전체에서 스니펫을 뽑기 때문에 **다른 논문 내용이 섞인다**
            #    (2026-07-16 실측: 대상 논문에 없는 synchrotron 문장이 답변에 포함됨).
            #    범위 지정 질문은 문서 경계가 정확한 로컬 경로로만 답한다.
            if focus_ids:
                raise RuntimeError("범위 지정 질문은 Vertex 경로를 사용하지 않음")

            from rag.search_client import ask

            r = ask(req.question, memory_block=context_block)
            text = (r.get("summary") or "").strip()
            if not text or "하드락" in text:
                raise RuntimeError("Vertex 응답 없음")
            citations = r.get("citations", [])
            if mem_on:
                with store.connect() as conn:
                    chat_memory.remember(
                        conn, req.question, text, [c.get("title", "") for c in citations], "cloud"
                    )
            return {"mode": "cloud", "answer": text + upsell, "citations": citations, **base}

        except Exception as e:  # noqa: BLE001 — 다음 자격증명으로 넘어간다
            tried.append(f"{cred['kind']}: {type(e).__name__}")

    # ③ 전부 실패 — 키워드 결과 + 안내
    hint = (
        (f"「{scope_title}」 안에서 " if focus_ids else "")
        + "AI 요약을 만들지 못했습니다. "
        + (
            f"시도한 경로: {', '.join(tried)}. "
            if tried
            else "사용 가능한 API 키나 GCP 프로젝트가 없습니다. "
        )
        + "우측 상단 [사용자] → [API]에서 API 키를 등록하거나 크레딧(GCP 프로젝트 ID)을 설정하세요. "
        "아래 검색 구절은 그대로 사용할 수 있습니다."
    )
    return {"mode": "fallback", "answer": hint, "citations": [], **base}


@app.post("/api/search/reindex")
def reindex():
    """기존 논문들을 로컬 검색 색인에 태운다 (무료·1회). 새 업로드는 자동 색인됨."""
    import local_search

    with store.connect() as conn:
        n = local_search.rebuild_all(conn)
    return {"indexed_blocks": n}


# ══════════════════════════════════════════════════════════════════
# 사용자별 API 키 관리
#   - 목록(GET /api/users)은 사용자명만. 비번·키는 절대 안 내려감.
#   - 조회/수정/삭제/활성화는 전부 비밀번호로 게이트.
# ══════════════════════════════════════════════════════════════════
from fastapi import Header  # noqa: E402


@app.get("/api/users")
def list_users():
    """평소 노출용 — 사용자명 + 자격증명 **마스킹** 상태. 원문 키는 절대 안 내려간다."""
    import users

    with store.connect() as conn:
        active = users.get_active(conn)
        rows = users.list_usernames(conn)
        for r in rows:
            r["credentials"] = users.get_credentials(conn, r["username"])
        return {"users": rows, "active": active}


@app.get("/api/users/{username}/credentials")
def get_credentials(username: str):
    """마스킹된 3종 자격증명 상태 (유료키/무료키/크레딧) + 선택된 기본값."""
    import users

    with store.connect() as conn:
        if not users.exists(conn, username):
            raise HTTPException(404, "사용자를 찾을 수 없습니다.")
        return users.get_credentials(conn, username)


@app.post("/api/users/{username}/credentials/reveal")
def reveal_credential(username: str, body: CredentialReveal):
    """비밀번호 확인 후 원문 반환 — 수정란 프리필용."""
    import users

    with store.connect() as conn:
        if not users.verify(conn, username, body.password):
            raise HTTPException(403, "비밀번호가 일치하지 않습니다.")
        try:
            return {"kind": body.kind, "value": users.get_credential_raw(conn, username, body.kind)}
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.put("/api/users/{username}/credentials")
def update_credential(username: str, body: CredentialUpdate):
    """저장·수정·삭제(빈 값 저장 = 삭제). 비밀번호 확인 필수."""
    import users

    with store.connect() as conn:
        if not users.verify(conn, username, body.password):
            raise HTTPException(403, "비밀번호가 일치하지 않습니다.")
        try:
            users.set_credential(conn, username, body.kind, body.value)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "credentials": users.get_credentials(conn, username)}


@app.put("/api/users/{username}/preferred")
def update_preferred(username: str, body: PreferredUpdate):
    """어떤 자격증명으로 유료 기능을 실행할지 선택."""
    import users

    with store.connect() as conn:
        if not users.verify(conn, username, body.password):
            raise HTTPException(403, "비밀번호가 일치하지 않습니다.")
        try:
            users.set_preferred(conn, username, body.kind)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "preferred": body.kind}


@app.post("/api/users")
def add_user(body: UserCreate):
    import users

    name = body.username.strip()
    if not name or not body.password:
        raise HTTPException(400, "사용자명과 비밀번호는 필수입니다.")
    with store.connect() as conn:
        if users.exists(conn, name):
            raise HTTPException(409, "이미 존재하는 사용자명입니다.")
        users.create(conn, name, body.password, body.api_key.strip())
    return {"username": name}


@app.post("/api/users/{username}/verify")
def verify_user(username: str, body: PasswordBody):
    """비밀번호 확인 — [API] 버튼 눌렀을 때 등. 맞으면 API 키를 함께 돌려준다(수정란 프리필용)."""
    import users

    with store.connect() as conn:
        if not users.verify(conn, username, body.password):
            raise HTTPException(403, "비밀번호가 일치하지 않습니다.")
        return {"ok": True, "api_key": users.get_api_key(conn, username)}


@app.put("/api/users/{username}/key")
def update_key(username: str, body: KeyUpdate):
    import users

    with store.connect() as conn:
        if not users.verify(conn, username, body.password):
            raise HTTPException(403, "비밀번호가 일치하지 않습니다.")
        users.set_api_key(conn, username, body.api_key.strip())
    return {"ok": True}


@app.post("/api/users/{username}/delete")
def remove_user(username: str, body: PasswordBody):
    import users

    with store.connect() as conn:
        if not users.verify(conn, username, body.password):
            raise HTTPException(403, "비밀번호가 일치하지 않습니다.")
        users.delete(conn, username)
    return {"ok": True}


@app.post("/api/users/{username}/activate")
def activate_user(username: str, body: PasswordBody):
    """이름 클릭 → 비번 팝업 통과 시 이 사용자를 번역 키의 주인으로 지정(도용 방지)."""
    import users

    with store.connect() as conn:
        if not users.verify(conn, username, body.password):
            raise HTTPException(403, "비밀번호가 일치하지 않습니다.")
        if not users.get_api_key(conn, username):
            raise HTTPException(400, "이 사용자에게 등록된 API 키가 없습니다. 먼저 키를 등록하세요.")
        users.set_active(conn, username)
    return {"ok": True, "active": username}


@app.post("/api/users/deactivate")
def deactivate_user():
    import users

    with store.connect() as conn:
        users.set_active(conn, None)
    return {"ok": True}


@app.get("/api/admin/users")
def admin_raw_users(x_admin_token: str = Header(default="")):
    """⚠️ 개발자 전용 (비번찾기) — 평문 비번·키 전체.
    env ADMIN_TOKEN 과 헤더 X-Admin-Token 이 일치할 때만. 미설정 시 비활성(403)."""
    import users

    admin = os.getenv("ADMIN_TOKEN", "")
    if not admin or x_admin_token != admin:
        raise HTTPException(403, "관리자 토큰이 필요합니다 (.env ADMIN_TOKEN + 헤더 X-Admin-Token).")
    with store.connect() as conn:
        return {"users": users.raw_all(conn)}


# ══════════════════════════════════════════════════════════════════
# 챗봇 대화 기억 (맞춤형 스킬) — 저장·검색은 0원, 주입 입력토큰만 과금
# ══════════════════════════════════════════════════════════════════
@app.get("/api/memory")
def memory_list():
    import chat_memory

    with store.connect() as conn:
        return {"enabled": chat_memory.is_enabled(conn), "memories": chat_memory.list_memories(conn)}


@app.post("/api/memory/toggle")
def memory_toggle(body: dict):
    import chat_memory

    on = bool(body.get("enabled"))
    with store.connect() as conn:
        chat_memory.set_enabled(conn, on)
    return {"enabled": on}


@app.post("/api/memory/{mem_id}/delete")
def memory_delete(mem_id: int):
    import chat_memory

    with store.connect() as conn:
        chat_memory.delete_memory(conn, mem_id)
    return {"ok": True}


@app.post("/api/memory/clear")
def memory_clear():
    import chat_memory

    with store.connect() as conn:
        return {"deleted": chat_memory.clear_all(conn)}


# ══════════════════════════════════════════════════════════════════
# 라이브러리 저장 경로 — 사용자마다 다른 폴더를 쓸 수 있다
# ══════════════════════════════════════════════════════════════════
class LibraryPathUpdate(BaseModel):
    path: str | None = None  # None 또는 빈 값이면 기본 경로로 되돌린다


def _library_stats() -> dict:
    info = store.current_paths()
    try:
        with store.connect() as conn:
            info["doc_count"] = len(store.list_documents(conn))
    except Exception:
        info["doc_count"] = 0
    info["db_exists"] = Path(info["db"]).exists()
    return info


@app.get("/api/library/path")
def get_library_path():
    return _library_stats()


@app.put("/api/library/path")
def set_library_path(body: LibraryPathUpdate):
    """저장 폴더 변경. 폴더 안에 {papers.db, uploads/, images/} 로 독립 라이브러리를 만든다.

    기존 데이터는 옮기지도 지우지도 않는다 — 경로만 바꾸면 그쪽 라이브러리로 전환된다.
    """
    raw = (body.path or "").strip()
    if not raw:
        store.save_library_root(None)  # 기본 경로로 복귀
        return _library_stats()

    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise HTTPException(400, "전체 경로(절대 경로)를 입력하세요. 예: D:\\PaperLibrary")
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise HTTPException(400, f"이 폴더를 쓸 수 없습니다: {e}")

    store.save_library_root(p)
    with store.connect() as conn:  # 새 위치에 스키마 생성
        store.list_documents(conn)
    return _library_stats()


# ══════════════════════════════════════════════════════════════════
# 유료 API 스위치 — 상단 배지를 눌러 바로 잠근다 (.env 안 열어도 됨)
#
# 끄기는 언제나 안전하므로 그냥 통과. 켜기는 프론트에서 확인창을 한 번 받는다.
# 값은 DB에 남아 서버를 껐다 켜도 유지된다(잠근 채로 재시작해도 다시 안 열림).
# ══════════════════════════════════════════════════════════════════
class PaidToggle(BaseModel):
    enabled: bool


@app.post("/api/paid/toggle")
def toggle_paid(body: PaidToggle):
    import guard

    if guard.offline_mode():
        return {
            "paid_apis_enabled": False,
            "message": "완전 로컬 모드(OFFLINE_MODE=true)에서는 유료 API를 켤 수 없습니다.",
        }
    with store.connect() as conn:
        store.set_state(conn, store.PAID_STATE_KEY, "1" if body.enabled else "0")
    guard.set_paid_override(body.enabled)
    return {
        "paid_apis_enabled": guard.paid_apis_enabled(),
        "message": "유료 API를 켰습니다. 번역·그림분석·AI 요약에서 과금이 발생합니다."
        if body.enabled
        else "🔒 유료 API를 잠갔습니다. 이제 돈 나가는 호출은 전부 차단됩니다.",
    }


def _restore_paid_override() -> None:
    """서버 시작 시 화면 스위치 값을 복원. 저장된 게 없으면 .env 를 따른다."""
    import guard

    try:
        with store.connect() as conn:
            v = store.get_state(conn, store.PAID_STATE_KEY)
    except Exception:
        return
    if v in ("0", "1"):
        guard.set_paid_override(v == "1")


_restore_paid_override()


@app.post("/api/maintenance/clean-text")
def clean_text():
    """깨진 글리프·수식 잔해를 이미 저장된 블록에서 걷어낸다 (재추출 없이, 비용 0)."""
    import extract
    import local_search

    with store.connect() as conn:
        stats = extract.clean_stored_blocks(conn)
        stats["reindexed_blocks"] = local_search.rebuild_all(conn)
    return stats


def _translate_model_or_none() -> str | None:
    try:
        import translate

        return translate.current_model_name()
    except Exception:
        return None  # TRANSLATE_PROVIDER 오타 등 — 상태 점검 자체는 죽이지 않는다


def _translate_cost_or_none() -> dict | None:
    try:
        import translate

        return translate.cost_hint()
    except Exception:
        return None


@app.get("/api/health")
def health_check():
    import chat_memory
    import guard
    import users

    with store.connect() as conn:
        active = users.get_active(conn)
        mem_on = chat_memory.is_enabled(conn)
    return {
        "ok": True,
        "paid_apis_enabled": guard.paid_apis_enabled(),
        # None이면 .env 값을 따르는 중, True/False면 화면 스위치가 이기는 중
        "paid_override": guard.paid_override(),
        "offline_mode": guard.offline_mode(),
        "search_mode": os.getenv("SEARCH_MODE", "ai"),
        # 번역이 어느 공급자·모델로 나가는지 — 돈이 어디서 빠지는지 화면·점검에서 확인할 수 있게
        "translate_provider": os.getenv("TRANSLATE_PROVIDER", "gemini").strip().lower() or "gemini",
        "translate_model": _translate_model_or_none(),
        "translate_cost": _translate_cost_or_none(),
        "active_user": active,
        "memory_enabled": mem_on,
    }


# ══════════════════════════════════════════════════════════════════
# 배포용 정적 서빙 — 빌드된 프론트(dist)를 이 서버가 직접 내보낸다.
#
# 개발 중에는 Vite(5173)가 화면을, 이 서버(8100)가 API를 맡는다. 하지만 배포 PC에
# Node를 깔게 하고 싶지 않으므로, dist 가 있으면 **한 포트(8100)에서 화면까지** 준다.
# dist 가 없으면(=개발 환경) 이 블록은 통째로 건너뛴다 → 기존 동작 그대로.
#
# ⚠️ 이 라우트는 파일 맨 끝에 있어야 한다. catch-all 이라 위에 두면 /api/* 를 삼킨다.
# ══════════════════════════════════════════════════════════════════
DIST_DIR = PROJECT_ROOT / "webapp" / "frontend" / "dist"

if DIST_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles  # noqa: E402

    if (DIST_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        """SPA 진입점. 없는 /api 경로까지 index.html 로 덮으면 디버깅이 지옥이 된다."""
        if full_path.startswith("api/"):
            raise HTTPException(404, "없는 API 경로입니다.")
        asset = DIST_DIR / full_path
        if full_path and asset.is_file():
            return FileResponse(asset)
        return FileResponse(DIST_DIR / "index.html")
