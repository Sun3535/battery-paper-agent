"""그림·표와 캡션 짝짓기.

배경(2026-10-14 호야): "Molybdate-Induced Rigid–Flexible Composite Framework…" 의 Fig. 5 에 캡션이 없었다.
그림이 한 쪽을 꽉 채워 캡션이 다음 쪽 맨 위에 있었는데, 예전 규칙은 "바로 앞뒤 블록 + 같은 쪽" 만 봤고,
리더는 캡션 블록을 숨겨서 캡션이 화면에서 통째로 사라졌다.
"""

import captions
from captions import Item


def T(page, text="본문"):
    return Item("text", page, text, False)


def CAP(page, text):
    return Item("text", page, text, True)


def FIG(page, text=""):
    return Item("image", page, text, False)


def TAB(page, text=""):
    return Item("table", page, text, False)


def test_caption_on_next_page_top_goes_to_full_page_figure():
    """실제 사례 그대로: 10쪽을 꽉 채운 그림, 캡션은 11쪽 맨 위."""
    items = [T(9), FIG(10), T(10, "쪽 번호"), CAP(11, "Fig. 5 Galvanostatic intermittent titration…"), T(11)]
    pairs, attached = captions.match(items)
    assert pairs == {1: 3}
    assert attached == {3}


def test_same_page_caption_need_not_be_adjacent():
    items = [FIG(3), T(3, "축 이름"), T(3, "범례"), CAP(3, "Fig. 1 XRD patterns")]
    assert captions.match(items)[0] == {0: 3}


def test_already_captioned_figure_is_left_alone_and_its_caption_counts_as_attached():
    items = [FIG(4, "Fig. 2 XPS spectra"), CAP(4, "Fig. 2 XPS spectra"), FIG(4), CAP(4, "Fig. 3 SEM images")]
    pairs, attached = captions.match(items)
    assert pairs == {2: 3}  # 이미 붙은 Fig. 2 는 건드리지 않고, 남은 그림에 남은 캡션
    assert attached == {1, 3}


def test_one_caption_is_never_given_to_two_figures():
    """한 그림이 여러 조각으로 뽑힌 쪽 — 캡션은 가장 가까운 조각 하나에만."""
    items = [FIG(5), FIG(5), FIG(5), CAP(5, "Fig. 4 CV curves")]
    pairs, _ = captions.match(items)
    assert pairs == {2: 3}


def test_table_caption_only_goes_to_table_and_figure_caption_only_to_figure():
    items = [FIG(8), CAP(8, "Table 1 Electrochemical performance"), TAB(8), CAP(8, "Fig. 4 CV curves")]
    assert captions.match(items)[0] == {0: 3, 2: 1}


def test_caption_deep_in_next_page_is_not_pulled_back():
    """다음 쪽 한가운데의 캡션은 그 쪽의 것이다 — 앞 쪽 그림에 붙이지 않는다."""
    items = [FIG(6), T(7), T(7), T(7), T(7), CAP(7, "Fig. 9 Something else")]
    pairs, attached = captions.match(items)
    assert pairs == {} and attached == set()


def test_reader_output_gets_caption_text_translation_and_orphan_flag():
    blocks = [
        {"kind": "image", "page": 10, "text_en": "", "text_ko": "", "is_caption": False},
        {"kind": "text", "page": 11, "text_en": "Fig. 5 GITT curves", "text_ko": "Fig. 5 GITT 곡선", "is_caption": True},
        {"kind": "text", "page": 11, "text_en": "Table 1 Performance", "text_ko": "", "is_caption": True},
        {"kind": "text", "page": 11, "text_en": "body", "text_ko": "", "is_caption": False},
    ]
    out = captions.pair_for_reader(blocks)
    assert out[0]["text_en"] == "Fig. 5 GITT curves" and out[0]["text_ko"] == "Fig. 5 GITT 곡선"  # 번역도 같이 따라온다
    assert out[1]["attached"] is True
    assert out[2]["attached"] is False  # 짝 없는 캡션 → 리더가 숨기지 않는다
    assert "attached" not in out[3]
