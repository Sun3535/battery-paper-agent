"""로컬 PDF 일괄 등록 (비용 0원).

input/ 의 PDF들을 웹앱에 등록하고 추출 + 로컬 FTS5 색인까지 수행한다.
번역·GCS 업로드·클라우드 색인은 하드락(PAID_APIS_ENABLED)에 걸려 자동으로 건너뛴다.

사용:
    cd Article_Battery
    python webapp/backend/import_local.py              # input/*.pdf 전부
    python webapp/backend/import_local.py path/to.pdf  # 특정 파일
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import ingest  # noqa: E402
import store  # noqa: E402


def already_imported(conn, filename: str) -> bool:
    row = conn.execute("SELECT 1 FROM documents WHERE filename = ?", (filename,)).fetchone()
    return bool(row)


def main(paths: list[Path]) -> None:
    store.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    done = skipped = failed = 0

    for pdf in paths:
        with store.connect() as conn:
            if already_imported(conn, pdf.name):
                skipped += 1
                continue
            doc_id = uuid.uuid4().hex[:12]
            dest = store.UPLOAD_DIR / f"{doc_id}.pdf"
            dest.write_bytes(pdf.read_bytes())
            store.create_document(conn, doc_id, pdf.stem, pdf.name, dest)

        ingest.process_document(doc_id)  # 추출 + 참고문헌 + 로컬색인 (번역/클라우드는 락으로 스킵)

        with store.connect() as conn:
            row = store.get_document(conn, doc_id)
        if row and row["status"] == "ready":
            done += 1
            print(f"  ✔ {pdf.name} — {row['page_count']}p")
        else:
            failed += 1
            print(f"  ✘ {pdf.name} — {(row['error'] or '')[:70] if row else '실패'}")

    print(f"\n등록 {done} / 건너뜀(중복) {skipped} / 실패 {failed}")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    targets = [Path(a) for a in args] if args else sorted((PROJECT_ROOT / "input").glob("*.pdf"))
    if not targets:
        raise SystemExit("등록할 PDF가 없습니다 (input/ 폴더 확인).")
    print(f"{len(targets)}개 PDF 등록 시작 (추출·색인 전부 로컬, 비용 0원)\n")
    main(targets)
