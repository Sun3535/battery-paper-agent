"""유료/크레딧 소비 하드락.

호야 지시(2026-07-15): 실제 청구액을 확인할 때까지 크레딧 사용·번역 전면 중단.
사용 허가가 다시 나올 때까지 **어떤 코드 경로도 돈 나가는 API를 호출하지 않는다.**

푸는 법: Article_Battery/.env 에서
    PAID_APIS_ENABLED=true
한 줄만 바꾸면 된다(코드 수정 불필요). 기본값은 항상 잠김(false) — 설정 누락 시에도 안전.

무료라서 이 락과 무관한 것: arXiv/Semantic Scholar 크롤링, PDF 블록 추출, 그림·표·참고문헌
추출, 리더(원문 보기), SQLite 캐시에 이미 저장된 번역 재열람.
"""

from __future__ import annotations

import os


class PaidApiLocked(RuntimeError):
    """유료 API 호출이 하드락으로 차단됨."""


def offline_mode() -> bool:
    """완전 로컬 모드 — 외부 통신을 일절 하지 않는다.

    사내 인트라넷처럼 구글 로그인·스토리지가 하드웨어적으로 차단된 환경용.
    켜면 번역·그림분석·AI요약·크레딧 경로가 모두 비활성화되고, 로컬 기능만 남는다
    (PDF 추출·로컬 검색·E-book 리더·그림/표/참고문헌 — 전부 네트워크 불필요).
    """
    return os.getenv("OFFLINE_MODE", "false").strip().lower() == "true"


# ── 화면에서 끄고 켜는 스위치 (2026-07-28 호야 지시) ─────────────────
# .env 를 열지 않고도 상단 배지를 눌러 즉시 잠글 수 있어야 한다.
# 값은 DB(app_state)에 남고, 서버가 뜰 때 main.py 가 여기로 다시 주입한다.
# ⚠️ 이 변수는 **프로세스 안에서만** 산다. 나중에 켜지는 경로가 생기지 않도록
#    설정하는 곳은 오직 사용자의 명시적 토글 + 시작 시 복원 두 군데뿐이다.
_OVERRIDE: bool | None = None


def set_paid_override(value: bool | None) -> None:
    """None = .env 값을 그대로 따름 / True·False = 화면 스위치가 이김."""
    global _OVERRIDE
    _OVERRIDE = value


def paid_override() -> bool | None:
    return _OVERRIDE


def paid_apis_enabled() -> bool:
    # 오프라인 모드면 유료 API는 무조건 잠긴다(외부 호출 자체를 안 함).
    if offline_mode():
        return False
    if _OVERRIDE is not None:
        return _OVERRIDE
    # 기본값 false — .env에 없으면 잠긴 것으로 본다(fail-safe).
    return os.getenv("PAID_APIS_ENABLED", "false").strip().lower() == "true"


LOCK_MESSAGE = (
    "🔒 유료 API가 잠겨 있습니다. "
    "화면 좌측 상단의 [유료 API] 배지를 눌러 켤 수 있습니다(.env PAID_APIS_ENABLED=true 도 가능). "
    "무료 기능(논문 수집·추출·그림/표/참고문헌·원문 리더·기존 번역 열람)은 그대로 동작합니다."
)

OFFLINE_MESSAGE = (
    "📴 완전 로컬 모드입니다 (OFFLINE_MODE=true) — 외부 통신을 하지 않습니다. "
    "논문 검색·E-book 리더·그림/표/참고문헌은 그대로 쓸 수 있고, "
    "AI 번역·그림분석·AI 요약은 비활성화됩니다."
)


def block_message() -> str:
    """지금 왜 막혔는지 상황에 맞는 안내."""
    return OFFLINE_MESSAGE if offline_mode() else LOCK_MESSAGE


def require_paid_apis(what: str) -> None:
    """돈 나가는 호출 직전에 부른다. 잠겨 있으면 예외."""
    if not paid_apis_enabled():
        raise PaidApiLocked(f"{what} 차단됨 — {LOCK_MESSAGE}")


NO_KEY_MESSAGE = (
    "사용할 API 키가 없습니다. 우측 상단 [사용자]에서 본인 Gemini API 키를 등록하고 "
    "이름을 클릭해 활성화하세요. (발급: https://aistudio.google.com/apikey) "
    "유료 기능은 각자 자기 키로 과금됩니다."
)


def usable_api_key(conn) -> str | None:
    """실행 전 자격증명 확인. 없으면 None → 호출부가 안내를 돌려준다.

    우선순위: 활성 사용자가 고른 자격증명(무료키/유료키/크레딧) → .env 폴백.
    무료 대안이 없으므로(배포 시 각자 자기 키), 키 없이 시작하면 백그라운드에서 조용히
    실패한다 → 시작 전에 여기서 거른다.
    """
    import os

    if conn is not None:
        try:
            import users

            # ⚠️ active_credential(고른 칸 하나)이 아니라 **credential_chain(폴백 포함)** 을 본다.
            # 실측 버그: 기본 옵션이 크레딧인데 크레딧 칸이 비어 있으면, API 키가 멀쩡히
            # 등록돼 있어도 "키 없음"으로 판단해 번역·그림분석이 차단됐다
            # (= 크레딧을 못 쓰는 사내망 구성에서 항상 발생).
            for cred in users.credential_chain(conn):
                if cred["kind"] == "credit":
                    if cred["project"]:
                        return "credit"
                    continue  # 프로젝트 ID가 없으면 다음 후보로
                if cred["key"]:
                    return cred["key"]
        except Exception:
            pass

    if os.getenv("TRANSLATE_CHANNEL", "aistudio").strip().lower() == "vertex":
        return "vertex"  # .env 로 vertex 고정 — gcloud 인증 사용, 별도 키 불요
    return os.getenv("GEMINI_API_KEY") or None
