"""PDF → 읽기순서 블록 추출 (E-book 리더의 핵심).

기존 scripts/01_extract.py 와의 차이:
  - 01_extract.py: 이미지를 xref로 뽑아 **페이지 끝**에 마커를 몰아넣음 → 본문 사이 위치가 틀림
  - 이 모듈: 텍스트/그림/표를 **읽기 순서대로** 배열한 블록 리스트를 만든다.
    E-book 리더가 이 순서 그대로 렌더하면 그림이 원래 있던 자리에 들어간다.

이미지 처리 원칙 (요구사항: "왜곡·꾸밈없이 원본 그대로"):
  - 임베디드 이미지를 xref로 뽑지 않고, **블록 bbox 영역을 그대로 클립 렌더링**한다.
    학술 논문의 Figure는 여러 하위 이미지+벡터 그래픽이 합성된 경우가 많아 xref 추출은
    조각나거나 축 라벨(벡터 텍스트)이 빠진다. bbox 클립 렌더는 화면에 보이는 그대로를
    픽셀로 보존한다. 리사이즈·비율변경·워터마크 일절 없음. ZOOM은 해상도만 올림(비율 유지).

2단(two-column) 조판 대응: 단순 y정렬은 좌우 단을 뒤섞는다. 페이지를 좌/우 단으로
나눠 각각 위→아래로 읽는 컬럼 인식 정렬을 적용한다.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

import fitz  # PyMuPDF

ZOOM = 2.0  # 렌더 배율 (비율 유지, 해상도만 향상)
MIN_IMAGE_AREA = 10_000  # 이보다 작은 이미지 블록은 로고/아이콘으로 보고 제외 (pt^2)
MIN_IMAGE_SIDE = 60  # 가로/세로 중 하나라도 이보다 작으면 제외 (장식용 구분선 등)
# 캡션의 머리: "Fig. 3", "Figure S1"(보조 자료), "TABLE II"(로마 숫자 — 대문자만), "Scheme 1"
CAPTION_PATTERN = re.compile(
    r"^\s*(?:fig(?:ure)?\.?|table|scheme)\s*\.?\s*(?:S?\d+|(?-i:[IVX]+)\b)", re.IGNORECASE
)


def _is_caption(text: str) -> bool:
    """캡션으로 시작하는 글인가. "Figure 3 shows…" 같은 본문 문장은 캡션이 아니다(captions.py 한 곳에서 판정)."""
    import captions

    return captions.is_caption_text(text)

# 문단 병합 파라미터 — PDF가 줄 단위 블록으로 쪼개져 오는 경우가 많아, 같은 단(column)의
# 인접한 줄들을 하나의 문단 블록으로 합친다(번역 품질·비용 모두에 유리).
PARA_X_TOL = 20.0  # 같은 단으로 볼 x0 차이 허용치 (pt)
PARA_GAP_RATIO = 1.6  # 줄 높이의 이 배수 이내 세로 간격이면 같은 문단

BlockKind = Literal["text", "image", "table"]


@dataclass
class Block:
    """읽기 순서 상의 한 블록. order가 곧 E-book 렌더 순서."""

    order: int
    kind: BlockKind
    page: int
    bbox: tuple[float, float, float, float]
    text: str = ""  # kind=text: 원문 / kind=image|table: 캡션(있으면)
    image_path: Optional[str] = None  # kind=image|table: 렌더된 PNG 파일명
    table_rows: Optional[list[list[str]]] = None  # kind=table: 셀 데이터(표 뷰어용)
    is_caption: bool = False  # 텍스트 블록이 그림/표 캡션인지

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = list(self.bbox)
        return d


@dataclass
class ExtractResult:
    blocks: list[Block] = field(default_factory=list)
    page_count: int = 0

    def to_dict(self) -> dict:
        return {"page_count": self.page_count, "blocks": [b.to_dict() for b in self.blocks]}


def _column_aware_sort(items: list[dict], page_width: float, page_height: float) -> list[dict]:
    """2단 조판을 고려한 읽기순서 정렬.

    좌/우 단 어느 쪽에도 확실히 속하는 블록이 양쪽에 충분히 있으면 2단으로 보고
    좌단 전체 → 우단 전체 순으로 읽는다. 아니면 단순 y→x 정렬(단일 단).
    """
    mid = page_width / 2
    margin = page_width * 0.03
    left, right, full = [], [], []
    for it in items:
        x0, _, x1, _ = it["bbox"]
        if x1 <= mid + margin:
            left.append(it)
        elif x0 >= mid - margin:
            right.append(it)
        else:
            full.append(it)  # 중앙선을 가로지름 = 전폭 요소(제목, 전폭 그림 등)

    def ykey(it):
        return (round(it["bbox"][1], 1), it["bbox"][0])

    is_two_column = len(left) >= 2 and len(right) >= 2 and len(full) <= max(len(left), len(right))
    if not is_two_column:
        return sorted(items, key=ykey)

    # 상단 전폭 요소(제목/저자 등)는 맨 앞, 나머지 전폭 요소는 뒤로.
    top_cut = page_height * 0.20
    top_full = [it for it in full if it["bbox"][1] < top_cut]
    rest_full = [it for it in full if it["bbox"][1] >= top_cut]

    return (
        sorted(top_full, key=ykey)
        + sorted(left, key=ykey)
        + sorted(right, key=ykey)
        + sorted(rest_full, key=ykey)
    )


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _regions_should_merge(a: dict, b: dict, texts: list[dict], gap: float = 14.0) -> bool:
    """두 비텍스트 영역이 같은 Figure의 조각인지 판정.

    학술 논문의 multi-panel Figure는 벡터 클러스터가 패널별로 쪼개져 잡힌다(a/b/c 패널).
    가깝고 가로로 겹치면 같은 그림으로 보고 합친다. 단 사이에 캡션 텍스트가 끼어 있으면
    서로 다른 그림이므로 합치지 않는다.
    """
    ax0, ay0, ax1, ay1 = a["bbox"]
    bx0, by0, bx1, by1 = b["bbox"]

    h_overlap = min(ax1, bx1) - max(ax0, bx0) > 0
    v_overlap = min(ay1, by1) - max(ay0, by0) > 0
    v_gap = max(0.0, max(ay0, by0) - min(ay1, by1))
    h_gap = max(0.0, max(ax0, bx0) - min(ax1, bx1))

    close = (h_overlap and v_gap <= gap) or (v_overlap and h_gap <= gap)
    if not close:
        return False

    # 사이에 캡션이 끼어 있으면 서로 다른 그림
    lo_y, hi_y = min(ay1, by1), max(ay0, by0)
    for t in texts:
        if not t.get("is_caption_hint"):
            continue
        tx0, ty0, tx1, ty1 = t["bbox"]
        if ty0 >= lo_y - 2 and ty1 <= hi_y + 2 and min(ax1, tx1) - max(ax0, tx0) > 0:
            return False
    return True


def _merge_regions(regions: list[dict], texts: list[dict]) -> list[dict]:
    """인접한 그림/표 조각들을 하나의 영역으로 합친다 (multi-panel Figure 대응)."""
    merged = [dict(r) for r in regions]
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                if _regions_should_merge(merged[i], merged[j], texts):
                    merged[i]["bbox"] = _union(merged[i]["bbox"], merged[j]["bbox"])
                    # 표 셀 데이터는 어느 쪽이든 있으면 보존
                    if not merged[i].get("rows") and merged[j].get("rows"):
                        merged[i]["rows"] = merged[j]["rows"]
                    merged.pop(j)
                    changed = True
                    break
            if changed:
                break
    return merged


def _merge_paragraphs(ordered: list[dict]) -> list[dict]:
    """읽기순서로 정렬된 항목들에서, 같은 단의 인접한 텍스트 줄들을 한 문단으로 합친다.

    PDF는 줄마다 별도 블록으로 오는 경우가 흔하다(실측: 31p 논문에서 텍스트 블록 1070개).
    그대로 번역하면 문장이 잘려 번역 품질이 떨어지고 API 호출도 과도하게 늘어난다.
    캡션은 병합하지 않는다(그림/표에 붙여야 하므로).
    """
    merged: list[dict] = []
    for it in ordered:
        if it["kind"] != "text":
            merged.append(it)
            continue

        text = it["text"]
        is_cap = _is_caption(text)
        it = {**it, "is_caption": is_cap}

        prev = merged[-1] if merged else None
        if (
            prev is not None
            and prev["kind"] == "text"
            and not prev.get("is_caption")
            and not is_cap
            and abs(prev["bbox"][0] - it["bbox"][0]) <= PARA_X_TOL
            and (it["bbox"][1] - prev["bbox"][3])
            <= PARA_GAP_RATIO * max(prev.get("line_h", 10.0), 1.0)
        ):
            # 같은 문단의 다음 줄 → 앞 블록에 이어붙이고 bbox 확장
            prev["text"] = f"{prev['text']} {text}".strip()
            prev["bbox"] = (
                min(prev["bbox"][0], it["bbox"][0]),
                min(prev["bbox"][1], it["bbox"][1]),
                max(prev["bbox"][2], it["bbox"][2]),
                max(prev["bbox"][3], it["bbox"][3]),
            )
            continue

        merged.append(it)
    return merged


def _render_clip(page: fitz.Page, bbox: tuple[float, float, float, float], out_path: Path) -> bool:
    """bbox 영역을 그대로 PNG로 렌더 (비율 유지, 재가공 없음)."""
    try:
        rect = fitz.Rect(*bbox)
        if page.rotation:
            # 가로로 누운 쪽(rotation 90/270): 블록 좌표는 돌리기 전 기준인데 get_pixmap 의 clip 은
            # 돌린 뒤 기준이다. 오릴 때만 맞춰 준다. (page.remove_rotation() 은 쓰지 않는다 —
            # 쪽 전체가 그림 하나로 잡혀 글 블록이 사라진다. 2026-10-14 점검에서 확인)
            rect = rect * page.rotation_matrix
            rect.normalize()
        pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=rect)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
        return True
    except Exception:
        return False


INSIDE_REGION_RATIO = 0.5  # 글 블록 넓이의 이 비율 이상이 그림/표 영역 안이면 "그림 속 글자" 로 본다


def _bbox_overlaps(a, b, tol: float = 2.0) -> bool:
    """글 블록 a 가 그림/표 영역 b **안에 들어 있는가** (그림 속 글자인가).

    예전에는 2pt 만 걸쳐도 참이라, 그림 옆에 붙은 캡션·본문 문단이 통째로 사라졌다
    (2026-10-14 점검: 서가 91편에서 148블록·7만 7천 자, 캡션 55개). 그 글은 그림 PNG 에도 다 찍히지 않는다.
    이제 글 블록 넓이의 절반 이상이 영역 안일 때만 그림 속 글자로 본다.
    """
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = min(ax1, bx1) - max(ax0, bx0)
    iy = min(ay1, by1) - max(ay0, by0)
    if ix <= tol or iy <= tol:
        return False
    return ix * iy >= INSIDE_REGION_RATIO * max(1e-6, (ax1 - ax0) * (ay1 - ay0))


# ══════════════════════════════════════════════════════════════════
# 글리프 깨짐 정리 (2026-07-28 호야 지적: 리더 본문에 □ 와 빈 네모가 섞여 나옴)
#
# 폰트 문제가 아니다. LaTeX 논문의 수식은 CMSY·CMMI·MSBM 같은 Type1 심볼 폰트로
# 조판되는데 이 폰트들은 ToUnicode CMap 이 없는 경우가 많다. 매핑이 없으면 PyMuPDF는
# 사용자정의영역(PUA)이나 미할당 코드포인트를 그대로 돌려주고, 브라우저는 **어떤 폰트로도**
# 그릴 수 없어 tofu(□)를 찍는다. 즉 문자 자체가 의미 없는 코드라 CSS로는 못 고친다.
# → 추출 단계에서 걸러내는 것이 유일한 해법.
#
# 함께 버리는 것: 행렬·수식이 텍스트로 흘러나온 잔해("a 0 0 0 b 0 0 0 c", "▯,").
# 읽을 수 없을뿐더러 번역 API 비용까지 잡아먹는다.
# ══════════════════════════════════════════════════════════════════
_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
# 유니코드 카테고리로 판정: Cn=미할당, Co=사용자정의영역, Cs=서로게이트, Cc=제어문자
_DEAD_CATEGORIES = {"Cn", "Co", "Cs", "Cc"}
_KEEP_CONTROL = {"\n", "\t"}
# 3글자 이상 이어진 '낱말 글자'. 예전에는 영어·한글만 낱말로 쳐서 러시아어·한자 논문의 글이 '잔해' 로 지워졌다.
# 라틴(악센트 포함)·키릴·가나·한자·한글을 낱말로 본다. 그리스 문자와 수학용 기울임 글자(𝑑𝑠…)는 넣지 않는다 —
# 이 분야 논문에서는 수식 기호라, 낱말로 치면 수식 조각이 본문에 쏟아진다(91편으로 견줘 확인).
_WORD = re.compile(r"[A-Za-z\u00C0-\u024F\u0400-\u04FF\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7A3]{3,}")
_TABLE_HEAD = re.compile(r"^\s*table\b", re.IGNORECASE)
DEBRIS_WORD_RATIO = 0.25  # 실단어가 이 비율 미만이면 수식 잔해로 본다
DEBRIS_MAX_LEN = 60  # 실단어가 0개일 때, 이보다 짧으면 잔해로 본다


def sanitize_text(text: str) -> str:
    """렌더 불가능한 글리프를 걷어내고 ligature를 되돌린다."""
    if not text:
        return ""
    out = []
    for ch in text:
        if ch in _LIGATURES:
            out.append(_LIGATURES[ch])
            continue
        if ch in _KEEP_CONTROL:
            out.append(ch)
            continue
        if ch == "�" or unicodedata.category(ch) in _DEAD_CATEGORIES:
            continue  # 그릴 수 없는 문자 — 버린다
        out.append(ch)
    cleaned = "".join(out)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


# 표가 끝났다고 볼 "문장으로 된 문단" — 표의 머리줄(`Sample Voltage (V) Capacity`)은 낱말이지만 문장이 아니다.
# 2차 점검(2026-10-14): 머리줄에서 보호를 끄는 바람에 그 아래 숫자 줄(표의 값)이 여전히 버려졌다(217블록·29편).
_SENTENCE_END = re.compile(r"[a-z]{2,}[.!?](?:\s|$)")
_PAGE_NO = re.compile(r"\s*\d{1,4}\s*")


def _is_prose(text: str) -> bool:
    return len(_WORD.findall(text)) >= 10 and bool(_SENTENCE_END.search(text))


def _continues(prev: dict, it: dict) -> bool:
    """it 이 prev 바로 밑에 붙은 다음 줄인가(같은 단, 줄 간격 안) — 캡션의 둘째 줄을 알아보는 데 쓴다."""
    return (
        abs(prev["bbox"][0] - it["bbox"][0]) <= PARA_X_TOL
        and -2 <= it["bbox"][1] - prev["bbox"][3] <= PARA_GAP_RATIO * max(prev.get("line_h", 10.0), 1.0)
    )


def is_math_debris(text: str) -> bool:
    """수식이 텍스트로 흘러나온 잔해인가. (정상 문장·제목·캡션은 남긴다)"""
    t = text.strip()
    if not t:
        return True
    words = _WORD.findall(t)
    if words:
        return sum(len(w) for w in words) < len(t) * DEBRIS_WORD_RATIO
    # 3글자 이상 단어가 하나도 없음 — 짧으면 잔해, 길면 표 데이터일 수 있으니 남긴다
    return len(t) < DEBRIS_MAX_LEN


def _block_text(block: dict) -> str:
    """PyMuPDF dict 블록에서 텍스트를 뽑아 한 문단으로 합친다."""
    parts = []
    for line in block.get("lines", []):
        parts.append("".join(span.get("text", "") for span in line.get("spans", [])))
    text = "\n".join(parts)
    text = re.sub(r"-\n(?=[a-z])", "", text)  # 줄바꿈 하이픈 결합: elec-\ntrolyte → electrolyte
    text = re.sub(r"\n(?!\n)", " ", text)  # 문단 내 줄바꿈 → 공백
    return sanitize_text(text)


# PDF 를 여러 편 한꺼번에 올리면 업로드 처리가 스레드로 동시에 돈다. 그런데 PyMuPDF 의 표 찾기(find_tables)는
# 전역 설정(small_glyph_heights)을 잠깐 켰다가 되돌리는데, 두 편이 겹치면 켜진 채로 남는다 → 서버를 다시 켤 때까지
# 모든 추출이 달라지고, 동시에 처리되는 논문은 돌 때마다 그림·캡션·표 값이 흔들렸다(2차 점검 2026-10-14).
# → 추출은 한 번에 한 편씩 한다. 한 편에 몇 초라, 줄을 서도 사용자는 거의 못 느낀다.
_EXTRACT_LOCK = threading.Lock()


def extract_blocks(pdf_path: Path, images_dir: Path) -> ExtractResult:
    """PDF를 읽기순서 블록 리스트로 변환. 그림/표는 원본 렌더 PNG로 저장. (한 번에 한 편 — 위 _EXTRACT_LOCK)"""
    with _EXTRACT_LOCK:
        fitz.TOOLS.set_small_glyph_heights(False)  # 혹시 켜진 채 남은 전역 설정을 기본값으로 되돌린다
        return _extract_blocks(pdf_path, images_dir)


def _extract_blocks(pdf_path: Path, images_dir: Path) -> ExtractResult:
    doc = fitz.open(str(pdf_path))
    result = ExtractResult(page_count=doc.page_count)
    order = 0
    img_seq = 0

    for page_index, page in enumerate(doc, start=1):
        page_width, page_height = page.rect.width, page.rect.height
        raw_blocks = page.get_text("dict").get("blocks", [])

        # 0) 캡션 힌트 — 영역 병합 시 "두 그림 사이에 캡션이 있는가" 판정에 쓴다.
        text_hints = []
        for b in raw_blocks:
            if b.get("type") != 0:
                continue
            t = _block_text(b)
            if t:
                text_hints.append({"bbox": tuple(b["bbox"]), "is_caption_hint": _is_caption(t)})

        # 1) 비텍스트 영역 후보 수집: 표(find_tables) + 벡터 그림(cluster_drawings) + 래스터 이미지
        regions: list[dict] = []
        try:
            for tb in page.find_tables():
                try:
                    rows = [[(c or "") for c in row] for row in tb.extract()]
                except Exception:
                    rows = []
                regions.append({"bbox": tuple(tb.bbox), "rows": rows})
        except Exception:
            pass  # find_tables는 일부 PDF에서 실패 가능

        try:
            # 학술 논문 Figure 대부분은 벡터 그래픽이라 래스터 이미지로 안 잡힌다.
            for rect in page.cluster_drawings():
                if rect.width * rect.height < MIN_IMAGE_AREA or min(rect.width, rect.height) < MIN_IMAGE_SIDE:
                    continue
                regions.append({"bbox": (rect.x0, rect.y0, rect.x1, rect.y1)})
        except Exception:
            pass  # cluster_drawings 미지원 시 래스터만으로 진행

        for b in raw_blocks:
            if b.get("type") != 1:
                continue
            x0, y0, x1, y1 = b.get("bbox", (0, 0, 0, 0))
            if (x1 - x0) * (y1 - y0) >= MIN_IMAGE_AREA and min(x1 - x0, y1 - y0) >= MIN_IMAGE_SIDE:
                regions.append({"bbox": (x0, y0, x1, y1)})

        # 2) 인접 조각 병합 → 한 Figure = 한 영역 (multi-panel 대응)
        regions = _merge_regions(regions, text_hints)

        # 3) 텍스트 블록 (그림/표 영역 내부 텍스트는 렌더 이미지에 이미 포함 → 본문에서 제외.
        #    캡션은 영역 밖에 있으므로 살아남는다.)
        items: list[dict] = [{"kind": "region", **r} for r in regions]
        for b in raw_blocks:
            if b.get("type") != 0:
                continue
            bbox = tuple(b.get("bbox", (0, 0, 0, 0)))
            if any(_bbox_overlaps(bbox, r["bbox"]) for r in regions):
                continue
            text = _block_text(b)
            if not text:
                continue
            # 수식 잔해 판정은 여기서 하지 않는다 — 줄 단위로 버리면 숫자 많은 줄이 문단 한가운데서 빠진다
            # (2026-10-14 점검: 새로 올리면 477블록이 그렇게 사라졌다). 아래에서 문단으로 합친 뒤에 판정한다.
            n_lines = max(1, len(b.get("lines", [])))
            items.append(
                {
                    "kind": "text",
                    "bbox": bbox,
                    "text": text,
                    "line_h": (bbox[3] - bbox[1]) / n_lines,
                }
            )

        # 4) 읽기순서 정렬 → 문단 병합 → 블록 생성 (그림/표는 bbox 클립 렌더)
        ordered = _merge_paragraphs(_column_aware_sort(items, page_width, page_height))
        under_table_caption = False  # 표 캡션 아래를 지나는 중인가(문장으로 된 문단·그림·쪽 끝에서 끝난다)
        last_caption: dict | None = None  # 바로 앞 블록이 캡션이면 그 캡션
        for it in ordered:
            prev_caption, last_caption = last_caption, None
            if it["kind"] != "text":
                under_table_caption = False
            elif it.get("is_caption"):
                # 캡션은 숫자가 많아도 남긴다. 표 캡션이면 그 아래 숫자 줄들은 표의 내용이다.
                under_table_caption = bool(_TABLE_HEAD.match(it["text"]))
                last_caption = it
            elif is_math_debris(it["text"]):
                # 문단으로 합친 뒤에도 통째로 수식 잔해인 블록은 뺀다(읽기 방해 + 번역비 낭비).
                # 단, 지우면 내용이 어디에도 안 남는 두 경우는 남긴다(2026-10-14 점검):
                #   - 표 캡션 아래의 숫자 줄 = **표의 값**(영역으로 못 잡힌 표는 그림으로도 안 남는다). 쪽 번호만은 뺀다.
                #   - 캡션 바로 밑에 붙은 숫자 위주의 둘째 줄 = 캡션의 일부(캡션은 문단으로 합치지 않아 따로 떨어진다).
                keep = (under_table_caption or (prev_caption is not None and _continues(prev_caption, it))) and not (
                    _PAGE_NO.fullmatch(it["text"])  # 쪽 번호는 어느 경우든 뺀다
                )
                if not keep:
                    continue
            elif _is_prose(it["text"]):
                under_table_caption = False  # 문장으로 된 문단이 나왔다 = 표가 끝났다(머리줄·소제목에서는 끄지 않는다)
            if it["kind"] == "text":
                order += 1
                result.blocks.append(
                    Block(
                        order=order,
                        kind="text",
                        page=page_index,
                        bbox=it["bbox"],
                        text=it["text"],
                        is_caption=it.get("is_caption", _is_caption(it["text"])),
                    )
                )
            else:  # region — 그림/표. 종류는 캡션을 보고 나중에 확정한다.
                img_seq += 1
                name = f"p{page_index}_fig_{img_seq}.png"
                if not _render_clip(page, it["bbox"], images_dir / name):
                    continue
                order += 1
                result.blocks.append(
                    Block(
                        order=order,
                        kind="image",  # 잠정 — _classify_regions에서 캡션 보고 table로 바뀔 수 있음
                        page=page_index,
                        bbox=it["bbox"],
                        image_path=name,
                        table_rows=it.get("rows"),
                    )
                )

    doc.close()
    for b in result.blocks:  # 잠정: 셀 데이터가 뽑힌 영역은 표. 캡션을 붙인 뒤 _classify_regions 가 확정한다
        if b.kind == "image" and b.table_rows:
            b.kind = "table"
    _attach_captions(result.blocks)
    _classify_regions(result.blocks)
    return result


def _classify_regions(blocks: list[Block]) -> None:
    """캡션을 기준으로 그림/표를 확정한다.

    find_tables()는 그래프의 축·격자선을 표로 오인하는 일이 잦다(실측: "Figure 2" 캡션이
    붙은 영역이 table로 분류됨). 캡션이 진실의 원천이므로 캡션 접두사로 재분류한다.
    캡션이 없으면 셀 데이터 유무로 판단한다.
    """
    for b in blocks:
        if b.kind not in ("image", "table"):
            continue
        head = (b.text or "").strip().lower()
        if head.startswith("table"):
            b.kind = "table"
        elif head.startswith(("fig", "scheme")):
            b.kind = "image"
            b.table_rows = None  # 그래프를 표로 오인해 뽑은 셀 데이터는 폐기
        else:
            b.kind = "table" if b.table_rows else "image"


def clean_stored_blocks(conn) -> dict:
    """이미 추출해 둔 블록의 텍스트를 정화한다 — 재추출 없이, 전부 로컬, 비용 0.

    91편을 다시 뜯을 필요 없이 깨진 글자만 걷어낸다. 블록 번호(block_order)는
    **그대로 둔다** — 번역 캐시가 이 번호로 묶여 있어 다시 매기면 이미 돈 낸 번역이
    엉뚱한 문단에 붙는다. 잔해 블록은 그 블록의 번역까지 함께 지운다(잔해의 번역도 잔해).
    """
    rows = conn.execute(
        "SELECT doc_id, block_order, kind, text_en FROM blocks WHERE text_en != ''"
    ).fetchall()

    fixed = removed = 0
    for r in rows:
        clean = sanitize_text(r["text_en"] or "")
        # 그림·표 캡션은 짧아도 살려둔다(그림에 붙는 설명이라 잔해 판정이 위험)
        if r["kind"] == "text" and (not clean or is_math_debris(clean)):
            conn.execute(
                "DELETE FROM blocks WHERE doc_id=? AND block_order=?",
                (r["doc_id"], r["block_order"]),
            )
            conn.execute(
                "DELETE FROM translations WHERE doc_id=? AND block_order=?",
                (r["doc_id"], r["block_order"]),
            )
            removed += 1
        elif clean != r["text_en"]:
            conn.execute(
                "UPDATE blocks SET text_en=? WHERE doc_id=? AND block_order=?",
                (clean, r["doc_id"], r["block_order"]),
            )
            fixed += 1

    return {"scanned": len(rows), "fixed": fixed, "removed": removed}


def _attach_captions(blocks: list[Block]) -> None:
    """그림/표에 캡션 텍스트를 붙인다 — 같은 쪽의 가장 가까운 캡션, 없으면 다음 쪽 맨 위의 캡션.

    예전에는 "바로 앞뒤 블록 + 같은 쪽" 만 봐서, 한 쪽을 꽉 채운 그림(캡션이 다음 쪽)의 캡션이 빠졌다.
    규칙은 captions.match 한 곳에 있다(이미 저장된 논문은 읽을 때 같은 규칙으로 짝짓는다).
    """
    import captions

    # 그림·표의 종류는 아직 잠정이다(find_tables 가 그래프를 표로 잘못 읽는 일이 흔하다) → "?" 를 붙여,
    # 캡션 종류가 달라도 붙을 수 있게 하되 같은 종류를 먼저 고르게 한다. 확정은 _classify_regions 가 캡션을 보고 한다.
    # (2차 점검: 잠정 종류로 엄격히 거르니 새로 올린 25편에서 그림 40장이 캡션을 잃었다)
    items = [
        captions.Item(b.kind + "?" if b.kind in ("image", "table") else b.kind, b.page, b.text or "", bool(b.is_caption))
        for b in blocks
    ]
    pairs, _ = captions.match(items)
    for f, c in pairs.items():
        blocks[f].text = blocks[c].text
