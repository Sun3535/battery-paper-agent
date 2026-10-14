"""배터리 관련성 필터 (엄격 모드).

arXiv의 cond-mat.mtrl-sci 검색은 배터리와 무관한 재료과학 논문을 대량으로 끌어온다
(고체산화물 연료전지, force field 파라미터화, post-spinel 산화물 등). 이 필터는 제목 또는
초록에 **전기화학 에너지 저장(배터리) 맥락을 명확히 드러내는 핵심어**가 실제로 있는 논문만
통과시킨다. 통과 기준: STRICT_TERMS 중 하나라도 단어 경계로 매칭되면 관련.

느슨한 단어(lithium 단독, cell, solid 단독)는 광학·촉매 논문 오탐이 많아 일부러 제외했다.
"""

from __future__ import annotations

import re

# 배터리/에너지저장 맥락을 강하게 시사하는 용어 (소문자, 단어경계 매칭)
STRICT_TERMS = [
    r"batter(?:y|ies)",
    r"anode",
    r"cathode",
    r"electrolyte",
    r"electrolytes",
    r"li-ion",
    r"lithium-ion",
    r"lithium ion",
    r"sodium-ion",
    r"na-ion",
    r"sodium ion",
    r"solid-state batter",
    r"all-solid-state",
    r"lithium metal",
    r"silicon anode",
    r"coulombic efficiency",
    r"cycle life",
    r"cyclability",
    r"dendrite",
    r"polysulfide",
    r"solid electrolyte interphase",
    r"lifepo4",
    r"nmc",   # 양극재 조성
    r"ncm",
    r"supercapacitor",  # 인접 에너지저장 — 필요 없으면 제거 가능
]

_PATTERN = re.compile(r"\b(?:" + "|".join(STRICT_TERMS) + r")\b", re.IGNORECASE)


def is_relevant(title: str, abstract: str) -> bool:
    """제목/초록에 배터리 핵심어가 하나라도 있으면 True."""
    text = f"{title or ''}\n{abstract or ''}"
    return bool(_PATTERN.search(text))


def matched_terms(title: str, abstract: str) -> list[str]:
    """디버그용 — 어떤 용어가 매칭됐는지 반환."""
    text = f"{title or ''}\n{abstract or ''}"
    return sorted({m.group(0).lower() for m in _PATTERN.finditer(text)})
