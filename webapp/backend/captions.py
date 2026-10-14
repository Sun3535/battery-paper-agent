"""그림·표와 캡션 짝짓기.

배경(2026-10-14 호야: "Fig. 5 의 캡션이 없다"):
  예전 규칙은 "그림 **바로 앞뒤** 블록이면서 **같은 쪽**" 일 때만 캡션을 붙였다. 그래서
    - 한 쪽을 꽉 채운 그림(캡션이 다음 쪽 맨 위에 오는 경우)
    - 그림과 캡션 사이에 다른 블록이 낀 경우
  에는 그림에 캡션이 안 붙었고, 리더는 캡션 블록을 "그림에 이미 붙였다" 고 보고 숨겨서
  캡션이 화면에서 **통째로 사라졌다**. 서가 91편에서 캡션 블록 966개 중 427개가 그렇게 숨어 있었다.

여기서 하는 일은 두 가지다.
  1) match(): 캡션 없는 그림에 남는 캡션을 짝지어 준다 — 같은 쪽의 가장 가까운 캡션, 없으면 다음 쪽 맨 위의 캡션.
  2) pair_for_reader(): 화면에 내보낼 때 그 짝을 적용하고, 어느 그림에도 붙지 못한 캡션에 표시를 남긴다
     (리더가 그 글은 숨기지 않고 보여 준다 — 내용이 사라지지 않는 것이 먼저다).

저장된 블록은 건드리지 않는다. 블록 번호에 번역 캐시가 묶여 있어, 읽을 때 짝을 지어 주는 쪽이 안전하다.
"""

from __future__ import annotations

import re
from typing import NamedTuple

_TABLE = re.compile(r"^\s*table\b", re.IGNORECASE)
NEXT_PAGE_TOP = 3  # 다음 쪽의 앞에서 몇 번째 블록까지를 "맨 위" 로 볼지


class Item(NamedTuple):
    kind: str  # text | image | table
    page: int
    text: str
    is_caption: bool


def _fits(figure: Item, caption: Item) -> bool:
    """표 캡션은 표에만, 그림 캡션(Fig./Scheme)은 그림에만 붙인다."""
    return (figure.kind == "table") == bool(_TABLE.match(caption.text))


def match(items: list[Item]) -> tuple[dict[int, int], set[int]]:
    """읽기 순서로 놓인 블록들에서 (그림 자리 → 캡션 자리) 짝과, 이미 그림에 붙어 있는 캡션 자리들을 돌려준다.

    이미 캡션 글이 들어 있는 그림은 건드리지 않고, 그 글과 같은 캡션 블록은 "붙어 있음" 으로 친다.
    """
    owned = {it.text.strip() for it in items if it.kind in ("image", "table") and it.text.strip()}
    attached = {i for i, it in enumerate(items) if it.kind == "text" and it.is_caption and it.text.strip() in owned}
    free = [i for i, it in enumerate(items) if it.kind == "text" and it.is_caption and i not in attached and it.text.strip()]
    bare = [i for i, it in enumerate(items) if it.kind in ("image", "table") and not it.text.strip()]

    pairs: dict[int, int] = {}
    used: set[int] = set()

    # ① 같은 쪽 — 캡션마다 가장 가까운 '캡션 없는 그림' 하나에 붙인다(한 그림이 여러 조각으로 뽑혀도 캡션은 한 번만).
    #    거리가 같으면 캡션보다 앞에 있는 그림을 고른다(캡션은 보통 그림 아래).
    for c in free:
        cands = [f for f in bare if f not in pairs and items[f].page == items[c].page and _fits(items[f], items[c])]
        if cands:
            f = min(cands, key=lambda f: (abs(c - f), f > c))
            pairs[f] = c
            used.add(c)

    # ② 다음 쪽 맨 위 — 한 쪽을 꽉 채운 그림의 캡션. 앞 쪽에서 캡션 없이 남은 **마지막** 그림에 붙인다.
    first_of_page: dict[int, int] = {}
    for i, it in enumerate(items):
        first_of_page.setdefault(it.page, i)
    for c in free:
        if c in used or c - first_of_page[items[c].page] >= NEXT_PAGE_TOP:
            continue
        prev = [f for f in bare if f not in pairs and items[f].page == items[c].page - 1 and _fits(items[f], items[c])]
        if prev:
            pairs[prev[-1]] = c
            used.add(c)

    return pairs, attached | used


def pair_for_reader(blocks: list[dict]) -> list[dict]:
    """리더용 블록 목록(store.get_blocks 결과)에 짝을 적용한다 — 목록을 고쳐서 그대로 돌려준다.

    - 캡션 없는 그림: 짝지어진 캡션의 원문·번역문을 받는다.
    - 캡션 블록: `attached` = 어느 그림에 붙었는가. False 면 리더가 숨기지 않고 본문에 보여 준다.
    """
    items = [Item(b["kind"], b["page"], b.get("text_en") or "", bool(b.get("is_caption"))) for b in blocks]
    pairs, attached = match(items)
    for f, c in pairs.items():
        blocks[f]["text_en"] = blocks[c].get("text_en") or ""
        blocks[f]["text_ko"] = blocks[c].get("text_ko") or ""
    for i, b in enumerate(blocks):
        if b["kind"] == "text" and b.get("is_caption"):
            b["attached"] = i in attached
    return blocks
