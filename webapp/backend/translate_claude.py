"""번역 — Claude(Anthropic API) 채널.

켜는 법: `.env` (또는 실행 환경변수)에
    TRANSLATE_PROVIDER=claude
    ANTHROPIC_API_KEY=...            ← Claude Console 에서 발급. 사용량은 그 조직의 크레딧에서 차감
선택:
    CLAUDE_TRANSLATE_MODEL=claude-opus-5-5   (기본) | claude-sonnet-5-5 | claude-haiku-5-5
    CLAUDE_TRANSLATE_EFFORT=low              (기본) | medium | high
    ANTHROPIC_BASE_URL=https://...           ← Anthropic 호환 사내 게이트웨이를 쓸 때. SDK 가 직접 읽는다

번역 규칙(SYSTEM_RULE)·블록 묶기·캐시는 translate.py 가 그대로 쥐고 있고, 이 파일은
"문단 배열 → 번역 배열" 한 번의 호출만 맡는다. 다른 공급자(사내 API 등)를 붙일 때 이 파일을 본보기로 삼는다.

실패는 **실패 쪽으로** 처리한다: 거절·잘림·빠진 항목을 원문으로 채워 "번역됨"으로 저장하지 않는다.
저장되지 않은 블록은 미번역으로 남아, 다시 실행하면 그 블록만 호출된다(이미 번역된 블록 재과금 0).

참고: 번역 규칙 프롬프트는 약 700 토큰이라 프롬프트 캐시 최소 길이에 못 미친다 → 캐시 표시는 붙이지 않는다.
"""

from __future__ import annotations

import json
import os

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 32000  # 스트리밍으로 받으므로 넉넉히 — 번역문이 중간에 잘리면 그 배치를 통째로 다시 해야 한다

# 구조화 출력 — 항목 번호(i)와 번역문(t)의 배열. 블록 경계가 섞이지 않게 번호로 되찾는다.
_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"i": {"type": "integer"}, "t": {"type": "string"}},
                "required": ["i", "t"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

NO_KEY_MESSAGE = (
    "Claude 번역에 쓸 API 키가 없습니다. Article_Battery/.env 에 ANTHROPIC_API_KEY=... 를 넣고 "
    "앱을 다시 켜세요. (발급: https://platform.claude.com/settings/keys) "
    "사용량은 그 키가 속한 조직의 크레딧에서 차감됩니다."
)


class ClaudeTranslateError(RuntimeError):
    """Claude 번역 호출이 쓸 수 있는 결과를 돌려주지 않음(거절·잘림·형식 오류)."""


def model_name() -> str:
    return os.getenv("CLAUDE_TRANSLATE_MODEL", "").strip() or DEFAULT_MODEL


def effort() -> str:
    return os.getenv("CLAUDE_TRANSLATE_EFFORT", "").strip().lower() or "low"


def has_credentials() -> bool:
    """SDK 가 읽는 자격증명 환경변수가 있는지 — 호출 전에 미리 걸러 조용한 실패를 막는다."""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _client():
    import anthropic  # 지연 임포트 — Claude 채널을 안 쓰면 의존성 불필요

    # 자격증명·ANTHROPIC_BASE_URL 은 SDK 가 환경에서 읽는다(키를 코드로 옮겨 담지 않는다).
    return anthropic.Anthropic()


def translate_batch(texts: list[str], system_rule: str, usage=None, client=None) -> list[str | None]:
    """문단 배열을 한 번의 호출로 번역. 입력과 같은 길이의 리스트를 돌려준다.

    번역문이 돌아오지 않은 자리는 **None** — 호출부가 저장하지 않는다(원문으로 채우지 않는다).
    client: 테스트에서 가짜 클라이언트를 넣는 자리.
    """
    if not texts:
        return []
    from guard import require_paid_apis

    # 하드락 — 잠겨 있으면 클라이언트를 만들기도 전에 멈춘다.
    require_paid_apis("번역(Claude API)")
    if client is None:
        if not has_credentials():
            raise ClaudeTranslateError(NO_KEY_MESSAGE)
        client = _client()

    payload = json.dumps([{"i": i, "t": t} for i, t in enumerate(texts)], ensure_ascii=False)
    prompt = (
        "아래 JSON 배열의 각 항목 t를 위 규칙대로 번역하라.\n"
        "입력과 같은 개수의 항목을 items 배열에 담고, 각 항목의 i는 입력의 i를 그대로 쓴다.\n\n"
        f"{payload}"
    )

    # 출력이 길 수 있어 스트리밍으로 받는다(긴 응답의 HTTP 시간 초과 방지).
    with client.messages.stream(
        model=model_name(),
        max_tokens=MAX_TOKENS,
        system=system_rule,
        output_config={"effort": effort(), "format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()

    if usage is not None:
        u = message.usage
        usage.calls += 1
        usage.input_chars += len(prompt)
        usage.input_tokens += (
            (u.input_tokens or 0)
            + (getattr(u, "cache_creation_input_tokens", 0) or 0)
            + (getattr(u, "cache_read_input_tokens", 0) or 0)
        )
        usage.output_tokens += u.output_tokens or 0

    # 내용을 읽기 전에 왜 멈췄는지부터 본다.
    if message.stop_reason == "refusal":
        category = getattr(getattr(message, "stop_details", None), "category", None)
        raise ClaudeTranslateError(f"모델이 이 배치의 번역을 거절했습니다 (분류: {category or '알 수 없음'}).")
    if message.stop_reason == "max_tokens":
        raise ClaudeTranslateError("번역문이 출력 한도에서 잘렸습니다 — 배치를 줄여 다시 실행하세요.")

    raw = next((b.text for b in message.content if b.type == "text"), "")
    if usage is not None:
        usage.output_chars += len(raw)
    try:
        items = json.loads(raw)["items"]
    except Exception as e:
        raise ClaudeTranslateError(f"번역 응답을 읽지 못했습니다: {e}") from e

    out: list[str | None] = [None] * len(texts)
    for item in items:
        idx = int(item["i"])
        text = str(item.get("t", "")).strip()
        if 0 <= idx < len(texts) and text:
            out[idx] = text
    return out
