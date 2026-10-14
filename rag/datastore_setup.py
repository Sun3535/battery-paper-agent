"""[1회성 수동 실행] Vertex AI Search 데이터스토어 생성.

크레딧이 실제로 깎이기 시작하는 지점이라 자동 실행에 넣지 않고, 호야가 준비 끝낸 뒤
직접 `python -m rag.datastore_setup` 으로 실행하는 스크립트로 남겨둠.

사전 준비 (이 스크립트 실행 전에 먼저 해야 함):
  1. gcloud auth login   (또는 서비스계정 키를 GOOGLE_APPLICATION_CREDENTIALS 로 지정)
  2. Discovery Engine API 활성화:
       gcloud services enable discoveryengine.googleapis.com --project=<PROJECT_ID>
  3. GCS 버킷 생성 (이름은 전역 유일해야 함):
       gsutil mb -l us gs://<BUCKET_NAME>
  4. rag/.env.example 을 참고해 .env 에 BATTERY_RAG_GCP_PROJECT_ID / BATTERY_RAG_GCS_BUCKET 채우기
  5. pip install -r rag/requirements.txt

이 스크립트가 하는 일: 위 버킷을 소스로 하는 비정형(unstructured) 데이터스토어를 만든다.
PDF를 실제로 색인(import)하는 건 gcs_sync.py 로 GCS에 업로드한 뒤, Vertex AI Search
콘솔의 "데이터 가져오기" 또는 후속 import_documents 배치로 진행한다 (문서 파싱은
비동기 작업이라 콘솔에서 진행상황을 보는 게 가장 안전).
"""

from __future__ import annotations

from . import config


def create_datastore() -> None:
    if not config.GCP_PROJECT_ID:
        raise SystemExit(
            "BATTERY_RAG_GCP_PROJECT_ID 미설정. .env 에 GCP 프로젝트 ID를 먼저 채워주세요."
        )

    from google.cloud import discoveryengine_v1 as discoveryengine  # pip install google-cloud-discoveryengine

    client = discoveryengine.DataStoreServiceClient()
    parent = client.collection_path(
        project=config.GCP_PROJECT_ID,
        location=config.GCP_LOCATION,
        collection="default_collection",
    )
    data_store = discoveryengine.DataStore(
        display_name="Battery Papers",
        industry_vertical=discoveryengine.IndustryVertical.GENERIC,
        solution_types=[discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH],
        content_config=discoveryengine.DataStore.ContentConfig.CONTENT_REQUIRED,
    )
    operation = client.create_data_store(
        parent=parent, data_store=data_store, data_store_id=config.DATASTORE_ID
    )
    print(f"데이터스토어 생성 요청 완료 (비동기): {operation.operation.name}")
    print("콘솔에서 진행 상황 확인: https://console.cloud.google.com/gen-app-builder/data-stores")


if __name__ == "__main__":
    create_datastore()
