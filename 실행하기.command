#!/bin/bash
# Battery Paper Agent — 실행 스크립트 (Mac)
# 이 파일을 더블클릭하면 됩니다(처음 열 때 "확인되지 않은 개발자" 경고가 나오면: 오른쪽 클릭 → 열기).
# 처음 한 번, 그리고 webapp/backend/requirements.txt 가 바뀌었을 때만 라이브러리를 설치합니다.
cd "$(dirname "$0")" || exit 1
echo ""
echo " === Battery Paper Agent ==="
echo ""
if ! command -v python3 >/dev/null 2>&1; then
  echo " [!] Python 이 설치되어 있지 않습니다. https://www.python.org/downloads/ 에서 3.10 이상을 설치하세요."
  read -r -p " 엔터를 누르면 닫힙니다." _; exit 1
fi
[ -f ".env" ] || { echo " [i] 설정 파일이 없어 기본값으로 만듭니다 (.env)"; cp ".env.example" ".env"; }
[ -d ".venv" ] || python3 -m venv .venv || { echo " [!] 가상환경을 만들지 못했습니다."; read -r _; exit 1; }
source .venv/bin/activate
if ! cmp -s "webapp/backend/requirements.txt" ".venv/requirements.installed"; then
  echo " [i] 필요한 라이브러리를 설치합니다. 몇 분 걸릴 수 있습니다."
  python -m pip install -r webapp/backend/requirements.txt || { echo " [!] 설치에 실패했습니다."; read -r _; exit 1; }
  cp "webapp/backend/requirements.txt" ".venv/requirements.installed"
fi
echo ""
echo " 브라우저에서 http://localhost:8100 으로 접속하세요. 끝내려면 이 창에서 Ctrl+C."
echo ""
(sleep 2 && open "http://localhost:8100") &
python -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8100
