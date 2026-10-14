"""
Gemini 모델 객관식 선택기 (Article_Battery 공용 모듈)

사용자가 .env 또는 코드에서 **번호(1, 2, 3 …)만으로** Gemini 모델을 지정할 수 있도록
중앙 레지스트리를 제공한다. 문자열(모델명) 직접 지정도 호환된다.

사용 방법
---------
1) .env 에서 번호로 지정 (권장)::

    GEMINI_VISION_MODEL=2
    GEMINI_TEXT_MODEL=1

2) .env 에서 모델명으로 직접 지정::

    GEMINI_TEXT_MODEL=gemini-2.5-pro

3) 코드에서 기본값으로 사용::

    from _models import get_model
    model_name = get_model(os.getenv("GEMINI_TEXT_MODEL"), default_num=1)
"""

from __future__ import annotations


# ── 모델 레지스트리 ─────────────────────────────────────────────
# 번호 ↔ 모델명 매핑. Gemini 3.x 등이 나오면 아래에 한 줄만 추가하면 된다.
#
# [1.5 세대]
# #1 : gemini-1.5-flash           → 가장 저렴·빠름. 번역/요약 기본값
# #2 : gemini-1.5-pro             → 고품질 멀티모달. 이미지 해설 기본값
# #7 : gemini-1.5-flash-8b        → 1.5 Flash 의 8B 경량판. 초저가·초고속
# #8 : gemini-1.5-pro-latest      → 1.5 Pro "latest" 별칭 (자동 최신 패치 추적)
# #9 : gemini-1.5-flash-latest    → 1.5 Flash "latest" 별칭
#
# [2.0 세대]
# #5 : gemini-2.0-flash           → 2.0 Flash (안정)
# #6 : gemini-2.0-flash-lite      → 2.0 Flash Lite (초경량)
# #10: gemini-2.0-pro-exp         → 2.0 Pro 실험 프리뷰 ⚠️ 실험 모델
# #11: gemini-2.0-flash-thinking-exp → Thinking 특화 실험 ⚠️ 응답 포맷 상이
#
# [2.5 세대, 2026-Q1 현행]
# #3 : gemini-2.5-flash           → 최신 Flash. 한국어 안정성↑
# #4 : gemini-2.5-pro             → 최신 Pro. 최고 품질·최고 비용
# #12: gemini-2.5-flash-lite      → 2.5 Flash Lite (2.5 세대 최경량)
#
# ⚠️ "-exp" 또는 "-thinking-exp" 는 Google 이 사전 경고 없이 회수·파라미터 변경 가능.
#    프로덕션 자동화 용도로는 #3·#4 등 정식 stable 모델을 권장.
# ↑ 새 모델은 아래 딕셔너리에 `N: "gemini-..."` 를 추가하고 위 주석도 함께 갱신.
MODEL_CHOICES: dict[int, str] = {
    # 1.5 세대 (기본값 2종)
    1: "gemini-1.5-flash",
    2: "gemini-1.5-pro",
    # 2.5 세대 최신 stable
    3: "gemini-2.5-flash",
    4: "gemini-2.5-pro",
    # 2.0 세대
    5: "gemini-2.0-flash",
    6: "gemini-2.0-flash-lite",
    # 1.5 세대 경량/확장
    7: "gemini-1.5-flash-8b",
    8: "gemini-1.5-pro-latest",
    9: "gemini-1.5-flash-latest",
    # 2.0 세대 실험
    10: "gemini-2.0-pro-exp",
    11: "gemini-2.0-flash-thinking-exp",
    # 2.5 세대 경량
    12: "gemini-2.5-flash-lite",
}


def get_model(choice: str | int | None, default_num: int) -> str:
    """
    번호/문자열/None 을 모두 받아 실제 Gemini 모델명을 반환.

    - choice 가 None 이거나 빈 문자열이면 `default_num` 에 해당하는 모델 반환
    - choice 가 정수로 파싱되면 레지스트리 조회 (미등록 번호는 default 로 폴백)
    - 그 외 문자열은 모델명으로 간주하여 그대로 반환 (호환성 유지)
    """
    if default_num not in MODEL_CHOICES:
        raise ValueError(f"default_num={default_num} 은 MODEL_CHOICES 에 없습니다.")

    if choice is None or (isinstance(choice, str) and not choice.strip()):
        return MODEL_CHOICES[default_num]

    # 번호로 온 경우
    try:
        num = int(str(choice).strip())
    except ValueError:
        # 숫자가 아니면 → 모델명 문자열로 간주
        return str(choice).strip()

    if num in MODEL_CHOICES:
        return MODEL_CHOICES[num]

    print(
        f"[WARN] GEMINI 모델 번호 #{num} 는 등록되어 있지 않습니다. "
        f"기본값 #{default_num} ({MODEL_CHOICES[default_num]}) 로 폴백합니다."
    )
    return MODEL_CHOICES[default_num]


def describe_choices() -> str:
    """CLI 로그용 모델 목록 문자열."""
    return "\n".join(f"    #{k}: {v}" for k, v in MODEL_CHOICES.items())


def resolve_and_report(env_value: str | int | None, default_num: int, label: str) -> str:
    """모델을 해석하고 현재 선택 결과를 한 줄로 로깅해 반환."""
    resolved = get_model(env_value, default_num)
    # 어떤 번호로 매칭됐는지 역조회 (가능한 경우)
    matched_num = next((k for k, v in MODEL_CHOICES.items() if v == resolved), None)
    tag = f"#{matched_num}" if matched_num is not None else "custom"
    print(f"[INFO] {label} = {resolved} ({tag})")
    return resolved
