"""업로드된 PDF 처리 파이프라인: 추출 → 참고문헌 → 번역 → (선택) RAG 색인.

백그라운드 태스크로 실행되며, 단계마다 documents.status/progress를 갱신해
프론트가 진행률을 폴링할 수 있게 한다.

RAG 색인(GCS 업로드 + Vertex AI Search import)은 선택 단계다. 켜두면 업로드한 논문이
챗봇 답변의 근거로도 쓰인다(App Builder 크레딧 차감 — 검색용이라 크레딧 적용 대상).
"""

from __future__ import annotations

import os
import subprocess
import traceback
from pathlib import Path

import local_search
import references as refs_mod
import store
from extract import extract_blocks
from guard import paid_apis_enabled
from translate import TranslationUsage, current_model_name, translate_blocks, usage_line

GCS_BUCKET = os.getenv("BATTERY_RAG_GCS_BUCKET", "")


def _rag_index_enabled() -> bool:
    """색인은 GCS 업로드가 필요 → 하드락·오프라인 모드 양쪽에 묶인다.

    (paid_apis_enabled 가 오프라인 모드면 무조건 False 를 돌려주므로 여기서 함께 차단된다.)
    """
    설정됨 = bool(GCS_BUCKET and os.getenv("BATTERY_RAG_GCP_PROJECT_ID", ""))   # 버킷·프로젝트를 .env 에 넣어야 켜진다
    return 설정됨 and paid_apis_enabled() and os.getenv("ENABLE_RAG_INDEX", "true").lower() == "true"


def process_document(doc_id: str) -> None:
    """업로드 직후 백그라운드에서 호출. 실패해도 예외를 밖으로 던지지 않는다(상태에 기록).

    notes: 건너뜀/부분실패 사유 누적 — 마지막 ready 상태에 함께 저장해 카드에 표시된다
    (중간 set_status의 error는 마지막 갱신에 덮이므로 여기 모아서 최종 반영).
    """
    notes: list[str] = []
    try:
        with store.connect() as conn:
            doc = store.get_document(conn, doc_id)
            if not doc:
                return
            pdf_path = Path(doc["pdf_path"])
            # 업로드 시 체크박스 (기본 OFF — 유료 위험은 사용자 판단에 맡긴다)
            opt_translate = bool(doc["opt_translate"])
            opt_analyze = bool(doc["opt_analyze"])
            store.set_status(conn, doc_id, "extracting", 10)

        # 1) 블록 추출 (텍스트/그림/표를 읽기순서로)
        images_dir = store.IMAGES_DIR / doc_id
        result = extract_blocks(pdf_path, images_dir)
        block_dicts = [b.to_dict() for b in result.blocks]

        with store.connect() as conn:
            store.save_blocks(conn, doc_id, block_dicts, result.page_count)
            store.save_refs(conn, doc_id, refs_mod.extract_references(block_dicts))
            # 로컬 FTS5 색인 — 무료·오프라인이라 하드락과 무관하게 항상 수행한다.
            local_search.index_document(conn, doc_id)
            # 라이브러리 표시용: 진짜 제목 + 표지(1페이지 렌더). 전부 로컬·비용 0.
            import library

            good = library.resolve_title(conn, doc_id, doc["filename"], doc["title"])
            if good:
                conn.execute("UPDATE documents SET title=? WHERE doc_id=?", (good, doc_id))
            library.make_cover(pdf_path, images_dir)
            store.set_status(conn, doc_id, "translating", 40)

        # 2) 번역 (체크박스 ON + 캐시 미스분만) — 배치마다 즉시 저장하므로 중단돼도 보존된다
        #    (재실행 시 남은 블록만 번역 → 재과금 0). 실패해도 원문 리더는 볼 수 있게 계속 진행.
        try:
            model = current_model_name()
            if not opt_translate:
                pending = []  # 사용자가 번역을 안 켰음 — 조용히 스킵 (기본, 0원)
            elif not paid_apis_enabled():
                notes.append("번역 건너뜀(하드락) — 원문 리더 사용 가능")
                pending = []
            else:
                with store.connect() as conn:
                    pending = store.untranslated_blocks(conn, doc_id)
            if pending:
                usage = TranslationUsage()
                # 활성 사용자의 API 키를 쓴다(없으면 translate가 .env로 폴백).
                import users

                with store.connect() as conn:
                    active_key = users.active_api_key(conn)

                def on_batch(mapping: dict[int, str], done: int, total: int) -> None:
                    with store.connect() as c:
                        store.save_translations(c, doc_id, mapping, model)
                        # 번역 구간은 전체 진행률 40~80% 에 매핑
                        store.set_status(c, doc_id, "translating", 40 + int(40 * done / max(total, 1)))

                try:
                    translate_blocks(pending, usage, on_batch=on_batch, api_key=active_key)
                finally:
                    print(usage_line(doc_id, usage), flush=True)  # 중간에 실패해도 쓴 만큼은 남긴다
                # 번역이 생겼으니 로컬 색인을 갱신 → 한국어 질문으로도 검색된다.
                with store.connect() as conn:
                    local_search.index_document(conn, doc_id)
        except Exception as e:
            notes.append(f"번역 일부 실패: {e}")

        # 3) RAG 색인 (선택) — 챗봇이 이 논문을 근거로 답할 수 있게 함. 하드락 시 건너뜀.
        if _rag_index_enabled():
            with store.connect() as conn:
                store.set_status(conn, doc_id, "indexing", 80)
            try:
                _index_to_rag(pdf_path)
            except Exception as e:
                notes.append(f"클라우드 색인 실패(검색엔 미반영): {e}")

        # 4) 그림·표 AI 분석 (체크박스 ON일 때만, 유료) — 그림 단위 캐시라 중단돼도 보존
        if opt_analyze:
            if paid_apis_enabled():
                try:
                    import figure_analysis
                    import users

                    with store.connect() as conn:
                        active_key = users.active_api_key(conn)
                        store.set_status(conn, doc_id, "indexing", 92)
                    figure_analysis.analyze_document(doc_id, active_key)
                except Exception as e:
                    notes.append(f"그림 분석 일부 실패: {e}")
            else:
                notes.append("그림 분석 건너뜀(하드락)")

        with store.connect() as conn:
            store.set_status(conn, doc_id, "ready", 100, error=" · ".join(notes) or None)

    except Exception:
        with store.connect() as conn:
            store.set_status(conn, doc_id, "failed", 0, error=traceback.format_exc()[-800:])


def translate_document(doc_id: str) -> None:
    """[실행 버튼용] 등록된 논문의 미번역 블록을 지금 번역. 배치마다 저장, 완료 후 재색인.

    하드락이면 translate가 PaidApiLocked를 던지므로 상태에 사유만 남기고 끝난다.
    """
    import users

    try:
        model = current_model_name()
        with store.connect() as conn:
            if not store.get_document(conn, doc_id):
                return
            pending = store.untranslated_blocks(conn, doc_id)
            active_key = users.active_api_key(conn)
            if pending:
                store.set_status(conn, doc_id, "translating", 40)

        if not pending:
            return

        def on_batch(mapping: dict[int, str], done: int, total: int) -> None:
            with store.connect() as c:
                store.save_translations(c, doc_id, mapping, model)
                store.set_status(c, doc_id, "translating", 40 + int(55 * done / max(total, 1)))

        usage = TranslationUsage()
        try:
            translate_blocks(pending, usage, on_batch=on_batch, api_key=active_key)
        finally:
            print(usage_line(doc_id, usage), flush=True)  # 중간에 실패해도 쓴 만큼은 남긴다
        with store.connect() as conn:
            local_search.index_document(conn, doc_id)
            store.set_status(conn, doc_id, "ready", 100)
    except Exception as e:
        with store.connect() as conn:
            store.set_status(conn, doc_id, "ready", 100, error=f"번역 실행 실패: {str(e)[:180]}")


def _index_to_rag(pdf_path: Path) -> None:
    """GCS 업로드 후 데이터스토어 재색인 트리거.

    gcloud CLI를 쓰는 이유: 파이썬 클라이언트는 ADC가 필요한데 이 환경엔 없고,
    사용자는 `gcloud auth login`만 해둔 상태다(rag/search_client.py와 동일한 방침).
    """
    dest = f"gs://{GCS_BUCKET}/papers/{pdf_path.name}"
    subprocess.run(
        ["gcloud", "storage", "cp", str(pdf_path), dest],
        check=True, capture_output=True, shell=True, timeout=300,
    )
    # 색인 import는 시간이 걸리는 비동기 작업 — 트리거만 하고 기다리지 않는다.
    import json as _json
    import urllib.request

    token = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True, shell=True,
    ).stdout.strip()
    project = os.getenv("BATTERY_RAG_GCP_PROJECT_ID", "")
    ds = os.getenv("BATTERY_RAG_DATASTORE_ID", "battery-papers-datastore")
    url = (
        f"https://discoveryengine.googleapis.com/v1/projects/{project}/locations/global"
        f"/collections/default_collection/dataStores/{ds}/branches/0/documents:import"
    )
    body = _json.dumps(
        {
            "gcsSource": {"inputUris": [f"gs://{GCS_BUCKET}/papers/*.pdf"], "dataSchema": "content"},
            "reconciliationMode": "INCREMENTAL",
        }
    ).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Goog-User-Project", project)
    urllib.request.urlopen(req, timeout=30).read()
