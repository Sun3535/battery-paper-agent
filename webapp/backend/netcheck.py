"""네트워크 진단 — 이 PC(예: 사내망)에서 어떤 기능이 실제로 되는지 확인한다.

사내 인트라넷은 보통 구글 **로그인**과 구글 **스토리지**를 막는다. 하지만 기능마다
필요한 통신이 다르므로, 무엇이 막히고 무엇이 되는지 실제로 찔러봐야 판단할 수 있다.

특히 중요한 구분:
  · Vertex/GCS 경로 = gcloud **로그인**이 필요 → 로그인 차단 시 사용 불가
  · Gemini API 키 경로 = 로그인 없이 **HTTP 헤더에 키만** 실어 보냄
    → 방화벽이 도메인만 열어주면 로그인 차단과 무관하게 동작한다

사용:  python webapp/backend/netcheck.py
"""

from __future__ import annotations

import socket
import ssl
import sys
import urllib.error
import urllib.request

TIMEOUT = 6

# (그룹, 표시명, 호스트, 이 통신이 필요한 기능)
TARGETS = [
    ("AI 기능", "Gemini API (키 인증)", "generativelanguage.googleapis.com", "번역 · 그림분석 · AI 요약"),
    ("크레딧", "Vertex AI Search", "discoveryengine.googleapis.com", "크레딧 챗봇 요약"),
    ("크레딧", "Google Cloud Storage", "storage.googleapis.com", "클라우드 색인(논문 업로드)"),
    ("크레딧", "Google 로그인", "accounts.google.com", "gcloud 인증"),
    ("논문 수집", "arXiv", "export.arxiv.org", "arXiv 크롤링"),
    ("논문 수집", "OpenAlex", "api.openalex.org", "OpenAlex 크롤링"),
    ("논문 수집", "Semantic Scholar", "api.semanticscholar.org", "S2 크롤링"),
]


def probe(host: str) -> tuple[bool, str]:
    """TCP 443 연결 + TLS 핸드셰이크까지 시도. (성공여부, 사유)"""
    try:
        with socket.create_connection((host, 443), timeout=TIMEOUT) as sock:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(sock, server_hostname=host):
                return True, "연결됨"
    except socket.gaierror:
        return False, "DNS 조회 실패(차단 또는 내부망 미해석)"
    except (socket.timeout, TimeoutError):
        return False, "시간 초과(방화벽 차단 추정)"
    except ssl.SSLError as e:
        # 사내 프록시가 인증서를 바꿔치기하면 여기 걸린다 — 연결 자체는 되는 상태
        return True, f"연결되나 TLS 경고({type(e).__name__}) — 사내 프록시 가능성"
    except OSError as e:
        return False, f"차단({type(e).__name__})"


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("네트워크 진단 — 이 PC에서 각 기능이 가능한지 확인합니다\n")
    results: dict[str, bool] = {}
    group_prev = None
    for group, label, host, feature in TARGETS:
        if group != group_prev:
            print(f"[{group}]")
            group_prev = group
        ok, why = probe(host)
        results[label] = ok
        mark = "O" if ok else "X"
        print(f"  {mark} {label:22s} {host:38s} {why}")
        print(f"    └ 필요한 기능: {feature}")
    print()

    gemini = results.get("Gemini API (키 인증)", False)
    vertex = results.get("Vertex AI Search", False) and results.get("Google Cloud Storage", False)
    crawl = any(results.get(k, False) for k in ("arXiv", "OpenAlex", "Semantic Scholar"))

    print("── 판정 ──────────────────────────────────────────")
    print("  항상 가능(네트워크 불필요): PDF 추출 · 로컬 검색 · E-book 리더 · 그림/표/참고문헌")
    print(f"  AI 기능(번역·그림분석·AI요약): {'가능 — API 키만 등록하면 됨' if gemini else '불가 → 로컬 검색만 사용'}")
    print(f"  크레딧(Vertex) 경로          : {'가능' if vertex else '불가 → .env 에서 크레딧 경로를 끄세요'}")
    print(f"  논문 자동 크롤링             : {'가능' if crawl else '불가 → PDF를 수동으로 드래그해 넣으세요'}")
    print()
    if not gemini and not vertex:
        print("  ⇒ 권장 설정: SEARCH_MODE=keyword (완전 로컬·비용 0·네트워크 0)")
    elif gemini and not vertex:
        print("  ⇒ 권장 설정: SEARCH_MODE=ai + [사용자]에 API 키 등록 (크레딧 칸은 비워둘 것)")


if __name__ == "__main__":
    main()
