"""로컬 검색 구절 → Gemini API로 근거 기반 요약 답변 (Vertex 없이 동작하는 RAG).

왜 필요한가 (조건2): Vertex AI Search는 GCP 프로젝트·크레딧이 있어야 쓴다. 배포받은 사용자
중엔 Vertex가 아예 없는 사람이 많다. 그런데 우리는 이미 **로컬 FTS5로 관련 구절을 무료로**
찾고 있으므로, 그 구절을 Gemini API에 넘겨 요약시키면 API 키만으로 같은 역할을 한다.
오히려 로컬 색인에는 **그림 AI 분석문까지** 들어 있어 Vertex 경로보다 답이 나은 경우가 있다.

비용: 로컬 검색은 0원. 이 요약 호출만 API 키로 과금(짧은 프롬프트라 질문당 수 원 이하).
"""

from __future__ import annotations

import os
import re

SYSTEM_RULE = """너는 이차전지 분야 연구 보조원이다.

규칙:
1. **제공된 발췌만 근거로** 답하라. 발췌에 없으면 추측하지 말고 "제공된 자료에는 없습니다"라고 밝혀라.
2. 학술 용어·단위·화학식은 영어 원문 그대로 두고, 서술어만 한국어로 옮겨라.
   (옳음: "이 cathode의 capacity retention이 높다" / 틀림: "이 음극의 용량 유지율")
3. 수치는 발췌에 있는 그대로만 인용하라. 반올림하거나 만들어내지 마라.
4. 근거로 쓴 발췌 번호를 [1] [2] 형태로 문장 끝에 붙여라.
5. 마크다운 제목(##)은 쓰지 말고, 3~6문장으로 간결히 답하라."""

MAX_PASSAGE_CHARS = 700  # 발췌 1건 상한 (비용 통제)
MAX_PASSAGES = 8
# 논문 1편 통독 모드(scope)에서는 문단 수 제한을 크게 푼다 — 논문 전체를 읽혀야 정확해진다
MAX_PASSAGES_FULL_DOC = 400


def build_prompt(
    question: str, results: list[dict], extra_context: str = "", full_doc: bool = False
) -> tuple[str, list[str]]:
    """로컬 검색 결과 → 프롬프트. (프롬프트, 출처목록) 반환.

    full_doc=True (논문 1편 통독 모드)면 문단 수 상한을 크게 풀어 논문 전체를 넣는다.
    """
    limit = MAX_PASSAGES_FULL_DOC if full_doc else MAX_PASSAGES
    lines, sources = [], []
    n = 0
    for g in results:
        for p in g.get("passages", []):
            if n >= limit:
                break
            n += 1
            text = re.sub(r"[「」]", "", p.get("text", ""))  # 하이라이트 마커 제거
            text = re.sub(r"\s+", " ", text)[:MAX_PASSAGE_CHARS]
            lines.append(f"[{n}] ({g.get('title', '?')} p{p.get('page', '?')}) {text}")
            sources.append(f"{g.get('title', '?')} p{p.get('page', '?')}")

    body = "\n".join(lines) or "(관련 발췌 없음)"
    ctx = f"\n\n{extra_context}" if extra_context else ""
    prompt = f"[논문 발췌]\n{body}{ctx}\n\n[질문]\n{question}\n\n위 규칙대로 답하라."
    return prompt, sources


def local_llm_available() -> bool:
    """사내 PC에서 도는 로컬 LLM(Ollama 호환)이 살아 있는지. 외부 통신 아님."""
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(f"{_local_host()}/api/tags", timeout=2).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def _local_host() -> str:
    return os.getenv("LOCAL_LLM_HOST", "http://127.0.0.1:11434").rstrip("/")


def summarize_local(
    question: str, results: list[dict], extra_context: str = "", full_doc: bool = False
) -> tuple[str, list[str]]:
    """**로컬 LLM**으로 근거 요약 (Ollama 호환 API).

    사내망 배포용 — 논문 내용이 이 PC 밖으로 **나가지 않는다**. 회사가 로그인을 막는 이유가
    데이터 유출 방지라면, 외부 LLM API(Gemini 등)도 같은 유출에 해당하므로 이 경로를 쓴다.

    준비: Ollama 설치 후 `ollama pull qwen2.5:7b` (또는 사내 승인 모델).
    설정: .env  LOCAL_LLM_HOST=http://127.0.0.1:11434  /  LOCAL_LLM_MODEL=qwen2.5:7b
    """
    import json as _json
    import urllib.request

    prompt, sources = build_prompt(question, results, extra_context, full_doc)
    model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
    body = _json.dumps(
        {
            "model": model,
            "prompt": f"{SYSTEM_RULE}\n\n{prompt}",
            "stream": False,
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{_local_host()}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    return (data.get("response") or "").strip(), sources


def summarize(
    question: str,
    results: list[dict],
    api_key: str,
    extra_context: str = "",
    full_doc: bool = False,
) -> tuple[str, list[str]]:
    """Gemini API로 근거 요약. 실패하면 예외를 던진다(호출부가 다음 경로로 폴백).

    ⚠️ 이 경로는 논문 내용이 구글 서버로 전송된다. 사내 자료라면 summarize_local 을 쓸 것.
    """
    from google import genai
    from google.genai import types

    prompt, sources = build_prompt(question, results, extra_context, full_doc)
    client = genai.Client(api_key=api_key)
    model = os.getenv("ANSWER_MODEL", os.getenv("TRANSLATE_MODEL", "gemini-2.5-flash"))
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_RULE),
    )
    return (resp.text or "").strip(), sources
