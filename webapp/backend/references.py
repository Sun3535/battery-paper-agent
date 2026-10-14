"""논문 텍스트 블록에서 참고문헌(References) 목록 추출.

전략: "References"/"Bibliography" 헤딩 이후의 텍스트를 모아, 번호 표기([1] 또는 1.)를
기준으로 항목을 쪼갠다. 학술 PDF의 참고문헌 형식이 제각각이라 완벽하진 않지만,
번호 기반 분할이 가장 안정적이다.
"""

from __future__ import annotations

import re

HEADING = re.compile(r"^\s*(references|bibliography|참고\s*문헌)\s*$", re.IGNORECASE)
# [1] 또는 1. 또는 (1) 로 시작하는 항목
ITEM_SPLIT = re.compile(r"(?=(?:\[\d{1,3}\]|\(\d{1,3}\)|^\d{1,3}\.\s))", re.MULTILINE)
LEADING_NUM = re.compile(r"^\s*(?:\[(\d{1,3})\]|\((\d{1,3})\)|(\d{1,3})\.)\s*")


def extract_references(blocks: list[dict]) -> list[str]:
    """blocks(extract.Block.to_dict 형태) → 참고문헌 문자열 리스트."""
    start = None
    for i, b in enumerate(blocks):
        if b.get("kind") != "text":
            continue
        text = (b.get("text") or "").strip()
        if HEADING.match(text):
            start = i + 1
            break
        # 헤딩이 문단에 섞인 경우(예: "References [1] Smith...")도 잡는다
        if re.match(r"^\s*references\b", text, re.IGNORECASE) and len(text) > 20:
            start = i
            break

    if start is None:
        return []

    tail = "\n".join(
        (b.get("text") or "").strip()
        for b in blocks[start:]
        if b.get("kind") == "text" and not b.get("is_caption")
    )
    # 헤딩 단어가 앞에 남아있으면 제거
    tail = re.sub(r"^\s*(references|bibliography)\s*", "", tail, flags=re.IGNORECASE)

    items = [s.strip() for s in ITEM_SPLIT.split(tail) if s and s.strip()]
    refs: list[str] = []
    for it in items:
        it = re.sub(r"\s+", " ", it).strip()
        if len(it) < 20:  # 번호만 남은 조각 등 노이즈 제거
            continue
        refs.append(it)

    # 너무 적게 잡히면(분할 실패) 빈 리스트로 — 잘못된 데이터를 보여주느니 없는 게 낫다
    return refs if len(refs) >= 3 else []


def strip_number(raw: str) -> tuple[int | None, str]:
    """"[12] Smith, J. ..." → (12, "Smith, J. ...")"""
    m = LEADING_NUM.match(raw)
    if not m:
        return None, raw
    num = next((g for g in m.groups() if g), None)
    return (int(num) if num else None), raw[m.end():].strip()
