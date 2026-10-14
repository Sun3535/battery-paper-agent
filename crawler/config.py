"""크롤러 설정 — 키워드/카테고리는 여기서만 수정 (스크립트 코드는 안 건드림).

battery_agent_ui.ipynb 파이프라인의 config.json과 같은 역할: 사용자가 직접
편집하는 제어판. 검색 대상 주제를 바꾸고 싶으면 KEYWORDS 리스트만 수정하면 됨.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # Article_Battery/
DB_PATH = BASE_DIR / "crawler" / "papers.db"

# 다운로드된 PDF는 기존 input/ 폴더에 그대로 쌓인다.
# → 마음에 드는 논문만 골라 scripts/01_extract.py 부터 기존 5단계 파이프라인을 그대로 돌리면 됨.
PDF_DOWNLOAD_DIR = BASE_DIR / "input"

# 검색 키워드 — label_ko는 로그/DB 표시용, query는 실제 API 검색어(영문 권장)
KEYWORDS = [
    {"query": "solid electrolyte ionic conductivity", "label_ko": "고체전해질"},
    {"query": "silicon anode lithium battery", "label_ko": "실리콘음극재"},
    {"query": "lithium metal anode", "label_ko": "리튬메탈음극"},
    {"query": "solid-state battery interface resistance", "label_ko": "전고체 계면저항"},
    {"query": "NMC cathode capacity retention", "label_ko": "NCM양극재"},
    {"query": "lithium sulfur battery shuttle effect", "label_ko": "리튬황전지"},
    # 2026-07-15 호야 추가 요청 (전고체 중심)
    {"query": "all-solid-state battery cathode composite", "label_ko": "전고체양극재"},
    {"query": "all-solid-state battery", "label_ko": "전고체"},
    {"query": "cathode active material lithium battery", "label_ko": "양극재"},
]

ARXIV_CATEGORIES = ["cond-mat.mtrl-sci", "physics.chem-ph"]  # arXiv 검색 범위를 관련 분야로 제한
MAX_RESULTS_PER_KEYWORD = 40  # 엄격 필터로 많이 걸러지므로 넉넉히 가져와 통과분 확보
REQUEST_TIMEOUT_SEC = 20
DOWNLOAD_OPEN_ACCESS_ONLY = True  # 저작권 문제 없는 오픈액세스 PDF만 자동 다운로드

# 엄격 관련성 필터 (crawler/relevance.py) — 제목/초록에 배터리 핵심어 없는 논문은 저장 안 함.
# 끄고 싶으면 False (그러면 arXiv 원본 결과를 그대로 저장 = 무관 논문 섞임).
RELEVANCE_FILTER = True
