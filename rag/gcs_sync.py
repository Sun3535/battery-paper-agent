"""crawler DB에서 로컬 PDF는 있지만 아직 GCS에 안 올라간 논문을 업로드한다.

업로드 후 gcs_uri 컬럼을 채워두면, 다음 단계(콘솔 "데이터 가져오기" 또는 향후
import_documents 배치)가 이 목록(crawler.db.papers_ready_for_search_index)을 소비한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # crawler 패키지 임포트용

from crawler import db as crawler_db  # noqa: E402

from . import config  # noqa: E402


def sync_pending() -> None:
    if not config.GCS_BUCKET:
        raise SystemExit("BATTERY_RAG_GCS_BUCKET 미설정. .env 에 버킷 이름을 먼저 채워주세요.")

    from google.cloud import storage  # pip install google-cloud-storage

    client = storage.Client(project=config.GCP_PROJECT_ID or None)
    bucket = client.bucket(config.GCS_BUCKET)

    uploaded = 0
    with crawler_db.connect() as conn:
        cur = conn.execute(
            "SELECT paper_id, local_pdf_path FROM papers "
            "WHERE local_pdf_path IS NOT NULL AND gcs_uri IS NULL"
        )
        rows = cur.fetchall()
        for row in rows:
            paper_id, local_path = row["paper_id"], row["local_pdf_path"]
            blob_name = f"papers/{paper_id.replace(':', '_')}.pdf"
            bucket.blob(blob_name).upload_from_filename(local_path)
            gcs_uri = f"gs://{config.GCS_BUCKET}/{blob_name}"
            conn.execute("UPDATE papers SET gcs_uri = ? WHERE paper_id = ?", (gcs_uri, paper_id))
            uploaded += 1

    print(f"GCS 업로드 완료: {uploaded}건 → gs://{config.GCS_BUCKET}/papers/")


if __name__ == "__main__":
    sync_pending()
