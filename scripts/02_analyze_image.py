"""
Step 2: Multimodal Figure Interpretation
- /output/images 의 Figure_N.png 를 Gemini Vision으로 분석
- 한글 심층 해설을 Figure_N_caption.txt 로 저장
- 01단계에서 누락(missing) 처리된 이미지는 스킵

Usage:
    python scripts/02_analyze_image.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

# scripts/_models.py 공용 레지스트리 import (스크립트의 부모 폴더가 곧 scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _models import resolve_and_report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "output" / "images"
TEXT_DIR = ROOT / "output" / "text"
MAPPING_PATH = TEXT_DIR / "figure_mapping.json"
CONFIG_PATH = ROOT / "config.json"

# 이미지 해설은 멀티모달 추론이 필수 → Pro 계열 기본값(#2: gemini-1.5-pro)
# .env 에서 GEMINI_VISION_MODEL=1~N 으로 객관식 변경 가능 (자세한 번호는 _models.py)
_VISION_DEFAULT_NUM = 2

# config.json 이 비어 있거나 파싱 실패 시에만 쓰이는 최소 fallback.
# 평상시 시스템 프롬프트는 config.json → _build_vision_prompt() 로 조립된다.
_DEFAULT_VISION_PROMPT = (
    "당신은 배터리 소재 전문가입니다. 이미지의 핵심 내용을 한글로 해설하세요. "
    "출력은 한글 서술문만 포함하고, 마크다운 헤더(##)는 사용하지 마세요."
)


def _configure() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit(
            "환경 변수 GEMINI_API_KEY 가 설정되지 않았습니다. "
            ".env 파일을 생성하고 키를 입력하세요 (.env.example 참고)."
        )
    genai.configure(api_key=api_key)


def _load_mapping() -> dict:
    if not MAPPING_PATH.exists():
        raise SystemExit("figure_mapping.json 이 없습니다. 먼저 01_extract.py 를 실행하세요.")
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[WARN] config.json 이 없습니다 → 기본 프롬프트 사용 ({CONFIG_PATH})")
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[WARN] config.json 파싱 실패 → 기본 프롬프트 사용: {exc}")
        return {}


def _build_vision_prompt(config: dict) -> str:
    """config.json 의 vision_analysis 항목을 하나의 시스템 프롬프트로 조립."""
    v = (config.get("vision_analysis") or {})
    ordered_parts = [
        v.get("role"),
        v.get("focus_points"),
        v.get("output_format"),
    ]
    parts = [p.strip() for p in ordered_parts if p and str(p).strip()]
    return "\n\n".join(parts) if parts else _DEFAULT_VISION_PROMPT


def analyze_one(model: genai.GenerativeModel, image_path: Path, system_prompt: str) -> str:
    uploaded = genai.upload_file(path=str(image_path))
    try:
        resp = model.generate_content([system_prompt, uploaded])
        return (resp.text or "").strip()
    finally:
        # 업로드된 파일 정리 (실패해도 무시)
        try:
            genai.delete_file(uploaded.name)
        except Exception:
            pass


def run() -> None:
    _configure()
    mapping = _load_mapping()
    config = _load_config()
    system_prompt = _build_vision_prompt(config)

    model_name = resolve_and_report(
        os.getenv("GEMINI_VISION_MODEL"),
        default_num=_VISION_DEFAULT_NUM,
        label="Vision 모델",
    )
    print(f"[INFO] config.json 기반 시스템 프롬프트 ({len(system_prompt)} chars) 적용")
    model = genai.GenerativeModel(model_name)

    total = 0
    done = 0
    skipped = 0

    for key, meta in sorted(mapping.items(), key=lambda kv: kv[1].get("figure_number", 0)):
        total += 1
        if meta.get("status") != "extracted":
            print(f"[SKIP] {key}: status={meta.get('status')} (누락 이미지 스킵)")
            skipped += 1
            continue

        image_path = ROOT / meta["file"]
        if not image_path.exists():
            print(f"[SKIP] {key}: 파일이 실제로 존재하지 않음 ({image_path})")
            skipped += 1
            continue

        out_path = TEXT_DIR / f"{key}_caption.txt"
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[SKIP] {key}: 캡션 이미 존재 ({out_path.name})")
            done += 1
            continue

        print(f"[RUN ] {key}: {image_path.name} 분석 중...")
        try:
            caption = analyze_one(model, image_path, system_prompt)
        except Exception as exc:
            print(f"[ERR ] {key}: Gemini 호출 실패 → {exc}")
            continue

        if not caption:
            print(f"[WARN] {key}: 빈 응답 수신")
            continue

        out_path.write_text(caption, encoding="utf-8")
        done += 1
        # Rate limit 완화
        time.sleep(1.2)

    print("=" * 60)
    print(f"[DONE] {done}/{total} 이미지 해설 저장 (스킵 {skipped})")
    print(f"[INFO] 출력 경로: {TEXT_DIR}")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(130)
