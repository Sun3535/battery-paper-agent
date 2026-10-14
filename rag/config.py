"""RAG(Vertex AI Search) 설정 — GenAI App Builder 크레딧(₩1,475,511, 만료 2027-05-04) 전용 소비처.

crawler/ 와 달리 이 모듈은 GCP 리소스를 실제로 만들고 과금을 발생시킨다.
그래서 값은 전부 .env 로만 채우고 기본값은 비워둠(=미설정이면 스크립트가 안내 메시지 내고 멈춤).
"""

import os

# 2026-07-11 실제 생성 완료 — 아래는 이 환경의 실제 값(디폴트). .env로 덮어쓸 수 있음.
GCP_PROJECT_ID = os.getenv("BATTERY_RAG_GCP_PROJECT_ID", "")  # 기본값 없음 — 개인 프로젝트 ID 를 배포본에 싣지 않는다
GCP_LOCATION = os.getenv("BATTERY_RAG_LOCATION", "global")  # Vertex AI Search는 보통 global 권장
GCS_BUCKET = os.getenv("BATTERY_RAG_GCS_BUCKET", "")  # 기본값 없음 — 개인 버킷 이름을 배포본에 싣지 않는다(.env 에서 읽는다)
DATASTORE_ID = os.getenv("BATTERY_RAG_DATASTORE_ID", "battery-papers-datastore")
SEARCH_APP_ID = os.getenv("BATTERY_RAG_APP_ID", "battery-papers-search-app")

# 크레딧 잔액 가드 (Blog/src/utils/vertex_billing_guard.py 와 동일 설계, 완전히 별개의 크레딧)
INITIAL_CREDIT_KRW = 1_475_511
CREDIT_EXPIRES_KST = "2027-05-04T00:00:00+09:00"
WARNING_THRESHOLD_KRW = 100_000  # 이 밑으로 내려가면 경고만 (자동 차단은 안 함 — 개인 도구라 저빈도·저위험)
USD_TO_KRW = 1370  # Blog 관례와 동일 환산율
