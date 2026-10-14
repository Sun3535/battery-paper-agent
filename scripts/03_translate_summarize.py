"""
Step 3: Sectional Chunking & Translation/Summarization
- full_text.txt 를 주요 섹션(Abstract / Introduction / Experimental / Results / Conclusion)
  단위로 청킹
- 섹션별로 Gemini 호출 → 한글 전문 번역 (환각/토큰 폭주 방지)
- 전체 번역본 기반으로 [3줄 핵심 요약] + [연구의 핵심 기여점] 추출
- 메타데이터(원제/번역제목/저자)도 별도 추출

Usage:
    python scripts/03_translate_summarize.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

# scripts/_models.py 공용 레지스트리 import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _models import resolve_and_report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = ROOT / "output" / "text"
FULL_TEXT_PATH = TEXT_DIR / "full_text.txt"
TRANSLATION_DIR = TEXT_DIR / "translations"
CONFIG_PATH = ROOT / "config.json"

# 번역/요약은 Pro 대비 약 1/16 가격의 Flash 로 충분 → 기본값 #1: gemini-1.5-flash
# .env 에서 GEMINI_TEXT_MODEL=1~N 으로 객관식 변경 가능 (자세한 번호는 _models.py)
_TEXT_DEFAULT_NUM = 1

# 섹션 헤더 후보(소문자 비교용). 문서마다 표현이 달라 느슨하게 매칭한다.
SECTION_ALIASES: list[tuple[str, list[str]]] = [
    ("Abstract",     ["abstract", "summary"]),
    ("Introduction", ["introduction", "1. introduction", "i. introduction", "background"]),
    ("Experimental", ["experimental", "methods", "methodology", "materials and methods",
                      "experimental section", "experimental details"]),
    ("Results",      ["results and discussion", "results & discussion",
                      "results", "discussion"]),
    ("Conclusion",   ["conclusion", "conclusions", "concluding remarks", "summary and outlook"]),
]


def _configure() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit(
            "환경 변수 GEMINI_API_KEY 가 설정되지 않았습니다. "
            ".env 파일을 생성하고 키를 입력하세요 (.env.example 참고)."
        )
    genai.configure(api_key=api_key)


def _load_config() -> dict:
    """config.json 을 불러온다. 없거나 깨져 있으면 빈 dict 를 반환(기본 동작 유지)."""
    if not CONFIG_PATH.exists():
        print(f"[WARN] config.json 이 없습니다 → 기본 프롬프트 사용 ({CONFIG_PATH})")
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[WARN] config.json 파싱 실패 → 기본 프롬프트 사용: {exc}")
        return {}


def _normalize_line(line: str) -> str:
    # 앞쪽 번호(1., 1.1, I., II.)와 공백 제거 후 소문자화
    cleaned = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s*", "", line, flags=re.IGNORECASE)
    return cleaned.strip().lower().rstrip(":")


def split_sections(full_text: str) -> dict[str, str]:
    """본문을 섹션별로 분할. 헤더 라인으로 추정되는 단독 라인을 기준으로 자른다."""
    lines = full_text.splitlines()

    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in SECTION_ALIASES:
        for alias in aliases:
            alias_to_canonical[alias] = canonical

    # 섹션 시작 지점 탐지: 짧은 라인이 alias와 정확 매치될 때만 헤더로 인정
    starts: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 60:
            continue
        key = _normalize_line(stripped)
        if key in alias_to_canonical:
            starts.append((idx, alias_to_canonical[key]))

    # 같은 canonical 섹션이 여러 번 잡히면 첫 번째만 사용
    seen: set[str] = set()
    unique_starts: list[tuple[int, str]] = []
    for idx, canonical in starts:
        if canonical in seen:
            continue
        seen.add(canonical)
        unique_starts.append((idx, canonical))

    # 섹션이 전혀 잡히지 않으면 전체 본문을 Results 로 간주
    if not unique_starts:
        return {"Results": full_text.strip()}

    unique_starts.sort(key=lambda t: t[0])
    sections: dict[str, str] = {}
    for i, (start_idx, canonical) in enumerate(unique_starts):
        end_idx = unique_starts[i + 1][0] if i + 1 < len(unique_starts) else len(lines)
        body = "\n".join(lines[start_idx + 1:end_idx]).strip()
        if body:
            sections[canonical] = body
    return sections


def _call_gemini(model: genai.GenerativeModel, prompt: str, *, retries: int = 2) -> str:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = model.generate_content(prompt)
            return (resp.text or "").strip()
        except Exception as exc:
            last_exc = exc
            wait = 2 ** attempt
            print(f"[WARN] Gemini 호출 실패 (시도 {attempt + 1}/{retries + 1}): {exc}. {wait}s 대기 후 재시도")
            time.sleep(wait)
    raise RuntimeError(f"Gemini 호출 실패: {last_exc}")


def _build_translation_custom_block(tr_config: dict) -> str:
    """config.json 의 translation 항목을 프롬프트용 규칙 블록으로 변환."""
    tone = (tr_config.get("tone_and_manner") or "").strip()
    terminology = (tr_config.get("terminology") or "").strip()
    lines = []
    if tone:
        lines.append(f"• 문체(Tone & Manner): {tone}")
    if terminology:
        lines.append(f"• 전문용어 통일(Terminology): {terminology}")
    if not lines:
        return ""
    return "\n[사용자 지정 번역 규칙 (config.json)]\n" + "\n".join(lines) + "\n"


def translate_section(model: genai.GenerativeModel, canonical: str, body: str,
                      tr_config: dict) -> str:
    custom_block = _build_translation_custom_block(tr_config)
    prompt = (
        "당신은 이차전지(Secondary Battery) 분야 논문을 한국어로 번역하는 전문 번역가입니다.\n"
        f"아래는 논문의 '{canonical}' 섹션 원문입니다. 다음 규칙을 지켜 한국어로 전문 번역하세요.\n"
        "1) 원문에 없는 내용은 절대 추가하지 말 것 (환각 금지).\n"
        "2) 전문 용어(예: cathode, anode, SEI, coulombic efficiency, cycle stability)는 "
        "   한국어 정착 번역을 사용하되 필요 시 괄호 안에 영문 병기.\n"
        "3) [Figure N 위치] 와 같은 마커는 그 위치 그대로 원문대로 유지.\n"
        "4) '--- Page N ---' 같은 페이지 구분자는 제거하고 자연스러운 단락으로 재구성.\n"
        "5) 수식/단위(mAh g⁻¹, V vs. Li/Li⁺ 등)는 원문 표기 유지.\n"
        "6) 출력은 번역문만 포함하고 다른 설명은 붙이지 말 것.\n"
        f"{custom_block}\n"
        f"--- 원문 ({canonical}) ---\n{body}\n"
    )
    return _call_gemini(model, prompt)


def extract_metadata(model: genai.GenerativeModel, head_text: str) -> dict:
    prompt = (
        "아래는 이차전지 논문 PDF의 첫 두 페이지에서 추출한 원문입니다. "
        "여기서 다음 세 가지 정보를 JSON 으로 추출하세요. 찾지 못하면 값은 빈 문자열로 두세요.\n"
        "- original_title: 논문 원제(영문)\n"
        "- translated_title: 원제의 자연스러운 한국어 번역\n"
        "- authors: 저자 전체 목록 (원문 그대로, 쉼표 구분 문자열)\n"
        "JSON 외 다른 텍스트는 절대 출력하지 마세요.\n\n"
        f"--- 본문 ---\n{head_text[:6000]}\n"
    )
    raw = _call_gemini(model, prompt)
    # 코드블록 제거
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[WARN] 메타데이터 JSON 파싱 실패. 원본 응답:\n{raw[:400]}")
        data = {"original_title": "", "translated_title": "", "authors": ""}
    return {
        "original_title": data.get("original_title", ""),
        "translated_title": data.get("translated_title", ""),
        "authors": data.get("authors", ""),
    }


def build_summary(model: genai.GenerativeModel, translations: dict[str, str],
                  sum_config: dict) -> dict:
    instruction = (sum_config.get("instruction") or "").strip()
    custom_line = (
        f"\n[사용자 지정 요약 지시사항 (config.json)]\n{instruction}\n"
        if instruction else ""
    )
    joined = "\n\n".join(f"## {name}\n{body}" for name, body in translations.items())
    prompt = (
        "아래는 이차전지 논문을 섹션별로 한국어로 번역한 본문입니다. "
        "이 내용을 바탕으로 두 가지 결과를 JSON 으로 만드세요.\n"
        "1) summary_3lines: 논문의 핵심을 전달하는 3줄 요약. "
        "   각 줄은 60~90자 내외 한 문장으로, 배열 길이는 정확히 3.\n"
        "2) contribution: 연구의 핵심 기여점(Contribution)을 2~4개의 불릿으로. "
        "   각 항목은 한 문장, 배열로 반환.\n"
        f"{custom_line}"
        "JSON 외의 텍스트는 절대 출력하지 마세요.\n\n"
        f"--- 번역본 ---\n{joined[:18000]}\n"
    )
    raw = _call_gemini(model, prompt)
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[WARN] 요약 JSON 파싱 실패. 원본 응답:\n{raw[:400]}")
        data = {"summary_3lines": [], "contribution": []}

    lines = data.get("summary_3lines", [])
    if not isinstance(lines, list):
        lines = []
    lines = [str(x).strip() for x in lines if str(x).strip()][:3]
    while len(lines) < 3:
        lines.append("(요약을 생성하지 못했습니다.)")

    contrib = data.get("contribution", [])
    if not isinstance(contrib, list):
        contrib = [str(contrib)]
    contrib = [str(x).strip() for x in contrib if str(x).strip()]
    if not contrib:
        contrib = ["(핵심 기여점을 생성하지 못했습니다.)"]

    return {"summary_3lines": lines, "contribution": contrib}


def run() -> None:
    if not FULL_TEXT_PATH.exists():
        raise SystemExit("full_text.txt 가 없습니다. 먼저 01_extract.py 를 실행하세요.")

    _configure()
    TRANSLATION_DIR.mkdir(parents=True, exist_ok=True)

    full_text = FULL_TEXT_PATH.read_text(encoding="utf-8")
    sections = split_sections(full_text)
    if not sections:
        raise SystemExit("섹션 분할 결과가 비어 있습니다. full_text.txt 내용을 확인하세요.")

    config = _load_config()
    tr_config = (config.get("translation") or {})
    sum_config = (config.get("summarization") or {})

    model_name = resolve_and_report(
        os.getenv("GEMINI_TEXT_MODEL"),
        default_num=_TEXT_DEFAULT_NUM,
        label="텍스트 모델",
    )
    print(f"[INFO] 감지된 섹션: {list(sections.keys())}")
    print(f"[INFO] 번역 규칙 로드: tone={'O' if tr_config.get('tone_and_manner') else 'X'}, "
          f"terminology={'O' if tr_config.get('terminology') else 'X'}")
    print(f"[INFO] 요약 지시사항: {'O' if sum_config.get('instruction') else 'X'}")
    model = genai.GenerativeModel(model_name)

    translations: dict[str, str] = {}
    for canonical, body in sections.items():
        out_path = TRANSLATION_DIR / f"{canonical}.md"
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[SKIP] {canonical}: 이미 번역됨 ({out_path.name})")
            translations[canonical] = out_path.read_text(encoding="utf-8")
            continue

        print(f"[RUN ] {canonical}: 번역 중... ({len(body)} chars)")
        try:
            translated = translate_section(model, canonical, body, tr_config)
        except Exception as exc:
            print(f"[ERR ] {canonical}: 번역 실패 → {exc}")
            continue

        out_path.write_text(translated, encoding="utf-8")
        translations[canonical] = translated
        time.sleep(1.2)

    # 메타데이터 (논문 헤더 근처)
    meta_path = TEXT_DIR / "metadata.json"
    if not meta_path.exists():
        head_text = full_text[:8000]
        print("[RUN ] 메타데이터 추출 중...")
        metadata = extract_metadata(model, head_text)
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        print(f"[SKIP] 메타데이터 이미 존재 ({meta_path.name})")

    # 요약 + 기여점
    summary_path = TEXT_DIR / "summary.json"
    if not summary_path.exists():
        print("[RUN ] 3줄 요약 / 핵심 기여점 생성 중...")
        summary = build_summary(model, translations, sum_config)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        print(f"[SKIP] 요약 이미 존재 ({summary_path.name})")

    print("=" * 60)
    print(f"[DONE] 번역: {TRANSLATION_DIR}")
    print(f"[DONE] 메타데이터: {meta_path}")
    print(f"[DONE] 요약: {summary_path}")
    print(f"[INFO] 원제: {metadata.get('original_title', '')[:80]}")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(130)
