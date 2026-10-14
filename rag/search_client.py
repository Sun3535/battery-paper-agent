"""논문 데이터스토어에 자연어로 질의 → LLM 요약 + 근거 인용(어느 논문인지) 반환.

인증: 파이썬 클라이언트 라이브러리의 ADC 대신, 이미 로그인된 gcloud CLI 토큰을 사용한다
(`gcloud auth print-access-token`). 호야가 `gcloud auth login`만 해두면 별도의
`gcloud auth application-default login` 없이 바로 동작한다.

전제: datastore_setup + gcs_sync + 문서 색인(import) 완료, Enterprise+LLM 엔진 생성 완료.
과금: LLM 요약 생성분은 App Builder(Agent Builder) SKU → GenAI App Builder 크레딧으로 차감.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request

from . import config, credit_guard

_HOST = "https://discoveryengine.googleapis.com"


def _access_token() -> str:
    # shell=False, gcloud은 PATH에 있음. 실패 시 명확한 안내.
    try:
        out = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, check=True, shell=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise SystemExit(
            "gcloud 토큰 획득 실패. 먼저 `gcloud auth login` 후 다시 실행하세요.\n" + str(e)
        )


def _serving_config_path() -> str:
    return (
        f"projects/{config.GCP_PROJECT_ID}/locations/{config.GCP_LOCATION}"
        f"/collections/default_collection/engines/{config.SEARCH_APP_ID}"
        f"/servingConfigs/default_search"
    )


def ask(
    question: str,
    summary_result_count: int = 5,
    page_size: int = 8,
    memory_block: str = "",
) -> dict:
    """질문 → {'summary': str, 'citations': [{'title','gcs_uri','snippet'}...], 'raw': ...}.

    summarySpec 로 LLM 그라운딩 요약을 받고, results 에서 인용 문서 메타데이터를 추출한다.
    """
    # 하드락 (2026-07-15 호야 지시) — 실제 청구액 확인 전까지 크레딧 소비 금지.
    # 해제: Article_Battery/.env 에서 PAID_APIS_ENABLED=true
    if os.getenv("PAID_APIS_ENABLED", "false").strip().lower() != "true":
        return {
            "summary": (
                "🔒 유료 API 하드락 (PAID_APIS_ENABLED=false) — Vertex AI Search 호출을 차단했습니다. "
                "실제 청구액 확인 후 .env에서 true로 바꿔 해제하세요."
            ),
            "citations": [],
        }

    if not config.GCP_PROJECT_ID:
        return {"summary": "BATTERY_RAG_GCP_PROJECT_ID 미설정. rag/config.py 또는 .env 확인.", "citations": []}

    url = f"{_HOST}/v1/{_serving_config_path()}:search"
    body = {
        "query": question,
        "pageSize": page_size,
        "contentSearchSpec": {
            "summarySpec": {
                "summaryResultCount": summary_result_count,
                "includeCitations": True,
                "ignoreAdversarialQuery": True,
                "modelSpec": {"version": "stable"},
                "modelPromptSpec": {
                    # memory_block: 과거 Q&A 기억 (chat_memory). 비어 있으면 입력 토큰 증가분 0.
                    "preamble": (
                        "너는 이차전지 분야 연구 보조원이다. 제공된 논문 발췌만 근거로, "
                        "한국어로 정확하게 답하라. 발췌에 없는 내용은 추측하지 말고 '자료 없음'이라고 밝혀라. "
                        "수치는 원문 그대로 인용하라. 학술 용어는 영어 원문을 유지하라."
                        + (f"\n\n{memory_block}" if memory_block else "")
                    )
                },
            },
            "snippetSpec": {"returnSnippet": True},
        },
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {_access_token()}")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Goog-User-Project", config.GCP_PROJECT_ID)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"summary": f"[HTTP {e.code}] {e.read().decode('utf-8', 'replace')[:400]}", "citations": []}

    summary = (payload.get("summary") or {}).get("summaryText", "")

    citations = []
    for result in payload.get("results", []):
        doc = result.get("document", {})
        derived = doc.get("derivedStructData", {}) or {}
        link = derived.get("link", "")  # gs://... 원본 경로
        title = derived.get("title") or link.rsplit("/", 1)[-1]
        snippets = derived.get("snippets", [])
        snippet_text = snippets[0].get("snippet", "") if snippets else ""
        citations.append({"title": title, "gcs_uri": link, "snippet": snippet_text})

    # LLM 요약 1회 호출을 비용으로 기록(정확 단가는 실측 후 보정; 보수적 추정치).
    credit_guard.record_usage(0.004)  # 대략 $0.004/answer 가정 — 실 청구서로 나중에 캘리브레이션

    return {"summary": summary, "citations": citations, "raw": payload}


def _print_result(q: str, res: dict) -> None:
    print(f"\n[질문] {q}\n")
    print("[요약]")
    print(res.get("summary") or "(요약 없음 — 색인 미완료이거나 관련 문서 없음)")
    print("\n[근거 논문]")
    for i, c in enumerate(res.get("citations", []), 1):
        print(f"  {i}. {c['title']}")
        if c.get("gcs_uri"):
            print(f"     {c['gcs_uri']}")
        if c.get("snippet"):
            print(f"     …{c['snippet'][:160]}")


if __name__ == "__main__":
    import sys

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    q = " ".join(sys.argv[1:]) or "최근 실리콘 음극재 연구에서 사이클 수명을 개선하는 방법은?"
    _print_result(q, ask(q))
    print("\n" + credit_guard.status_report())
