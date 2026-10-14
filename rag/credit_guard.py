"""GenAI App Builder 크레딧 잔액 추정 가드.

Blog/src/utils/vertex_billing_guard.py 와 같은 설계 철학(자체 누적 카운터로 잔액 추정)이지만,
이 모듈은 자동 차단(should_use)까지는 하지 않고 경고만 낸다 — 발행 파이프라인처럼 상시 자동
실행되는 게 아니라 호야가 수동으로 python -m rag.ask 를 실행하는 개인 리서치 도구라
호출 빈도 자체가 낮고, 크레딧 소진 실패의 blast radius도 "다음 질문이 막힌다" 정도라 낮음.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config

STATE_PATH = Path(__file__).parent / "credit_guard_state.json"


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"cumulative_used_krw": 0.0}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def record_usage(usd_amount: float) -> None:
    """Discovery Engine 호출 직후 누적 사용액 기록. search_client.ask() 가 응답 후 호출."""
    state = _load_state()
    state["cumulative_used_krw"] = round(
        state.get("cumulative_used_krw", 0.0) + usd_amount * config.USD_TO_KRW, 2
    )
    _save_state(state)


def estimated_balance_krw() -> float:
    used = _load_state().get("cumulative_used_krw", 0.0)
    return config.INITIAL_CREDIT_KRW - used


def status_report() -> str:
    state = _load_state()
    used = state.get("cumulative_used_krw", 0.0)
    balance = estimated_balance_krw()
    warn = " ⚠ 잔액 부족 경고" if balance < config.WARNING_THRESHOLD_KRW else ""
    return (
        f"App Builder 크레딧 잔액 추정 ₩{balance:,.0f} "
        f"(누적사용 ₩{used:,.1f}, 만료 {config.CREDIT_EXPIRES_KST}){warn}"
    )


if __name__ == "__main__":
    import sys

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ₩ 기호가 cp949 콘솔에서 깨지는 것 방지
    print(status_report())
