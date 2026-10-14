"""자격증명 3종(무료키·유료키·크레딧) — 저장/수정/삭제·마스킹·채널 라우팅 검증.

실 API 호출 없음. 저장 위치는 로컬 SQLite(코드 옆)이며 외부 전송이 없음을 전제로 한다.
"""

from pathlib import Path
import pytest

import guard
import store
import users


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "cred.db")
    with store.connect() as conn:
        users.create(conn, "u1", "pw")
        yield conn


# ── 마스킹 ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expect_visible",
    [
        ("AIzaSyABCDEFGHIJKLMNOPqrst", ("AIzaSy", "qrst")),
        ("short", ()),  # 12자 이하는 전부 가림
    ],
)
def test_mask_hides_middle(raw, expect_visible):
    m = users.mask(raw)
    assert raw not in m, "원문이 그대로 노출되면 안 됨"
    assert "•" in m
    for frag in expect_visible:
        assert frag in m


def test_mask_empty():
    assert users.mask("") == ""


# ── 저장 / 수정 / 삭제 ────────────────────────────────────────────
def test_save_read_update_delete_each_kind(db):
    for kind, val in (("free", "AIzaFREE1234567890abcd"), ("paid", "AIzaPAID0987654321wxyz"), ("credit", "proj-123")):
        users.set_credential(db, "u1", kind, val)
        assert users.get_credential_raw(db, "u1", kind) == val
        assert users.get_credentials(db, "u1")[kind]["set"] is True

        users.set_credential(db, "u1", kind, val + "X")  # 수정
        assert users.get_credential_raw(db, "u1", kind).endswith("X")

        users.set_credential(db, "u1", kind, "")  # 빈 값 = 삭제
        assert users.get_credentials(db, "u1")[kind]["set"] is False


def test_get_credentials_never_returns_raw(db):
    users.set_credential(db, "u1", "paid", "AIzaSECRETVALUE1234567")
    blob = str(users.get_credentials(db, "u1"))
    assert "SECRETVALUE" not in blob, "목록 조회에 원문이 섞이면 안 됨"


def test_unknown_kind_rejected(db):
    with pytest.raises(ValueError):
        users.set_credential(db, "u1", "hacker", "x")
    with pytest.raises(ValueError):
        users.get_credential_raw(db, "u1", "hacker")


# ── 선택(preferred)에 따른 라우팅 ─────────────────────────────────
def test_preferred_routes_to_correct_credential(db):
    users.set_credential(db, "u1", "free", "AIzaFREEkey00000000000")
    users.set_credential(db, "u1", "paid", "AIzaPAIDkey11111111111")
    users.set_credential(db, "u1", "credit", "my-gcp-project")
    users.set_active(db, "u1")

    users.set_preferred(db, "u1", "free")
    c = users.active_credential(db)
    assert c["kind"] == "free" and c["key"].startswith("AIzaFREE")

    users.set_preferred(db, "u1", "paid")
    c = users.active_credential(db)
    assert c["kind"] == "paid" and c["key"].startswith("AIzaPAID")

    users.set_preferred(db, "u1", "credit")
    c = users.active_credential(db)
    assert c["kind"] == "credit"
    assert c["key"] == "", "크레딧 경로는 API 키를 쓰지 않는다(gcloud 인증)"
    assert c["project"] == "my-gcp-project"


def test_credit_without_project_is_not_usable(db, monkeypatch):
    """크레딧을 골랐는데 프로젝트 ID가 없으면 실행 불가로 판정돼야 한다."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("TRANSLATE_CHANNEL", "aistudio")
    users.set_active(db, "u1")
    users.set_preferred(db, "u1", "credit")
    assert guard.usable_api_key(db) is None

    users.set_credential(db, "u1", "credit", "proj-ok")
    assert guard.usable_api_key(db) == "credit"


def test_usable_key_follows_user_choice(db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    users.set_credential(db, "u1", "free", "AIzaFREEkey00000000000")
    users.set_credential(db, "u1", "paid", "AIzaPAIDkey11111111111")
    users.set_active(db, "u1")

    users.set_preferred(db, "u1", "free")
    assert guard.usable_api_key(db).startswith("AIzaFREE")
    users.set_preferred(db, "u1", "paid")
    assert guard.usable_api_key(db).startswith("AIzaPAID")


def test_no_active_user_means_no_key(db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("TRANSLATE_CHANNEL", "aistudio")
    users.set_active(db, None)
    assert guard.usable_api_key(db) is None


# ── 저장 위치 (로컬, 코드 옆) ─────────────────────────────────────
def test_storage_is_local_file_next_to_code():
    """DB는 이 PC의 앱 폴더 안에 있어야 한다(외부 전송 없음).
    폴더 이름은 PC마다 다르므로(ZIP으로 받으면 battery-paper-agent-main) 이름 대신 위치를 본다."""
    p = store.DB_PATH.resolve()
    앱폴더 = Path(store.__file__).resolve().parents[2]
    assert p.suffix == ".db"
    assert 앱폴더 in p.parents


# ── 마이그레이션 1회성 (실측 버그 회귀 방지) ──────────────────────
# ⚠️ 이 두 테스트는 **연결을 순차적으로** 열고 닫아야 한다(중첩 금지).
#    db fixture 는 연결을 열어둔 채라 그 안에서 또 열면 SQLite 락 대기에 걸린다.
@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "mig.db")
    with store.connect() as conn:
        users.create(conn, "u1", "pw")
    yield  # 연결을 열어두지 않는다


def test_migration_runs_only_once(fresh_db):
    """②칸에 저장한 키가 ①칸으로 새어 들어가면 안 된다.

    실측 버그: 일회성이어야 할 api_key→key_free 이관이 매 connect()마다 돌아
    ②칸 저장 시 ①칸이 자동으로 채워지고, ①칸을 지워도 되살아났다.
    """
    with store.connect() as c:
        users.set_credential(c, "u1", "paid", "AIzaPAIDonly1234567890")
        assert users.get_credentials(c, "u1")["free"]["set"] is False

    with store.connect() as c:  # 새 연결 = 마이그레이션 재실행 기회
        assert users.get_credentials(c, "u1")["free"]["set"] is False, "①칸이 오염됨"


def test_deleted_slot_stays_deleted(fresh_db):
    """①칸을 지운 뒤 재연결해도 되살아나면 안 된다."""
    with store.connect() as c:
        users.set_credential(c, "u1", "free", "AIzaFREE1234567890abc")
        users.set_credential(c, "u1", "paid", "AIzaPAID1234567890xyz")
        users.set_credential(c, "u1", "free", "")  # ①칸 삭제

    with store.connect() as c:
        assert users.get_credentials(c, "u1")["free"]["set"] is False


# ── 기본 옵션 = 크레딧 (호야 지시 2026-07-16) ─────────────────────
def test_default_preferred_is_credit(fresh_db):
    """새 사용자의 기본 옵션은 크레딧이어야 한다"""
    with store.connect() as c:
        assert users.get_credentials(c, "u1")["preferred"] == "credit"


def test_credit_default_falls_back_to_api_key_when_no_project(fresh_db):
    """크레딧이 기본이어도 GCP 프로젝트가 없으면 API 키로 안전하게 넘어간다.

    (배포 사용자 다수가 Vertex/GCP가 없으므로 이 폴백이 없으면 앱이 멈춘다)
    """
    with store.connect() as c:
        users.set_active(c, "u1")
        users.set_credential(c, "u1", "free", "AIzaOnlyKey_123456789")
    with store.connect() as c:
        assert [x["kind"] for x in users.credential_chain(c)] == ["free"]
        assert users.active_api_key(c).startswith("AIzaOnlyKey")


def test_credit_first_once_project_is_set(fresh_db):
    with store.connect() as c:
        users.set_active(c, "u1")
        users.set_credential(c, "u1", "free", "AIzaKey_1234567890ab")
        users.set_credential(c, "u1", "credit", "my-proj")
    with store.connect() as c:
        assert [x["kind"] for x in users.credential_chain(c)][0] == "credit"


def test_user_can_switch_default_to_api(fresh_db):
    with store.connect() as c:
        users.set_active(c, "u1")
        users.set_credential(c, "u1", "free", "AIzaKey_1234567890ab")
        users.set_credential(c, "u1", "credit", "my-proj")
        users.set_preferred(c, "u1", "free")
    with store.connect() as c:
        assert [x["kind"] for x in users.credential_chain(c)] == ["free", "credit"]


# ── 완전 로컬 모드 (사내망 배포) ──────────────────────────────────
def test_offline_mode_blocks_all_paid_paths(monkeypatch):
    """OFFLINE_MODE=true 면 하드락 설정과 무관하게 외부 호출이 전부 막힌다"""
    monkeypatch.setenv("OFFLINE_MODE", "true")
    monkeypatch.setenv("PAID_APIS_ENABLED", "true")  # 켜져 있어도
    assert guard.offline_mode() is True
    assert guard.paid_apis_enabled() is False, "오프라인이면 유료 경로는 무조건 차단"


def test_offline_message_explains_local_only(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "true")
    msg = guard.block_message()
    assert "로컬" in msg and "외부 통신" in msg
    assert "리더" in msg, "쓸 수 있는 기능을 안내해야 함"


def test_online_lock_message_differs_from_offline(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "false")
    monkeypatch.setenv("PAID_APIS_ENABLED", "false")
    assert guard.block_message() == guard.LOCK_MESSAGE


def test_translate_refuses_in_offline_mode(monkeypatch):
    """오프라인에서 번역을 호출하면 예외로 막혀야 한다(네트워크 시도 자체를 안 함)"""
    import translate

    monkeypatch.setenv("OFFLINE_MODE", "true")
    with pytest.raises(guard.PaidApiLocked):
        translate._get_client_and_model("AIzaSomeKey")


def test_usable_key_found_when_credit_default_but_empty(fresh_db, monkeypatch):
    """회사 구성 회귀 테스트: 기본=크레딧 + 크레딧 칸 비움 + API 키만 등록.

    실측 버그: usable_api_key 가 credential_chain(폴백 포함)이 아니라 active_credential
    (고른 칸 하나)만 봐서, API 키가 멀쩡한데도 "키 없음"으로 번역·그림분석을 차단했다.
    크레딧을 못 쓰는 사내망 배포에서 항상 터지는 문제라 반드시 고정한다.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("TRANSLATE_CHANNEL", "aistudio")
    with store.connect() as c:
        users.set_active(c, "u1")
        users.set_credential(c, "u1", "free", "AIzaCompanyKey_123456")
        # 크레딧 칸은 비운 채로 두고, 기본 옵션은 credit(기본값)
        assert users.get_credentials(c, "u1")["preferred"] == "credit"
    with store.connect() as c:
        got = guard.usable_api_key(c)
    assert got is not None, "API 키가 있는데 차단되면 안 됨"
    assert got.startswith("AIzaCompanyKey")


# ── 크레딧 옵션 비활성화 (사내망 = API 키 전용) ───────────────────
def test_credit_disabled_removes_from_chain(fresh_db, monkeypatch):
    monkeypatch.setenv("ENABLE_CREDIT", "false")
    with store.connect() as c:
        users.set_active(c, "u1")
        users.set_credential(c, "u1", "free", "AIzaKey_1234567890ab")
        users.set_credential(c, "u1", "credit", "my-proj")  # 값이 있어도
    with store.connect() as c:
        kinds = [x["kind"] for x in users.credential_chain(c)]
    assert "credit" not in kinds, "비활성 시 크레딧은 시도조차 하면 안 됨"
    assert kinds == ["free"]


def test_credit_disabled_shows_api_key_as_default(fresh_db, monkeypatch):
    """기본값이 credit 이어도, 꺼진 환경에선 API 키를 기본으로 보여준다"""
    monkeypatch.setenv("ENABLE_CREDIT", "false")
    with store.connect() as c:
        cr = users.get_credentials(c, "u1")
    assert cr["credit_enabled"] is False
    assert cr["preferred"] == "free"


def test_credit_disabled_rejects_selecting_credit(fresh_db, monkeypatch):
    monkeypatch.setenv("ENABLE_CREDIT", "false")
    with store.connect() as c:
        with pytest.raises(ValueError):
            users.set_preferred(c, "u1", "credit")


def test_credit_enabled_by_default(fresh_db, monkeypatch):
    monkeypatch.delenv("ENABLE_CREDIT", raising=False)
    assert users.credit_enabled() is True
    assert "credit" in users.usable_kinds()
