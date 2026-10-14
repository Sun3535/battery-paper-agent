"""
Step 4: Final Markdown Assembly
- 번역된 섹션 + AI 이미지 해설 + 요약/기여점 + 메타데이터를 하나의 마크다운으로 조립
- [Figure N 위치] 마커를 실제 이미지 링크 + AI 심층 해설로 치환
- 누락 이미지는 System Warning 문구로 대체
- 결과: /final_report/battery_paper_analysis.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = ROOT / "output" / "text"
TRANSLATION_DIR = TEXT_DIR / "translations"
REPORT_DIR = ROOT / "final_report"
REPORT_PATH = REPORT_DIR / "battery_paper_analysis.md"

MARKER_PATTERN = re.compile(r"\[\s*Figure\s+(\d+)\s+위치\s*\]", re.IGNORECASE)

SECTION_ORDER = [
    ("Abstract",     "1. Abstract (요약)"),
    ("Introduction", "2. Introduction (서론)"),
    ("Experimental", "3. Experimental (실험 방법)"),
    ("Results",      "4. Results and Discussion (결과 및 고찰)"),
    ("Conclusion",   "5. Conclusion (결론)"),
]


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_caption(fig_num: int) -> str:
    path = TEXT_DIR / f"Figure_{fig_num}_caption.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _substitute_markers(text: str, mapping: dict) -> str:
    """[Figure N 위치] 마커를 이미지 링크 + 캡션 블록으로 치환."""

    def replace(match: re.Match) -> str:
        fig_num = int(match.group(1))
        key = f"Figure_{fig_num}"
        meta = mapping.get(key)

        if not meta or meta.get("status") != "extracted":
            return (
                f"\n> ⚠️ **[System Warning]** Figure_{fig_num} 이미지를 원본 PDF에서 "
                f"자동으로 추출하지 못했습니다. 원본 논문을 참조해 주세요.\n"
            )

        # 이미지 경로는 final_report/ 기준 상대경로
        image_rel = f"../output/images/Figure_{fig_num}.png"
        caption = _load_caption(fig_num)
        caption_block = (
            f"> **📊 AI Figure 심층 분석:** {caption}"
            if caption
            else f"> **📊 AI Figure 심층 분석:** (캡션 생성 결과가 없습니다. 02_analyze_image.py 실행 여부 확인)"
        )
        return f"\n\n![Figure_{fig_num}]({image_rel})\n{caption_block}\n\n"

    return MARKER_PATTERN.sub(replace, text)


def _flag_missing_figures(metadata_mapping: dict) -> list[int]:
    return sorted(
        meta["figure_number"]
        for meta in metadata_mapping.values()
        if meta.get("status") != "extracted" and meta.get("figure_number") is not None
    )


def run() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    metadata = _load_json(TEXT_DIR / "metadata.json", {})
    summary = _load_json(TEXT_DIR / "summary.json", {"summary_3lines": [], "contribution": []})
    figure_mapping = _load_json(TEXT_DIR / "figure_mapping.json", {})

    if not figure_mapping:
        print("[WARN] figure_mapping.json 이 비어 있습니다. 01_extract.py 를 먼저 실행하세요.")

    translated_title = metadata.get("translated_title") or "[논문 제목 번역본]"
    original_title = metadata.get("original_title") or "[Original Title]"
    authors = metadata.get("authors") or "[Authors]"

    summary_lines = summary.get("summary_3lines") or []
    while len(summary_lines) < 3:
        summary_lines.append("(요약을 생성하지 못했습니다.)")

    contribution = summary.get("contribution") or ["(핵심 기여점을 생성하지 못했습니다.)"]

    lines: list[str] = []
    lines.append("---")
    lines.append(f"# {translated_title}")
    lines.append(f"**원제:** {original_title}")
    lines.append(f"**저자:** {authors}")
    lines.append("")
    lines.append("## 💡 3줄 핵심 요약")
    for i, item in enumerate(summary_lines[:3], start=1):
        lines.append(f"{i}. {item}")
    lines.append("")
    lines.append("## 🎯 연구의 핵심 기여점")
    for item in contribution:
        lines.append(f"- {item}")
    lines.append("")

    # 섹션 본문
    for canonical, header in SECTION_ORDER:
        body_path = TRANSLATION_DIR / f"{canonical}.md"
        if not body_path.exists():
            continue
        body = body_path.read_text(encoding="utf-8").strip()
        if not body:
            continue
        body = _substitute_markers(body, figure_mapping)
        lines.append(f"## {header}")
        lines.append("")
        lines.append(body)
        lines.append("")

    # 섹션에 포함되지 못했지만 추출된 Figure가 있다면 부록으로 노출
    used_nums = {int(m.group(1)) for m in MARKER_PATTERN.finditer("\n".join(lines))}
    leftovers = [
        meta for key, meta in figure_mapping.items()
        if meta.get("status") == "extracted" and meta.get("figure_number") not in used_nums
    ]
    if leftovers:
        lines.append("## 📎 Appendix — 추가 Figure")
        lines.append("")
        for meta in sorted(leftovers, key=lambda m: m["figure_number"]):
            num = meta["figure_number"]
            image_rel = f"../output/images/Figure_{num}.png"
            caption = _load_caption(num)
            lines.append(f"### Figure {num}")
            lines.append(f"![Figure_{num}]({image_rel})")
            if caption:
                lines.append(f"> **📊 AI Figure 심층 분석:** {caption}")
            lines.append("")

    lines.append("---")

    REPORT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    missing = _flag_missing_figures(figure_mapping)
    print("=" * 60)
    print(f"[DONE] 최종 리포트: {REPORT_PATH}")
    if missing:
        print(f"[WARN] 누락 Figure: {missing} → 본문에 System Warning 으로 표기됨")


if __name__ == "__main__":
    run()
