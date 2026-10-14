"""
Step 1: PDF Parsing & Asset Separation
- PyMuPDF로 페이지 단위 텍스트 추출 및 섹션 분리
- Figure/Table 이미지 추출 및 Figure_N.png 형식 저장
- 본문 내 [Figure N 위치] 마커 삽입
- 본문-이미지 교차 검증 (Cross-validation)

Usage:
    python scripts/01_extract.py input/paper.pdf
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
IMAGES_DIR = ROOT / "output" / "images"
TEXT_DIR = ROOT / "output" / "text"

FIGURE_REF_PATTERN = re.compile(r"(?:Fig(?:ure)?\.?)\s*(\d+)", re.IGNORECASE)


def extract_figure_numbers_from_text(text: str) -> set[int]:
    """본문에서 언급된 모든 Figure 번호 집합을 반환."""
    return {int(m.group(1)) for m in FIGURE_REF_PATTERN.finditer(text)}


def save_image(doc: fitz.Document, xref: int, out_path: Path) -> bool:
    """xref가 가리키는 이미지를 PNG로 저장. CMYK 등도 RGB로 변환."""
    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.n > 4:  # CMYK / alpha 변환
            pix = fitz.Pixmap(fitz.csRGB, pix)
        pix.save(str(out_path))
        pix = None
        return True
    except Exception as exc:
        print(f"[WARN] 이미지 저장 실패 (xref={xref}): {exc}")
        return False


def run(pdf_path: Path) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF를 찾을 수 없습니다: {pdf_path}")

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    full_text_parts: list[str] = []
    page_texts: list[str] = []

    figure_counter = 0
    figure_mapping: dict[str, dict] = {}
    seen_xrefs: set[int] = set()

    for page_num, page in enumerate(doc, start=1):
        page_text = page.get_text("text") or ""
        page_texts.append(page_text)

        # 같은 이미지가 여러 페이지에 중복 참조될 수 있어 xref 기준 dedup
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            figure_counter += 1
            figure_name = f"Figure_{figure_counter}"
            out_path = IMAGES_DIR / f"{figure_name}.png"

            ok = save_image(doc, xref, out_path)
            figure_mapping[figure_name] = {
                "figure_number": figure_counter,
                "page": page_num,
                "file": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "status": "extracted" if ok else "failed",
            }
            # 본문 마커: 해당 이미지가 위치했던 페이지 끝에 삽입
            page_text += f"\n[Figure {figure_counter} 위치]\n"

        full_text_parts.append(f"\n--- Page {page_num} ---\n{page_text}")

    doc.close()

    full_text = "".join(full_text_parts)
    (TEXT_DIR / "full_text.txt").write_text(full_text, encoding="utf-8")

    # 교차 검증: 본문 언급 Figure 번호 vs 실제 추출된 Figure 번호
    referenced = extract_figure_numbers_from_text(full_text)
    extracted = {meta["figure_number"] for meta in figure_mapping.values() if meta["status"] == "extracted"}

    missing = sorted(referenced - extracted)
    unreferenced = sorted(extracted - referenced)

    for num in missing:
        key = f"Figure_{num}"
        figure_mapping.setdefault(key, {
            "figure_number": num,
            "page": None,
            "file": None,
            "status": "missing",
        })
        print(f"[WARN] Figure_{num} 가 본문에 언급되었으나 이미지 추출에 실패했습니다.")

    for num in unreferenced:
        print(f"[WARN] Figure_{num} 이미지가 추출되었으나 본문에서 참조되지 않았습니다.")

    (TEXT_DIR / "figure_mapping.json").write_text(
        json.dumps(figure_mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 페이지별 텍스트도 별도 저장 (디버깅/섹션 분할용)
    (TEXT_DIR / "pages.json").write_text(
        json.dumps(page_texts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=" * 60)
    print(f"[DONE] 텍스트: {TEXT_DIR / 'full_text.txt'}")
    print(f"[DONE] 매핑: {TEXT_DIR / 'figure_mapping.json'}")
    print(f"[DONE] 이미지 {figure_counter}개 → {IMAGES_DIR}")
    print(f"[INFO] 본문 참조 Figure: {sorted(referenced)}")
    print(f"[INFO] 추출된 Figure: {sorted(extracted)}")
    if missing:
        print(f"[WARN] 누락된 Figure: {missing}")


def _pick_pdf() -> Path:
    if len(sys.argv) >= 2:
        return Path(sys.argv[1]).resolve()
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"input/ 디렉토리에 PDF가 없습니다: {INPUT_DIR}")
    return pdfs[0]


if __name__ == "__main__":
    run(_pick_pdf())
