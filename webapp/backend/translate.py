"""논문 텍스트 → 연구자 문체 한국어 번역 (기본 Gemini, 선택 Claude).

공급자 선택: `.env` TRANSLATE_PROVIDER = gemini(기본) | claude
  - gemini : 이 파일의 Gemini 경로(사용자 API 키 또는 Vertex).
  - claude : translate_claude.py (Anthropic API, ANTHROPIC_API_KEY). 사용자 Gemini 키와 무관.
  번역 규칙(SYSTEM_RULE)·블록 묶기·캐시는 공급자와 상관없이 여기서 한 번만 정한다.
  새 공급자(사내 API 등)는 translate_batch 의 갈림 한 곳과 translate_claude.py 같은 파일 하나를 더하면 된다.

언어 규칙 (사용자 지정, 2026-07-14):
  - 학술 용어·고유명사·화학식·단위·약어는 **영어 그대로 유지**한다.
    (cathode, electrolyte, coulombic efficiency, SEI, XRD, Li-ion, DFT, mAh/g …)
    억지로 한글화하면 오히려 읽기 어려워지기 때문. 실제 연구자들이 쓰는 문체가 기준.
  - 서술어·동사·접속사·일반 어휘는 한국어로 옮긴다.
  예) "The cathode exhibits high capacity retention after 100 cycles."
    → "이 cathode는 100 cycles 후에도 높은 capacity retention을 보인다."

비용 주의: 이 번역은 **Gemini API 직접 호출**이라 GenAI App Builder 크레딧으로 차감되지
않는다(그 크레딧은 Vertex AI Search 전용). 실제 요금이 나가므로:
  - 기본 모델은 flash 계열(저가)
  - 번역 결과는 DB에 캐시 → 같은 블록은 두 번 번역하지 않는다(재열람 무료)
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

SYSTEM_RULE = """너는 이차전지·재료과학 논문을 한국 연구자에게 읽히는 형태로 옮기는 번역가다.

핵심 규칙 — 이것을 반드시 지켜라:
1. 학술 용어, 전문 용어, 고유명사, 화학식, 단위, 약어는 **영어 원문 그대로** 둔다.
   예: cathode, anode, electrolyte, coulombic efficiency, capacity retention, cycle life,
   SEI, XRD, SEM, DFT, NEB, Li-ion, Na-ion, mAh/g, eV, Ehull, voltage window, overpotential
   → 절대 '음극재', '쿨롱 효율' 같이 한글로 바꾸지 마라. 억지 한글화는 오히려 읽기 어렵다.
2. 서술어, 동사, 조사, 접속사, 일반 어휘는 **자연스러운 한국어**로 옮긴다.
   예: "exhibits" → "보인다", "we investigated" → "우리는 조사했다", "however" → "그러나"
3. 숫자, 수치, 단위는 원문 그대로 정확히 유지한다. 절대 바꾸거나 반올림하지 마라.
4. 인용 표기([1], [2-4] 등)는 그대로 유지한다.
5. 원문에 없는 내용을 덧붙이지 마라. 설명·해설·의견을 추가하지 마라.
6. 번역문만 출력하라. "번역:", "다음은..." 같은 머리말을 붙이지 마라.

문체 예시:
  원문: The Li-rich cathode exhibits a high initial capacity of 250 mAh/g, but suffers from
        voltage decay during cycling.
  번역: 이 Li-rich cathode는 250 mAh/g의 높은 initial capacity를 보이지만, cycling 동안
        voltage decay를 겪는다."""

# 번역할 필요 없는 블록 판별
_SKIP_PATTERN = re.compile(r"^[\s\d\.\,\;\:\(\)\[\]\-–—/%+±×°]*$")
MAX_CHARS_PER_CALL = 6000  # 블록들을 이 크기까지 묶어 한 번에 번역 (호출 수·비용 절감)
PACING_SEC = 1.2  # Gemini rate limit 예방


@dataclass
class TranslationUsage:
    calls: int = 0
    input_chars: int = 0
    output_chars: int = 0
    # 공급자가 알려 준 실제 토큰 수(Claude 경로). 비용은 추정이 아니라 이 값으로 센다.
    input_tokens: int = 0
    output_tokens: int = 0


PROVIDERS = ("gemini", "claude")


class BatchError(RuntimeError):
    """묶음 하나가 쓸 수 있는 번역을 돌려주지 않음(거절·출력 잘림·형식 오류).

    이 묶음만 건너뛰고 다음 묶음으로 넘어간다. 잠금·키 없음·인증 오류처럼 "어느 묶음이든 똑같이 실패할" 오류는
    이 예외가 아니라 그대로 올라가 번역을 멈춘다(같은 실패를 묶음마다 되풀이하며 돈을 쓰지 않게).
    """


class TranslationIncomplete(RuntimeError):
    """끝까지 돌았지만 번역하지 못한 문단이 남음 — 사유를 사용자에게 보여 주기 위한 예외."""


def cost_hint() -> dict:
    """화면의 버튼·확인창에 보여 줄 번역 비용 어림값(원). 공급자·모델마다 다르다.

    claude 는 쪽당(실측 2026-10-14, Opus 5.5·논문 4편 63쪽 = 약 $3.13 → 쪽당 약 $0.05 ≈ ₩70.
    7쪽짜리 짧은 글은 쪽당 ₩40, 그림 설명이 긴 15쪽 논문은 ₩88 로 논문마다 2배쯤 차이 난다),
    gemini 는 편당(기존 어림값). 어림일 뿐이고, 실제 사용량은 서버 기록의 [번역] 줄에 토큰 수로 남는다.
    """
    if provider() == "claude":
        m = current_model_name()
        per_page = 2 if "haiku" in m else 35 if "sonnet" in m else 175 if "fable" in m else 70
        return {"provider": "claude", "model": m, "per_page_krw": per_page, "per_paper_krw": None}
    return {"provider": "gemini", "model": current_model_name(), "per_page_krw": None, "per_paper_krw": 121}


def usage_line(doc_id: str, usage: TranslationUsage) -> str:
    """번역 한 건이 끝난 뒤 서버 기록에 남기는 한 줄 — 호출 수와 (공급자가 알려 준) 실제 토큰 수."""
    line = f"[번역] {doc_id} · {provider()} · {current_model_name()} · 호출 {usage.calls}회"
    if usage.input_tokens or usage.output_tokens:
        line += f" · 토큰 입력 {usage.input_tokens:,} / 출력 {usage.output_tokens:,}"
    else:
        line += f" · 글자 입력 {usage.input_chars:,} / 출력 {usage.output_chars:,}"
    return line


def provider() -> str:
    """번역 공급자. 모르는 값이면 조용히 Gemini 로 떨어지지 않고 멈춘다(엉뚱한 곳에 과금 방지)."""
    p = os.getenv("TRANSLATE_PROVIDER", "gemini").strip().lower() or "gemini"
    if p not in PROVIDERS:
        raise RuntimeError(f"TRANSLATE_PROVIDER 값을 알 수 없습니다: {p!r} (가능: {', '.join(PROVIDERS)})")
    return p


def current_model_name() -> str:
    """지금 번역에 쓰이는 모델 이름 — 번역 캐시(translations.model)에 기록된다."""
    if provider() == "claude":
        import translate_claude

        return translate_claude.model_name()
    return os.getenv("TRANSLATE_MODEL", "gemini-2.5-flash")


def ready(conn) -> tuple[bool, str]:
    """번역을 시작해도 되는지(자격증명이 있는지)와, 안 될 때 보여 줄 안내."""
    if provider() == "claude":
        import translate_claude

        return translate_claude.has_credentials(), translate_claude.NO_KEY_MESSAGE
    import guard

    return bool(guard.usable_api_key(conn)), guard.NO_KEY_MESSAGE


def needs_translation(text: str) -> bool:
    """숫자·기호만 있는 블록, 너무 짧은 블록은 번역하지 않는다(비용 낭비 방지)."""
    t = (text or "").strip()
    if len(t) < 3:
        return False
    if _SKIP_PATTERN.match(t):
        return False
    return True


def _resolve_channel() -> tuple[str, str]:
    """호출 채널 결정: 활성 사용자의 선택이 최우선, 없으면 .env TRANSLATE_CHANNEL.

    반환 (channel, gcp_project). channel: 'aistudio' | 'vertex'
    """
    try:
        import store
        import users

        with store.connect() as conn:
            cred = users.active_credential(conn)
        if cred["kind"] == "credit":
            return "vertex", cred["project"]
        if cred["kind"] in ("free", "paid"):
            return "aistudio", ""
    except Exception:
        pass  # 사용자 설정을 못 읽으면 .env 로 폴백
    return os.getenv("TRANSLATE_CHANNEL", "aistudio").strip().lower(), ""


def _get_client_and_model(api_key: str | None = None) -> tuple[object, str]:
    """번역 채널을 환경변수로 선택.

    TRANSLATE_CHANNEL=aistudio → **각 사용자가 앱에 등록한 자기 AI Studio API 키**로 호출.
                                 사용량은 그 키 소유자에게 과금된다(배포 시 기본 모델).
    TRANSLATE_CHANNEL=vertex   → 이 PC의 gcloud 인증으로 Vertex AI 호출.
                                 프로젝트 소유자에게 과금되고, App Builder 크레딧은 적용되지 않는다.

    api_key: 활성 사용자의 키. 없으면 .env GEMINI_API_KEY(선택적 폴백)를 쓰고, 그것도 없으면 에러.
    """
    from guard import require_paid_apis

    # 하드락 — 실제 청구액 확인 전까지 어떤 채널로도 번역 API를 부르지 않는다.
    require_paid_apis("번역(Gemini API)")

    from google import genai  # 지연 임포트 — 번역 안 쓰면 의존성 불필요

    model_name = os.getenv("TRANSLATE_MODEL", "gemini-2.5-flash")

    # 활성 사용자가 [크레딧]을 골랐으면 vertex 경로로 간다(키 대신 gcloud 인증 사용).
    channel, user_project = _resolve_channel()

    if channel == "vertex":
        project = user_project or os.getenv("BATTERY_RAG_GCP_PROJECT_ID", "")
        if not project:
            raise RuntimeError(
                "크레딧(Vertex) 경로에 쓸 GCP 프로젝트 ID가 없습니다. "
                "[사용자] → 크레딧 칸에 프로젝트 ID를 저장하세요."
            )
        location = os.getenv("TRANSLATE_VERTEX_LOCATION", "global")
        return genai.Client(vertexai=True, project=project, location=location), model_name

    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "사용할 API 키가 없습니다. 화면 우측 상단 [사용자]에서 본인 API 키를 등록한 뒤 "
            "이름을 클릭해 활성화하세요. (Gemini API 키 발급: https://aistudio.google.com/apikey)"
        )
    return genai.Client(api_key=key), model_name


def translate_batch(
    texts: list[str], usage: TranslationUsage | None = None, api_key: str | None = None
) -> list[str | None]:
    """여러 문단을 한 번의 호출로 번역. 입력 순서 그대로 같은 길이의 리스트를 반환.

    JSON 배열로 주고받아 블록 경계가 섞이지 않게 한다. api_key: 사용자별 키(옵션, Gemini 경로).
    None 인 자리는 "번역을 받지 못함" — 호출부가 저장하지 않는다(Claude 경로).
    """
    if not texts:
        return []
    if provider() == "claude":
        import translate_claude

        return translate_claude.translate_batch(texts, SYSTEM_RULE, usage)
    from google.genai import types

    client, model_name = _get_client_and_model(api_key)

    payload = json.dumps([{"i": i, "t": t} for i, t in enumerate(texts)], ensure_ascii=False)
    prompt = (
        "아래 JSON 배열의 각 항목 t를 위 규칙대로 번역하라.\n"
        '반드시 같은 길이의 JSON 배열로만 답하라. 형식: [{"i": 0, "t": "번역문"}, ...]\n'
        "코드블록 표시(```)를 붙이지 마라.\n\n"
        f"{payload}"
    )

    resp = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_RULE,
            response_mime_type="application/json",  # JSON 강제 → 파싱 실패율 감소
        ),
    )
    raw = (resp.text or "").strip()
    if usage:
        usage.calls += 1
        usage.input_chars += len(prompt)
        usage.output_chars += len(raw)

    # ```json 펜스 제거 후 파싱
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
        out = [""] * len(texts)
        for item in data:
            idx = int(item["i"])
            if 0 <= idx < len(texts):
                out[idx] = str(item.get("t", "") or "")
    except Exception as e:
        # 예전에는 여기서 원문을 그대로 돌려줘 "번역됨" 으로 저장됐다(영어가 번역본 자리에 영영 남는다).
        # 이제 이 묶음은 저장하지 않는다 — 원문은 리더가 어차피 보여 주고, 다시 실행하면 이 묶음만 다시 한다.
        raise BatchError(f"번역 응답을 읽지 못했습니다: {e}") from e
    # 번역문이 돌아오지 않은 자리는 None — 호출부가 저장하지 않는다(원문으로 채우지 않는다)
    return [out[i].strip() or None for i in range(len(texts))]


def translate_blocks(
    blocks: list[dict],
    usage: TranslationUsage | None = None,
    on_batch: "Callable[[dict[int, str], int, int], None] | None" = None,
    api_key: str | None = None,
) -> dict[int, str]:
    """블록 리스트(dict, extract.Block.to_dict 형태)를 번역해 {order: 번역문} 반환.

    - kind=text 와 그림/표 캡션(text 필드)을 모두 번역 대상으로 삼는다.
    - **같은 글은 한 번만 보낸다.** 캡션은 그림 블록과 캡션 글 블록 양쪽에 같은 글로 들어 있어,
      예전에는 두 번 번역했다(돈도 두 번, 문구도 서로 달라질 수 있었다). 한 번 번역해 양쪽에 같이 저장한다.
    - MAX_CHARS_PER_CALL 단위로 묶어 호출 수를 줄인다.
    - on_batch(mapping, done, total): 배치 하나가 끝날 때마다 호출된다. 호출부가 이 시점에
      DB에 저장하면 중간에 실패해도 그때까지의 번역이 보존된다(재실행 시 재과금 0).
    - 묶음 하나가 실패(BatchError)해도 **다음 묶음은 계속한다.** 예전에는 거기서 멈춰, 다시 눌러도
      같은 묶음에서 또 멈추고 그 뒤 문단은 영영 번역되지 않았다. 끝까지 돈 뒤, 번역하지 못한 문단이
      있으면 TranslationIncomplete 로 사유를 알린다(자동으로 다시 시도하지는 않는다 — 같은 실패에 돈을 또 쓰지 않게).
    """
    orders_of: dict[str, list[int]] = {}
    for b in blocks:
        text = (b.get("text") or "").strip()
        if text and needs_translation(text):
            orders_of.setdefault(text, []).append(b["order"])
    targets = list(orders_of)  # 서로 다른 글만, 처음 나온 순서대로

    # 배치 미리 구성 (진행률 계산용)
    batches: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for text in targets:
        if size + len(text) > MAX_CHARS_PER_CALL and cur:
            batches.append(cur)
            cur, size = [], 0
        cur.append(text)
        size += len(text)
    if cur:
        batches.append(cur)

    result: dict[int, str] = {}
    missing = 0  # 번역문을 받지 못한 문단 수(블록 기준)
    reasons: list[str] = []
    for i, batch in enumerate(batches, 1):
        try:
            translated = translate_batch(batch, usage, api_key=api_key)
        except BatchError as e:
            translated = [None] * len(batch)
            if str(e) not in reasons:
                reasons.append(str(e))
        # None(번역을 받지 못한 자리)은 담지 않는다 → 미번역으로 남아 다음 실행 때 그 블록만 다시 호출된다
        mapping: dict[int, str] = {}
        for text, ko in zip(batch, translated):
            if ko:
                for order in orders_of[text]:
                    mapping[order] = ko
            else:
                missing += len(orders_of[text])
        result.update(mapping)
        if on_batch:
            on_batch(mapping, i, len(batches))  # 배치별 즉시 저장 → 중단돼도 손실 없음
        if i < len(batches):
            time.sleep(PACING_SEC)

    if missing:
        why = " / ".join(reasons) if reasons else "모델이 일부 문단의 번역문을 돌려주지 않았습니다."
        raise TranslationIncomplete(
            f"문단 {missing}개를 번역하지 못했습니다 — {why} 다시 실행하면 남은 문단만 번역합니다."
        )
    return result
