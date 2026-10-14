# Battery Paper Agent (논문책방)

## 받아서 바로 쓰기 (로그인 필요 없음)

1. 이 페이지 위쪽 초록색 **Code → Download ZIP**을 눌러 받고, 압축을 풀어요.
2. 실행
   - **Windows:** `실행하기.bat` 더블클릭
   - **Mac:** `실행하기.command` 더블클릭(처음엔 오른쪽 클릭 → 열기)
   - 처음 한 번은 필요한 라이브러리를 자동으로 깔아요(몇 분). 이후에는 바로 켜져요.
3. 브라우저에서 `http://localhost:8100`이 열려요.

- 필요한 것: Python 3.10 이상([python.org](https://www.python.org/downloads/), Windows는 설치할 때 "Add Python to PATH" 체크).
- API 키는 화면의 자격증명 칸이나 `.env`(처음 실행할 때 `.env.example`로 만들어져요)에 넣어요. 키는 이 PC에만 저장돼요.
- 자세한 설치·업그레이드: `설치안내.md`. 아래 설명의 `Article_Battery` 폴더는 압축을 푼 폴더(예: `battery-paper-agent-main`)를 말해요.

---

# Battery Paper → Korean Markdown Pipeline

이차전지(Secondary Battery) 분야 영문 논문 PDF를 입력으로 받아,
블로그/사내 위키에 그대로 배포 가능한 **한국어 고품질 마크다운 리포트**를
자동 생성하는 4단계 파이프라인입니다.

- 본 저장소는 **VS Code + Python 가상환경** 기반 로컬 실행을 전제로 합니다.
- Claude Code 없이도 동작하며, 외부 AI 호출은 **Google Gemini API** 만 사용합니다.

---

## 📂 디렉토리 구조

```
Article_Battery/
├── battery_agent_ui.ipynb  # 🖥️ Jupyter 실행 파일 (Gradio GUI 진입점)
├── input/                  # 분석할 원본 PDF 논문을 여기에 넣습니다
├── output/
│   ├── images/             # Step 1에서 추출한 Figure 이미지 (Figure_1.png …)
│   └── text/               # 파싱 텍스트, 매핑 JSON, 섹션별 번역, 요약, 캡션 등
├── scripts/
│   ├── _models.py          # Gemini 모델 객관식 레지스트리 (12종)
│   ├── 01_extract.py
│   ├── 02_analyze_image.py
│   ├── 03_translate_summarize.py
│   ├── 04_assemble.py
│   └── 05_export_docx.py
├── final_report/           # 최종 마크다운/Word 결과물
├── config.json             # 🛠️ 프롬프트 제어판 (사용자가 직접 수정)
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 빠른 시작 (다른 PC / VS Code 기준)

### 1) 저장소 가져오기
`Article_Battery` 폴더를 통째로 새 PC에 복사하거나 git clone 받습니다.

### 2) Python 가상환경 생성
Python 3.10 이상 권장.

**Windows (PowerShell)**
```powershell
cd Article_Battery
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
cd Article_Battery
python3 -m venv .venv
source .venv/bin/activate
```

### 3) 의존성 설치
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4) `.env` 파일 세팅
프로젝트 루트에서 `.env.example` 을 `.env` 로 복사한 뒤, 실제 Gemini API Key 로 교체합니다.

```bash
cp .env.example .env       # Windows 라면 copy .env.example .env
```

`.env` 내부:
```
GEMINI_API_KEY=sk-...실제_키...
```

> **주의:** `.env` 는 절대 git 이나 공용 저장소에 커밋하지 마세요.

### 5) 분석할 PDF 배치
`input/` 디렉토리에 PDF 파일 하나를 넣습니다. 예: `input/paper.pdf`

### 6) (선택) `config.json` 프롬프트 제어판 커스터마이징
분석하려는 논문의 주제에 맞게 루트의 [config.json](config.json) 을 편집하세요.
**파이썬 코드를 건드릴 필요 없이** Gemini 의 이미지 해설·번역 문체·요약 관점을 바꿀 수 있습니다.
자세한 필드 설명과 예시는 아래 **"🛠️ 프롬프트 제어판 (config.json)"** 섹션을 참고하세요.

### 7-A) **권장: Jupyter Notebook GUI 로 실행** 🖥️
한 번의 `Run All` 로 Gradio UI 가 열리고, 이후 모든 작업을 **웹 UI 에서 클릭만으로** 수행할 수 있습니다.

```bash
# VS Code 에서 battery_agent_ui.ipynb 열고 "Run All"
# 또는 CLI 에서:
jupyter notebook battery_agent_ui.ipynb
```

**UI 기능**
| 영역 | 기능 |
|------|------|
| 📂 입력 소스 | PDF 드래그&드롭 · 파일 선택 · 폴더 경로 Batch 중 자유 선택 |
| 🎛️ 모델 선택 | Vision/Text 모델을 각각 드롭다운으로 12종 중 선택 |
| ⚠️ 안전장치 | `-exp` 가 포함된 #10·#11 선택 시 **경고 토스트** 자동 표시 |
| 🏃 실행 | ▶️ 버튼 → Step 1~5 자동 실행, 실시간 로그 + 진행률 바 |
| 📁 결과 | 완료 시 `.md` / `.docx` 다운로드 링크 자동 생성 (Batch 시 논문별 파일명) |

> 노트북을 열었을 때 Kernel 이 오프라인이면 VS Code 에서 `Python 3` 커널을 선택해 주세요.
> Gradio 가 기본적으로 `http://127.0.0.1:7860` 에 바인딩되며, 다른 프로세스가 점유 중이면 자동으로 다음 포트를 사용합니다.

### 7-B) (대안) 스크립트를 순서대로 CLI 실행
GUI 없이 자동화 파이프라인에 넣고 싶을 때는 순차 실행도 그대로 지원합니다.

```bash
python scripts/01_extract.py                 # PDF → 텍스트 + 이미지 + 매핑
python scripts/02_analyze_image.py           # 이미지 → Gemini 한글 심층 해설
python scripts/03_translate_summarize.py     # 섹션별 한글 번역 + 3줄 요약 + 기여점
python scripts/04_assemble.py                # 최종 마크다운 조립
python scripts/05_export_docx.py             # (선택) Word(.docx) 변환
```

정상 종료 시 결과물은 다음 경로에 생성됩니다.

```
final_report/battery_paper_analysis.md     # 블로그/위키 배포용
final_report/battery_paper_analysis.docx   # 공유·인쇄용 Word 보고서 (이미지 포함)
```

---

## 🧠 파이프라인 개요

| Step | 스크립트 | 기본 모델 | 주요 라이브러리 | 출력물 |
|------|-----------|-----------|------------------|---------|
| 1 | `01_extract.py` | — | PyMuPDF, re | `output/text/full_text.txt`, `output/images/Figure_*.png`, `output/text/figure_mapping.json` |
| 2 | `02_analyze_image.py` | **gemini-1.5-pro** (Vision) | google-generativeai, python-dotenv | `output/text/Figure_*_caption.txt` — 프롬프트: `config.json` ▸ `vision_analysis` |
| 3 | `03_translate_summarize.py` | **gemini-1.5-flash** (Text) | google-generativeai, python-dotenv | `output/text/translations/*.md`, `metadata.json`, `summary.json` — 프롬프트: `config.json` ▸ `translation`·`summarization` |
| 4 | `04_assemble.py` | — | 표준 라이브러리 | `final_report/battery_paper_analysis.md` |
| 5 | `05_export_docx.py` | — | python-docx | `final_report/battery_paper_analysis.docx` (이미지 임베드) |

### 💰 Hybrid 모델 전략 (비용 1/10 수준으로 절감)
Step 2 와 Step 3 는 **용도에 따라 서로 다른 모델**을 사용하도록 분리되어 있습니다.

| 단계 | 작업 특성 | 기본 모델 | 단가 (백만 토큰, 2026-Q1 기준) |
|------|-----------|-----------|--------------------------------|
| Step 2 이미지 해설 | 고차원 멀티모달 추론 | `gemini-1.5-pro` (#2) | 입력 $1.25 / 출력 $5.00 |
| Step 3 번역·요약 | 경량 언어 변환 | `gemini-1.5-flash` (#1) | 입력 $0.075 / 출력 $0.30 |

Flash 는 Pro 대비 입·출력 모두 **약 1/16** 가격이며, 번역 품질은 논문 요약·번역 수준에서 Pro 와 유의미한 차이를 보이지 않습니다.
논문 1편(본문 ~1만 단어 + Figure 4~6장) 기준 **대략 30~50원** 수준으로 분석이 가능합니다.

### 🎛️ 모델 객관식 선택 (`GEMINI_*_MODEL = 번호`)
모델은 [scripts/_models.py](scripts/_models.py) 의 중앙 레지스트리에 번호로 등록되어 있습니다.
`.env` 에서 **번호 한 글자만** 바꾸면 파이썬 코드를 건드리지 않고 모델을 교체할 수 있습니다.

| 번호 | 모델명 | 세대 | 특징 |
|------|--------|------|------|
| **#1** | `gemini-1.5-flash` | 1.5 | 저렴·빠름. **번역/요약 기본값** |
| **#2** | `gemini-1.5-pro` | 1.5 | 고품질 멀티모달. **이미지 해설 기본값** |
| **#3** | `gemini-2.5-flash` | 2.5 | 최신 Flash · 한국어 안정성↑ |
| **#4** | `gemini-2.5-pro` | 2.5 | 최신 Pro · 최고 품질 |
| **#5** | `gemini-2.0-flash` | 2.0 | 2.0 세대 Flash |
| **#6** | `gemini-2.0-flash-lite` | 2.0 | 초경량·초저가 |
| **#7** | `gemini-1.5-flash-8b` | 1.5 | 8B 파라미터. **극저가·초고속** (대량 배치) |
| **#8** | `gemini-1.5-pro-latest` | 1.5 | 1.5 Pro 최신 패치 자동 추적(별칭) |
| **#9** | `gemini-1.5-flash-latest` | 1.5 | 1.5 Flash 최신 패치 자동 추적(별칭) |
| **#10** | `gemini-2.0-pro-exp` | 2.0 | ⚠️ 실험 모델 (사전 경고 없이 회수 가능) |
| **#11** | `gemini-2.0-flash-thinking-exp` | 2.0 | ⚠️ Thinking 실험 (응답 포맷 상이) |
| **#12** | `gemini-2.5-flash-lite` | 2.5 | 2.5 세대 최경량 |

> ⚠️ **`-exp` / `-thinking-exp` 접미 모델**은 Google 이 사전 예고 없이 회수·파라미터 변경을 할 수 있습니다. 자동화 프로덕션에는 #1–#6, #12 등 **stable 라인**을 권장합니다.

`.env` 작성 예시:

```env
# ① 기본 Hybrid (가장 저렴)
GEMINI_VISION_MODEL=2
GEMINI_TEXT_MODEL=1

# ② 최신 2.5 세대로 전부 업그레이드
GEMINI_VISION_MODEL=4
GEMINI_TEXT_MODEL=3

# ③ 대량 배치용 극저가 모드 (1.5 Flash 8B + 2.0 Flash Lite)
GEMINI_VISION_MODEL=6
GEMINI_TEXT_MODEL=7

# ④ 레지스트리에 없는 모델은 이름으로 직접 지정도 가능
GEMINI_TEXT_MODEL=gemini-3.1-pro
```

> 새 Gemini 세대가 나오면 [scripts/_models.py](scripts/_models.py) 의 `MODEL_CHOICES` 딕셔너리에
> `13: "gemini-3.1-pro"` 처럼 **한 줄만 추가**하면 즉시 `GEMINI_*_MODEL=13` 로 선택할 수 있습니다.

### 🛠️ 프롬프트 제어판 (`config.json`)

루트의 `config.json` 은 **사용자가 파이썬 코드를 수정하지 않고** Gemini 동작을 제어하는 제어판입니다.
Step 2 와 Step 3 는 실행 시점에 이 파일을 읽어 프롬프트를 동적으로 조립합니다.

```json
{
  "vision_analysis": {
    "role": "당신은 이차전지 소재 및 전기화학 분석 최고 전문가입니다.",
    "focus_points": "특히 사이클 수명(Cycle life), 쿨롱 효율(Coulombic efficiency), 그리고 임피던스(EIS) 변화에 집중해서 분석해 주세요.",
    "output_format": "결과는 반드시 '1. 데이터 개요, 2. 핵심 발견, 3. 성능에 미치는 영향' 3가지 항목으로 나누어 한글로 작성하세요."
  },
  "translation": {
    "tone_and_manner": "전문적이고 학술적인 KCI 논문 스타일의 건조한 문체로 번역하세요.",
    "terminology": "Cathode는 '양극재', Anode는 '음극재', Electrolyte는 '전해질'로 통일하세요."
  },
  "summarization": {
    "instruction": "이 논문이 기존 연구의 한계를 어떻게 극복했는지(Novelty)를 중심으로 3줄 요약하세요."
  }
}
```

| 필드 | 적용 단계 | 역할 |
|------|-----------|------|
| `vision_analysis.role` | Step 2 | 모델에게 부여할 **역할(Role)** 선언 |
| `vision_analysis.focus_points` | Step 2 | 이미지에서 집중 분석할 **포인트** |
| `vision_analysis.output_format` | Step 2 | 해설의 **출력 형식/구조** |
| `translation.tone_and_manner` | Step 3 | 번역문의 **문체/톤** |
| `translation.terminology` | Step 3 | **전문용어 통일** 규칙 (예: Cathode → 양극재) |
| `summarization.instruction` | Step 3 | **3줄 요약 관점** 커스터마이징 |

> Step 2 는 `role + focus_points + output_format` 을 빈 줄로 연결해 **하나의 시스템 프롬프트**로 조립합니다.
> Step 3 는 번역 프롬프트 내부에 `[사용자 지정 번역 규칙]` 블록을, 요약 프롬프트에 `[사용자 지정 요약 지시사항]` 블록을 자동 삽입합니다.
> `config.json` 이 없거나 파싱 실패 시 스크립트는 안전한 기본 프롬프트로 자동 폴백합니다 (파이프라인이 멈추지 않음).

#### 🔬 사용 예시 — 전고체 배터리(Solid-state battery) 논문 분석
`config.json` 의 `vision_analysis.focus_points` 만 아래처럼 교체하면, Gemini 가 그래프·모식도 해설의 초점을
고체 전해질 특성으로 자동 전환합니다. 코드는 손대지 않아도 됩니다.

```json
"focus_points": "고체 전해질의 이온 전도도(Ionic conductivity)와 전극-전해질 계면 저항(Interfacial resistance)에 집중해서 분석해 주세요."
```

다른 주제로 스왑할 때의 빠른 가이드:

| 논문 주제 | 추천 `focus_points` 예시 |
|-----------|-------------------------|
| 리튬-황 배터리 | "폴리설파이드 셔틀 현상(shuttle effect)과 황 활용률(sulfur utilization)에 집중해서 분석해 주세요." |
| 고니켈 NCM 양극재 | "니켈 함량에 따른 층상구조 안정성과 장기 사이클에서의 용량 유지율에 집중해서 분석해 주세요." |
| 실리콘 음극 | "부피 팽창(volume expansion)과 SEI 형성이 쿨롱 효율에 미치는 영향에 집중해서 분석해 주세요." |
| 전고체 배터리 | "고체 전해질의 이온 전도도와 전극-전해질 계면 저항에 집중해서 분석해 주세요." |

### 교차 검증(Cross-validation)
Step 1 은 본문에서 `Fig.\s*\d+` / `Figure\s*\d+` 정규식으로 언급된 Figure 번호 집합과,
실제 추출된 이미지 파일명의 번호 집합을 비교합니다. 불일치가 발생하면:

- 터미널에 경고 로그 출력
- `figure_mapping.json` 의 해당 항목에 `"status": "missing"` 기록

Step 4 는 이 정보를 바탕으로 본문의 `[Figure N 위치]` 마커를 다음과 같이 치환합니다.

- 정상 추출: `![Figure_N](../output/images/Figure_N.png)` + AI 심층 해설 블록
- 누락:
  ```
  > ⚠️ **[System Warning]** Figure_N 이미지를 원본 PDF에서 자동으로 추출하지 못했습니다. 원본 논문을 참조해 주세요.
  ```

### API Key 보안
모든 Gemini 호출은 스크립트 최상단의 다음 패턴을 따르며, 키는 `.env` 에서만 로드됩니다.

```python
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
```

---

## 🛠️ 자주 겪는 문제

| 증상 | 해결 |
|------|------|
| `ModuleNotFoundError: fitz` | `pip install PyMuPDF` (패키지명이 `fitz` 가 아님) |
| `KeyError: 'GEMINI_API_KEY'` | `.env` 파일을 프로젝트 루트에 만들고 키 입력 |
| 섹션이 하나도 감지되지 않음 | `output/text/full_text.txt` 를 열어 헤더 표기 확인 → `03_translate_summarize.py` 의 `SECTION_ALIASES` 에 alias 추가 |
| 이미지가 너무 많이/적게 추출됨 | PDF 내부에 로고·아이콘도 이미지로 들어있을 수 있습니다. `figure_mapping.json` 의 `unreferenced` 경고를 확인 후 수동 정리 |
| Gemini rate limit | 각 스크립트는 호출 사이 약 1.2초 sleep. 한도 초과 시 잠시 대기 후 재실행 (중간 산출물은 캐시되므로 이어서 진행됩니다) |

---

## 📝 최종 마크다운 템플릿

```
# [논문 제목 번역본]
**원제:** [Original Title]
**저자:** [Authors]

## 💡 3줄 핵심 요약
1. ...
2. ...
3. ...

## 🎯 연구의 핵심 기여점
- ...

## 1. Abstract (요약)
...

## 2. Introduction (서론)
...

## 3. Results and Discussion (결과 및 고찰)
...
![Figure_1](../output/images/Figure_1.png)
> **📊 AI Figure 심층 분석:** ...

## 4. Conclusion (결론)
...
```

각 스크립트는 **중복 실행 시 기존 산출물을 유지**(SKIP)하므로, API 장애나 중단 후에도
안전하게 이어서 실행할 수 있습니다.

---

## 🔍 논문 자동 수집 + 교차검색 (신규, 2026-07-11)

위 5단계 파이프라인은 **한 편의 PDF**를 한글 리포트로 바꾸는 도구입니다. 아래 2개 모듈은
**여러 논문을 자동으로 찾고, 쌓인 논문들을 가로질러 질문**하는 기능을 더합니다. 기존 5단계
스크립트는 전혀 건드리지 않았고, 완전히 분리된 선택 기능입니다.

### 1) `crawler/` — 무료 논문 크롤러 (바로 사용 가능)

arXiv + Semantic Scholar API(둘 다 무료, 키 불요)로 `crawler/config.py`에 등록된 키워드
(고체전해질/실리콘음극재/리튬메탈음극/전고체 계면저항/NCM양극재/리튬황전지)에 해당하는
신규 논문을 찾아 `crawler/papers.db`(SQLite)에 메타데이터로 쌓고, 오픈액세스 PDF는
기존 `input/` 폴더에 내려받습니다. 마음에 드는 논문만 골라 `python scripts/01_extract.py`부터
기존 파이프라인을 그대로 돌리면 됩니다.

```bash
pip install -r crawler/requirements.txt
python -m crawler.run_crawl              # 메타데이터 수집 + PDF 다운로드
python -m crawler.run_crawl --no-download # 메타데이터만
python -m pytest crawler/tests            # 단위 테스트 (실 API 호출 없음, 픽스처 기반)
```

키워드를 바꾸고 싶으면 `crawler/config.py`의 `KEYWORDS`만 수정하면 됩니다(코드 수정 불필요).
Semantic Scholar는 키 없이도 동작하지만 레이트리밋이 낮으니, 자주 돌릴 계획이면
`crawler/.env.example` 참고해 무료 키를 발급받는 걸 권장합니다.

**엄격 관련성 필터 (`crawler/relevance.py`, 기본 ON):** arXiv 검색은 키워드 매칭이 느슨해
배터리와 무관한 재료과학 논문(고체산화물 연료전지, force field 등)이 대량으로 섞입니다.
그래서 제목/초록에 배터리 핵심어(battery/anode/cathode/electrolyte/li-ion/solid-state
battery/dendrite/polysulfide 등)가 실제로 있는 논문만 저장합니다. 끄려면 `config.py`의
`RELEVANCE_FILTER = False`. 필터가 많이 걸러내므로 `MAX_RESULTS_PER_KEYWORD`는 40으로
넉넉히 잡아둡니다.

> 한계 2가지: ① 키워드 필터라 "electrolyte"를 한 번만 언급한 계산화학 논문 같은 경계 사례는
> 아직 통과할 수 있습니다(완벽한 주제 분류는 아님). ② Semantic Scholar의 오픈액세스 링크는
> 상당수가 PDF 직링크가 아닌 출판사 랜딩페이지라 자동 다운로드에 실패합니다(메타데이터는 남음).
> arXiv 논문은 PDF 직링크라 안정적으로 받아집니다.

### 2) `rag/` — Vertex AI Search 기반 논문 교차검색 (✅ 구축 완료, 2026-07-11)

"내가 모은 논문들에서 최근 실리콘 음극재 사이클 수명 개선 방법이 뭐였지?" 같은 질문에
**LLM 요약 + 근거 논문 인용**으로 답하는 검색엔진입니다. **GenAI App Builder 체험
크레딧(₩1,475,511, 만료 2027-05-04)** 전용 소비처 — 이 크레딧은 Gemini API 직접
호출(위 5단계 파이프라인의 Step 2/3)에는 적용되지 않고 Vertex AI Search(Agent Builder)
SKU에만 적용되기 때문입니다.

> **순수히 "내 논문에 질문하고 싶다"뿐이면 [NotebookLM](https://notebooklm.google.com)이
> 무료로 동일 기능을 제공합니다.** 이 모듈의 진짜 가치는 나중에 배터리 카테고리 블로그
> 파이프라인처럼 **코드가 자동으로 논문 근거를 조회**해야 할 때 생깁니다(API 호출 가능).

**실제 구축된 리소스 (프로젝트 `<GCP 프로젝트 ID>`):**
| 리소스 | 값 |
|--------|-----|
| GCS 버킷 | `gs://<버킷 이름>/papers/` (논문 PDF 87건) |
| 데이터스토어 | `battery-papers-datastore` (GENERIC, 디지털 파서) |
| 검색 엔진 | `battery-papers-search-app` (Enterprise + LLM 애드온) |
| 결제 | 결제계정 `<결제 계정: 공개본에서 지움>` → App Builder 크레딧으로 차감 |

**사용법 (질문하기):**
```bash
python -m rag.search_client "고체 전해질의 이온 전도도를 높이는 최근 접근법은?"
python -m rag.credit_guard   # 크레딧 잔액 추정치 확인
```
`gcloud auth login`만 되어 있으면 별도 ADC 설정 없이 동작합니다(내부적으로 gcloud 토큰 사용).

**논문을 더 추가하려면** (크롤 → 업로드 → 재색인):
```bash
python -m crawler.run_crawl          # 새 논문 수집 + PDF 다운로드
gcloud storage cp input/*.pdf gs://<버킷 이름>/papers/
# 그다음 콘솔 "데이터 가져오기"(INCREMENTAL) 또는 documents:import 재호출
```

> ⚠️ **비용 주의:** 검색 1회 = LLM 요약 생성분이 크레딧에서 차감됩니다(개인용 저빈도라
> 미미). GCS 저장 비용(수백 MB)은 크레딧 밖 카드 청구지만 월 수십 원 수준입니다.
> `rag/credit_guard.py`의 누적 추정치는 실 청구서로 나중에 캘리브레이션하세요.

셋업을 처음부터 재현하려면 `rag/datastore_setup.py`(파이썬 SDK 경로, ADC 필요)와 위
README의 REST 순서 둘 다 참고할 수 있습니다.

---

## 🖥️ 통합 AI 논문 에이전트 (웹앱, 2026-07-15)

브라우저에서 논문을 **드래그앤드롭으로 수집 → 한국어 E-book으로 읽기 → 챗봇에게 질문**까지
한 화면에서 하는 풀스택 앱입니다. 위의 CLI 파이프라인들을 UI로 묶은 것입니다.

### 실행

```bash
# 터미널 1 — 백엔드 (FastAPI, :8100)
cd Article_Battery
pip install -r webapp/backend/requirements.txt
python -m uvicorn webapp.backend.main:app --port 8100

# 터미널 2 — 프론트엔드 (React+Vite, :5173)
cd Article_Battery/webapp/frontend
npm install
npm run dev
```
브라우저에서 http://localhost:5173 접속.

### 화면 구성

메인 화면은 **논문 라이브러리 하나**이고, 나머지는 필요할 때 열리는 패널입니다
(우측 = E-book 리더 / 좌측 = AI 챗봇). 화면을 갈아타지 않고 **원문을 보면서 물어볼 수 있게** 한 구조입니다.

| 패널 | 여는 법 | 기능 |
|------|---------|------|
| **📥 논문 라이브러리** | 기본 화면 | **표지(PDF 1페이지) + 실제 논문 제목**으로 서가처럼 보여줍니다. 상단 검색창으로 제목 필터링. PDF 드래그앤드롭 → 본문·그림·표 추출 + 로컬 검색색인(항상 무료). 유료 기능 2종은 **체크박스 = 앞으로 업로드할 논문에 자동 적용 / [실행] 버튼 = 지금 체크한 논문에만 즉시 실행**. ☐한국어 번역(~₩121/편) ☐그림·표 AI 분석(~₩30/편). 기본 OFF(0원) |
| **📖 E-book 리더** | 카드 **더블클릭** (우측에서 열림) | 아래 별도 절 참고 |
| **💬 AI 챗봇** | 우하단 [AI챗봇] 버튼 또는 리더 좌측 툴바 (**좌측**에서 열림) | 수집된 논문을 근거로 답변. **체크한 논문이 있으면 그 논문들을 집중적으로 읽고**, 라이브러리의 나머지 논문은 참고로만 씁니다. 근거가 없으면 지어내지 않고 "자료 없음"이라고 답하며, 답변마다 근거 논문을 표시 |

그림·표·참고문헌은 리더 안에서 **원래 있던 자리 그대로** 보므로 별도 탭을 두지 않습니다.

### 카드 배지 — '완료'가 무엇의 완료인지 구분

유료 버튼이 두 개(번역·그림분석)라 '완료' 하나로는 어디에 이미 돈을 냈는지 알 수 없습니다.
그래서 카드에 **`✓ 번역 완료` / `✓ 그림분석 완료`** 를 따로 표시하고(부분 처리면 `번역 12/76`),
**체크한 논문 중 하나라도 이미 처리된 게 있으면 그 버튼을 잠급니다**(재과금 차단, 툴팁에 사유).

한 번 지불한 번역·그림분석 결과는 `translations` / `figure_analyses` 테이블에 영구 보관되고,
리더에서 [한국어]를 누르면 **저장된 데이터를 그대로 불러옵니다 — 다시 과금되지 않습니다.**

### E-book 리더

- **읽기 순서 그대로**: 번역된 본문 사이에 원본 그림이 **원래 있던 자리**에 삽입됩니다.
  (2단 조판·multi-panel Figure 인식. 실측: 168블록 논문에서 Figure가 19·25·30·44번 위치에 정확히 배치)
- **원본 이미지 무손상**: 그림은 PDF 영역을 그대로 렌더한 PNG입니다. 잘라내기·비율변경·워터마크 없음.
  (벡터 그래픽 Figure도 `cluster_drawings()`로 잡아 패널 통째로 보존)
- **좌측 세로 툴바**: 언어 전환(한국어 / 원문 / 나란히) · 글자 크기(A− / A+, **5~24, 기본 10**) ·
  [AI챗봇]. 스크롤해도 따라옵니다(sticky). 제목이 길어도 밀려나지 않도록 헤더가 아니라 본문에 둡니다.
- **글자 깨짐(□) 제거**: LaTeX 심볼 폰트는 ToUnicode 매핑이 없어 브라우저가 그릴 수 없는
  코드포인트가 섞여 나옵니다(폰트를 바꿔도 안 고쳐짐). 추출 단계에서 걸러내며, 이미 수집한
  논문은 `POST /api/maintenance/clean-text` 로 재추출 없이 정화합니다(무료).
- **영문 용어 한글 gloss (ruby)**: 한국어 뷰에서 학술 용어(cathode, electrolyte, XRD…)는
  검은색 영문 그대로 두되, 그 **바로 아래에 작은 회색 한글 뜻**을 루비 주석으로 깐다.
  예: `cathode`(아래에 회색으로 "양극"). 완전 로컬·무료 — `webapp/frontend/src/glossary.tsx`의
  용어사전(현재 79개)으로 렌더링 시 매핑하며, API 호출이 없어 하드락과 무관하게 동작한다.
  용어를 추가하려면 그 파일의 `GLOSSARY`에 `'term': '뜻'` 한 줄만 넣으면 된다. 긴 용어부터
  매칭하므로 `capacity retention`이 `capacity`로 쪼개지지 않는다.

### 번역 언어 규칙 (중요)

학술 용어·고유명사·화학식·단위는 **영어 그대로** 두고, 서술어·동사만 한국어로 옮깁니다.
실제 연구자가 쓰는 문체가 기준입니다.

> **원문**: The Li-rich cathode exhibits a high initial capacity of 250 mAh/g, but suffers from voltage decay.
> **번역**: 이 Li-rich cathode는 250 mAh/g의 높은 initial capacity를 **보이지만**, voltage decay를 **겪는다**.

규칙은 `webapp/backend/translate.py`의 `SYSTEM_RULE` 한 곳에서 관리합니다.

### 🏢 사내망(인트라넷) 배포 — 완전 로컬 모드

회사망은 구글 **로그인**과 **스토리지**를 막는 경우가 많습니다. 기능마다 필요한 통신이
다르므로, 먼저 그 PC에서 무엇이 되는지 확인하세요:

```bash
python webapp/backend/netcheck.py
```

각 엔드포인트에 실제로 붙어보고 "무엇이 가능한지"를 판정해 줍니다.

| 기능 | 필요한 통신 | 사내망에서 |
|------|-------------|-----------|
| PDF 추출 · **로컬 검색** · E-book 리더 · 그림/표/참고문헌 | **없음** | ✅ 항상 가능 |
| 번역 · 그림분석 · AI 요약 | `generativelanguage.googleapis.com` (**API 키 헤더만, 로그인 불필요**) | 방화벽이 이 도메인만 열어주면 가능 |
| 크레딧(Vertex AI Search) | gcloud **로그인** + GCS | ❌ 로그인 차단 시 불가 |
| 논문 자동 크롤링 | arxiv.org · openalex.org · semanticscholar.org | 정책에 따라 (막히면 PDF 수동 드래그) |

> 💡 **중요한 구분:** Gemini API는 **로그인이 아니라 HTTP 헤더에 키를 싣는 방식**입니다.
> 구글 로그인이 차단돼 있어도 이 도메인만 허용되면 AI 기능이 동작합니다.
> 반면 크레딧(Vertex) 경로는 gcloud 로그인이 필수라 로그인 차단 환경에서는 쓸 수 없습니다.

#### 🏢 회사 배포 설정 — **API 키 전용** (권장)

구글 로그인은 막혀 있지만 API 키는 쓸 수 있는 환경. `.env`를 이렇게 두면 됩니다:

```bash
ENABLE_CREDIT=false         # ★ 크레딧(Vertex) 옵션을 완전히 끔
SEARCH_MODE=ai              # 로컬 검색 + AI 요약
PAID_APIS_ENABLED=true      # 사용 허가 후
OFFLINE_MODE=false
USE_LOCAL_LLM=false
```

`ENABLE_CREDIT=false` 로 두면:
- [사용자] → [API] 화면에서 **크레딧 칸이 아예 사라지고**, "🏢 이 환경은 API 키 전용" 안내가 뜹니다
- 자격증명 후보에서 완전히 빠져 **시도조차 하지 않습니다** (gcloud 로그인 불필요)
- 기본 옵션이 자동으로 API 키가 됩니다

이 구성에서 **번역·그림분석·AI 요약·논문 1편 통독이 전부 동작**합니다. 실측 확인 완료.

> 참고: 읽는 자료가 공개 논문(arXiv 등)이면 API 키 경로에 아무 문제가 없습니다.
> 미발표 사내 자료를 다룰 일이 생기면 아래 로컬 LLM 또는 완전 로컬 모드를 쓰세요.

#### (선택) 사내 자료용 — 로컬 LLM (데이터가 PC 밖으로 안 나감)

Ollama 같은 로컬 LLM을 띄우면 AI 요약을 **외부 전송 없이** 쓸 수 있습니다.

```bash
# 1) Ollama 설치 후 모델 받기 (사내 승인 모델 권장)
ollama pull qwen2.5:7b

# 2) .env
USE_LOCAL_LLM=true
LOCAL_LLM_HOST=http://127.0.0.1:11434
LOCAL_LLM_MODEL=qwen2.5:7b
```
켜두면 챗봇이 **가장 먼저** 이 경로를 시도하고, 꺼져 있으면 자동으로 다음 경로로 넘어갑니다.
완전 로컬 모드에서도 동작합니다(외부 통신이 아니라 `127.0.0.1` 호출이므로).
검증: 호출이 루프백 주소로만 나가는지 테스트로 고정했습니다(`tests/test_local_llm.py`).

**완전 로컬 모드** — 외부 통신을 일절 하지 않으려면 `.env`:

```bash
OFFLINE_MODE=true
```

번역·그림분석·AI요약·크레딧 경로가 **전부 비활성화**되고, 논문 검색·E-book 리더·그림/표/
참고문헌만 남습니다. 화면 상단에 `📴 완전 로컬 모드 · 외부 통신 없음` 배지가 표시됩니다.
실측 검증: 이 모드에서 소켓 연결을 강제로 막아도 **외부 연결 시도 0회**로 모든 로컬 기능이
정상 동작합니다(논문 91편 검색·통독 66문단·리더 285블록).

### 💸 비용 구조 — 기본값은 **완전 0원**

기본 설정은 **어떤 유료 API도 부르지 않습니다.** 검색은 로컬에서, 추출도 로컬에서 합니다.

| 기능 | 구현 | 비용 |
|------|------|------|
| 논문 크롤링 (arXiv / Semantic Scholar) | 무료 공개 API | **0원** |
| PDF 본문·그림·표 추출 | PyMuPDF (로컬) | **0원** |
| **논문 전체 검색** | **SQLite FTS5 (로컬, BM25)** | **0원** |
| E-book 리더 (원문) | 로컬 | **0원** |
| 한국어 번역 | Gemini API | 유료 → 하드락으로 차단 중 |
| AI 요약 답변 (챗봇) | Vertex AI Search | 크레딧 → 하드락으로 차단 중 |

**로컬 검색 (`SEARCH_MODE=local`, 기본):** 논문 전문이 이미 SQLite에 들어 있으므로, 내장
FTS5 전문검색 + BM25 랭킹으로 "어느 논문이 이 주제를 다루고 뭐라고 썼는지"를 찾습니다.
**외부 호출 0회 · 오프라인 동작 · 실측 11ms** (논문 28편 / 6,186블록 기준). AI 요약은 없고,
대신 **매칭된 원문 구절**을 논문별로 하이라이트해 보여줍니다.

> 한글 검색이 되는 이유: 토크나이저를 `trigram`으로 씁니다. 기본 `unicode61`은 조사를 못 떼서
> "음극재"로 "음극재**의**"를 못 찾습니다(실측). trigram은 부분 문자열 매칭이라
> 한국어·영어·혼합 문체("이 cathode는 높은 capacity retention을 보인다")에 모두 걸립니다.

```bash
python webapp/backend/import_local.py   # input/의 PDF를 전부 등록·색인 (무료)
```

`SEARCH_MODE=cloud` 로 바꾸면 Vertex AI Search(LLM 요약 포함)를 쓰지만, 크레딧을 소비하며
하드락에 걸립니다.

### 🔬 그림·표 멀티모달 AI 분석 (유료, 수동 트리거)

우측 패널의 **[AI 분석] 버튼**을 누르면 선택한 논문의 그림·표를 Gemini Vision으로 분석합니다.
그림 PNG + **캡션 + 주변 본문 맥락**을 함께 넣어 "①데이터 개요 ②핵심 발견 ③논문 맥락 연결"
3항목의 한국어 해설(용어는 영어 유지)을 만들고, 리더의 그림 아래와 자산 패널에 표시합니다.
분석문은 로컬 검색에도 색인되어 그래프 내용으로도 검색이 걸립니다.

- **비용**: Gemini API 직접 호출(카드, 크레딧 아님). flash 기준 **그림 1장 ≈ ₩3~6**.
- 자동 실행 없음 — 논문별 버튼으로만. 결과는 DB 캐시(그림 단위 즉시 저장, 재분석 재과금 0).
- 하드락(PAID_APIS_ENABLED=false) 중에는 버튼을 눌러도 잠김 안내만 나옵니다.
- 모델 교체: `.env` `FIGURE_ANALYSIS_MODEL` (기본은 TRANSLATE_MODEL과 동일).

### 🧠 챗봇 대화 기억 (맞춤형 스킬) — 헤더 "기억" 버튼

사용자가 던진 질문은 곧 그 사람의 관심사라, 다음 논문에서도 비슷한 걸 묻게 됩니다. Q&A를
압축 저장해두고 새 질문이 오면 **관련된 과거 Q&A만 골라** 챗봇에게 함께 전달합니다.

- **기본 OFF.** 헤더 [기억] 버튼 → 스위치로 언제든 켜고 끕니다.
- **저장·검색은 전부 로컬(0원)** — LLM 요약을 쓰지 않고 규칙 기반으로 압축(답변 260자 상한),
  회수는 SQLite FTS5. 크레딧은 **주입되는 입력 토큰만**(회당 약 70~100토큰) 추가되고,
  관련 기억이 없으면 0입니다.
- "정보 없음" 류 답변은 학습 가치가 없어 저장하지 않습니다.
- 어떤 기억이 이번 답변에 쓰였는지 채팅에 표시됩니다(비용 투명성). 개별·전체 삭제 가능.

### 🎯 질문 범위 — 전체 라이브러리 vs 논문 1편

챗봇 입력창 위 스위치로 두 루트를 고릅니다.

| 루트 | 동작 | 쓰는 때 |
|------|------|---------|
| **전체 (N편)** | 라이브러리 전체에서 관련 구절 검색 → 요약 | "이 주제를 다룬 논문이 뭐가 있지?" |
| **이 논문만** | 선택한 논문 **전문을 통째로** 읽혀서 답변 | Nature/Science 논문 한 편을 깊게 파고들 때 |

**「이 논문만」이 검색이 아니라 통독인 이유:** 질문에 조사가 붙으면(`impedance를`) trigram
검색이 영문 원문(`impedance`)과 매칭되지 않아 핵심 문장을 놓칩니다. 실측에서 검색 방식은
논문의 결론을 못 찾아 "자료에 없다"고 답했지만, 통독 방식은 정확히 답했습니다.

> **실측 A/B** — Q: "impedance를 낮추는 핵심 메커니즘과 그림에서 확인되는 수치는?"
> - 검색 방식(4구절): *"제공된 자료에 명시되어 있지 않습니다"* ❌
> - **통독 방식(66문단/11,951자)**: *"in-phase harmonic perturbations가 CCL 임피던스와 static
>   resistivity를 감소시킨다… 주로 ORR의 oscillating exchange current density가 주도하며…
>   i* variation의 Arrhenius slope가 proton conductivity보다 거의 7배 크기 때문"* ✅

비용: 논문 1편 ≈ 2,800 토큰 ≈ **질문당 ₩5~10**. 40,000자 상한이 있어 폭주하지 않습니다.

> ⚠️ **「이 논문만」은 Vertex(크레딧) 경로를 쓰지 않습니다.** Vertex AI Search는 데이터스토어
> 전체에서 스니펫을 뽑아 **다른 논문 내용을 섞기 때문**입니다(실측: 대상 논문에 없는
> synchrotron 문장이 답변에 포함됨). 범위 지정 질문은 문서 경계가 정확한 로컬 경로로만 답합니다.

### 🔬 그림 분석 → 챗봇 자동 연동 (돈 낸 만큼 답이 좋아지게)

**문제:** 클라우드 챗봇은 GCS의 PDF **텍스트**만 색인합니다. 그래프 속 수치는 PDF 텍스트에
없어서, 그림을 물으면 "자료 없음"이라고 답했습니다(실측 확인).

**해결:** 그림 AI 분석을 실행해두면, 질문할 때마다 관련 분석문을 **묻지 않아도 자동으로**
챗봇에게 전달합니다. 실측 A/B:

> Q: "κ가 0에서 0.1로 증가하면 Nyquist spectra는 어떻게 변하는가?"
> - **주입 전**: "제공된 발췌만으로는 알 수 없습니다"
> - **주입 후**: "임피던스 반원 직경이 약 320에서 120 mOhm cm²로 감소… charge transfer
>   resistance는 100에서 45 mOhm cm²로… βT=0일 때는 κ 변화에도 영향 없음" ✅

**그림 분석을 안 했다면** 챗봇이 유도 안내를 붙입니다 — "그래프 질문 같은데 지금은 확실히
답할 수 없습니다. [실행]을 누르면(그림 1장 ≈ ₩3~6) 축 라벨·수치까지 읽어 답할 수 있습니다."

비용 최적화: 그림 질문은 OR 매칭·최대 3건(넉넉히), 일반 질문은 AND 매칭·최대 2건(강하게
관련될 때만). 실측으로 본문 질문의 불필요한 주입 211토큰 → 0토큰이 되었습니다.
관련 판정·회수는 전부 로컬(0원)이며, 판별 규칙은 `webapp/backend/tests/test_figure_chat.py`
에서 오탐(압축·표면·발표 등)·미탐 41건으로 검증합니다.

### 🔑 자격증명 3종 관리 (헤더 [사용자] → 이름 옆 [API])

유료 기능(번역·그림분석)을 어떤 자격증명으로 돌릴지 사용자가 직접 고릅니다. 3칸 모두
**저장·수정·삭제**가 가능하고, 라디오로 **기본 사용할 것**을 선택합니다.

**입력 칸은 기본 1개** — Gemini API 키 하나만 등록하면 모든 기능이 동작합니다.

| 칸 | 넣는 값 | 언제 보이나 |
|----|---------|------------|
| **API 키** | Gemini API 키 (무료·유료 **아무거나**) | 항상 |
| **크레딧 (GCP)** | GCP **프로젝트 ID** (키 아님) | `ENABLE_CREDIT=true` 일 때만 |

> 예전에는 무료키·유료키·크레딧 3칸이었지만, 무료/유료는 **코드상 완전히 같은 것**이라
> (앱은 키 등급을 판별하지 못합니다) 혼란만 줘서 1칸으로 합쳤습니다. 사내망처럼
> `ENABLE_CREDIT=false` 인 환경에서는 **API 키 1칸만** 보이고 선택 라디오도 사라집니다.

**입력란 옆 `?` 아이콘**에 마우스를 올리면 안내가 뜹니다 — 내 키가 무료인지 유료인지
구분하는 법(결제 계정 연결 여부), 유료일 때 항목별 단가(번역 ₩121/편, 그림 ₩3~6/장),
무료 등급의 제약(요청 수 제한, 입력이 모델 개선에 쓰일 수 있음)까지.

**실행 순서 (Vertex 없는 사용자 대비):**
`① 고른 칸 → ② 다른 API 키 칸 → ③ 크레딧(Vertex) → ④ 안내 메시지`
Vertex/GCP가 아예 없어도 **API 키만으로 챗봇 AI 요약까지 전부 동작**합니다
(로컬 검색으로 근거 구절을 찾고, 그 구절만 Gemini API로 요약 — `webapp/backend/answer.py`).

- **표시는 항상 마스킹**: `AIzaSy••••••••••••wXyZ`. 원문은 **비밀번호를 확인해야** 서버가
  내려주고, 수정란에만 채워집니다. 목록 API에는 원문이 절대 포함되지 않습니다.
- **저장 위치는 이 PC의 로컬 파일** — `Article_Battery/crawler/papers.db`(SQLite). 외부로
  전송되지 않습니다. 개발자는 이 파일(또는 `ADMIN_TOKEN` + `/api/admin/users`)로 확인 가능.
- 선택한 칸에 따라 호출 경로가 바뀝니다: 무료키·유료키 → AI Studio, 크레딧 → Vertex(gcloud).
- 자격증명이 하나도 없으면 [실행] 시 **시작 전에** 안내가 뜹니다(헛돈 나갈 일 없음).

### 👤 사용자 계정 (헤더 우측 "사용자" 버튼)

번역은 Gemini API를 씁니다. 사용자마다 자기 API 키를 쓸 수 있도록 관리 UI를 넣었습니다.

- **평소에는 사용자명만** 보입니다. 비밀번호·API 키는 목록에 절대 안 나옵니다(서버가 안 내려줌).
- **이름 옆 [API] 버튼** → 비밀번호 입력 → 맞으면 API 키 입력/수정란이 열립니다.
- **이름 클릭** → 비밀번호 팝업(도용 방지) → 통과 시 그 사용자를 "활성"으로 지정 →
  이후 번역은 **그 사용자의 API 키**로 실행됩니다. (활성 사용자가 없으면 `.env`의 키로 폴백)
- **+ 버튼**으로 추가, 각 행의 **삭제 버튼**(비밀번호 확인)으로 제거.

**개발자 비번찾기 루트:** `.env`에 `ADMIN_TOKEN=...`을 설정하고
`GET /api/admin/users` 를 헤더 `X-Admin-Token`과 함께 호출하면 평문 비번·키 전체를 볼 수
있습니다. 토큰 미설정 시 이 라우트는 비활성(403). (또는 SQLite `users` 테이블을 직접 조회)

> ⚠️ **보안:** 비밀번호·API 키는 로컬 SQLite에 **평문**으로 저장됩니다("개발자 비번찾기"
> 요구를 위해 의도적). **localhost 개인/소규모 전용 — 공개 배포 금지.** 중요한 서비스의
> 비밀번호를 여기 재사용하지 마세요.

### 🔒 유료 API 하드락 (현재 **잠김** — 2026-07-15)

호야 지시로 **크레딧 사용·번역이 전면 중단**되어 있습니다. 실제 청구액을 확인한 뒤 허가할
예정입니다. `.env`의 한 줄이 스위치입니다:

```bash
PAID_APIS_ENABLED=false   # 현재값 — 잠김
PAID_APIS_ENABLED=true    # 허가 시 이렇게 바꾸면 즉시 해제 (코드 수정 불필요)
```

| 잠겨서 **차단**되는 것 | 잠겨도 **그대로 되는 것** |
|---|---|
| 번역 (Gemini API) | 논문 크롤링 (arXiv — 무료) |
| RAG 색인 (GCS 업로드 + import) | PDF 블록 추출, 그림·표·참고문헌 |
| 챗봇 검색 (Vertex AI Search 크레딧) | 원문 리더, **이미 번역된 논문 열람**(캐시) |

기본값은 `false`(fail-safe) — `.env`에 설정이 없어도 잠긴 것으로 간주합니다. 화면 우측 상단에
현재 잠금 상태가 항상 배지로 표시됩니다.

### ⚠️ 번역·그림분석 비용 (해제 시 확인)

번역·그림분석은 **Gemini API 직접 호출**이라 **App Builder 크레딧으로 차감되지 않습니다**
(그 크레딧은 Vertex AI Search 전용). **사용한 사람이 자기 API 키로 부담**하는 구조입니다.

| 항목 | 단위 비용 | 누가 내나 |
|------|-----------|-----------|
| 한국어 번역 | 논문 1편 ≈ **₩121** | 화면 [사용자]에 등록해 활성화한 **본인 API 키** |
| 그림·표 AI 분석 | 그림 1장 ≈ **₩3~6** (논문 ≈ ₩30) | 〃 |

`.env`의 `TRANSLATE_CHANNEL`로 호출 경로를 고릅니다:

| 채널 | 과금 대상 | 데이터 학습 | 용도 |
|------|-----------|------------|------|
| `aistudio` (기본) | 각 사용자가 등록한 자기 키 | ⚠️ 구글이 입력을 학습에 쓸 수 있음 | 공개 논문 |
| `vertex` | 이 PC의 gcloud 프로젝트 소유자 | ✅ 학습에 사용 안 함 | **미발표 연구·회사 자료** |

> 🔴 **미발표 연구나 회사 자료를 올릴 때는 `TRANSLATE_CHANNEL=vertex`로 바꾸세요.**
> AI Studio 경로로 올리면 연구 IP가 구글 학습 데이터로 들어갈 수 있습니다.

**API 키가 없으면** 번역·그림분석 실행 시 "화면 [사용자]에서 본인 API 키를 등록하세요"
안내가 뜹니다(키 발급: https://aistudio.google.com/apikey). 앱이 대신 부담하는 무료 경로는
없습니다 — 유료 기능은 쓰는 사람이 자기 키로 냅니다.

번역 결과는 SQLite에 **캐시**되고 **배치마다 즉시 저장**되므로, 재열람은 추가 비용이 없고
중단돼도 그때까지의 번역은 보존됩니다(재실행 시 남은 블록만 번역 → 재과금 0).

### 구조

```
webapp/
├── backend/          # FastAPI
│   ├── main.py       # 라우터 (업로드/목록/리더/자산/챗봇)
│   ├── extract.py    # ★ PDF → 읽기순서 블록 (텍스트·그림·표). E-book의 핵심
│   ├── translate.py  # Gemini 번역 (언어규칙 + 배치 + 채널 전환)
│   ├── references.py # 참고문헌 파싱
│   ├── ingest.py     # 업로드 후 백그라운드 파이프라인
│   └── store.py      # SQLite (documents/blocks/translations/refs)
└── frontend/         # React 18 + TS + Vite + AntD
    └── src/components/{DropZone,ChatPanel,AssetsPanel,ReaderView}.tsx
```
