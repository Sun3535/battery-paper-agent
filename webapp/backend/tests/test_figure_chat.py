"""그림 질문 인식 + 분석 주입 + 유료 유도 안내 — 경우의 수 단위검증.

실 API 호출 없음(전부 로컬 판정/DB). 유료 경로는 건드리지 않는다.
"""

import sqlite3

import pytest

import figure_analysis as fa


# ══════════════════════════════════════════════════════════════════
# 1) 그림 질문 판별 — 오탐/미탐 양쪽 검증
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "q",
    [
        # 한국어 — 직접 지칭
        "이 그림 설명해줘",
        "그래프에서 최대값은?",
        "도표 해석해줘",
        "표 1의 파라미터는?",
        # 한국어 — 그래프 구성요소
        "x축이 뭘 나타내?",
        "가로축 단위는?",
        "축 라벨이 뭐야?",
        "XRD 피크가 어디로 이동해?",
        "곡선 기울기는?",
        "임피던스 반원 직경이 얼마야?",
        "스펙트럼 변화는?",
        "SEM 이미지에서 뭐가 보여?",
        # 영어
        "What does Figure 3 show?",
        "Explain Fig. 2",
        "Nyquist plot 변화는?",
        "What is the peak position?",
        "Describe the schematic",
        "y-axis range?",
        "Table 2 values?",
        "TEM micrograph 분석",
    ],
)
def test_detects_figure_questions(q):
    assert fa.is_figure_question(q), f"미탐: {q}"


@pytest.mark.parametrize(
    "q",
    [
        # ⚠️ 오탐 방지 — 그림과 무관하지만 부분 문자열이 겹치는 것들
        "압축 응력이 어떻게 변해?",  # '축' 포함
        "구축된 모델의 가정은?",  # '축'
        "축전지 수명은?",  # '축'
        "표면 반응 메커니즘은?",  # '표'
        "이 논문의 표현이 모호해",  # '표'
        "발표된 연도가 언제야?",  # '표'
        # 일반 질문
        "이 논문의 핵심 결론은?",
        "저자가 누구야?",
        "coulombic efficiency를 높이는 방법은?",
        "어떤 손실을 무시했어?",
    ],
)
def test_no_false_positive(q):
    assert not fa.is_figure_question(q), f"오탐: {q}"


# ══════════════════════════════════════════════════════════════════
# 2) 유료 유도 안내 (upsell) — 4가지 경우의 수
# ══════════════════════════════════════════════════════════════════
@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    c.row_factory = sqlite3.Row
    fa.ensure_table(c)
    yield c
    c.close()


def _add_analysis(c, doc_id="d1", order=1):
    c.execute(
        "INSERT INTO figure_analyses (doc_id, block_order, analysis_ko, model, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (doc_id, order, "임피던스 반원이 320에서 120 mOhm cm2로 감소한다", "m", "now"),
    )


def test_upsell_case_A_figure_q_no_analysis_at_all(conn):
    """A: 그림 질문 + 분석 전무 → '실행하면 답할 수 있다' 안내"""
    note = fa.upsell_note(conn, "그래프에서 임피던스 변화는?", used_analyses=0)
    assert "실행" in note and "₩" in note


def test_upsell_case_B_figure_q_analysis_exists_but_unmatched(conn):
    """B: 그림 질문 + 분석은 있으나 이 질문엔 안 걸림 → 다른 안내"""
    _add_analysis(conn)
    note = fa.upsell_note(conn, "그래프에서 임피던스 변화는?", used_analyses=0)
    assert "맞는 그림 분석이 아직 없습니다" in note


def test_upsell_case_C_figure_q_with_matched_analysis(conn):
    """C: 그림 질문 + 관련 분석 회수됨 → 안내 없음(이미 답할 수 있음)"""
    _add_analysis(conn)
    assert fa.upsell_note(conn, "그래프 변화는?", used_analyses=2) == ""


def test_upsell_case_D_non_figure_question(conn):
    """D: 그림 질문이 아니면 → 안내 없음 (분석 유무 무관)"""
    assert fa.upsell_note(conn, "저자가 누구야?", used_analyses=0) == ""
    _add_analysis(conn)
    assert fa.upsell_note(conn, "저자가 누구야?", used_analyses=0) == ""


# ══════════════════════════════════════════════════════════════════
# 3) 프롬프트 주입 블록 — 비용에 직결되므로 크기·내용 검증
# ══════════════════════════════════════════════════════════════════
def test_figure_block_empty_when_no_analysis():
    """회수 0건이면 빈 문자열 → 주입 입력토큰 0 (비용 0)"""
    assert fa.build_figure_block([]) == ""


def test_figure_block_contains_analysis_and_source():
    blk = fa.build_figure_block(
        [{"analysis": "임피던스가 320에서 120으로 감소", "title": "paper_A", "page": 3}]
    )
    assert "320에서 120" in blk
    assert "paper_A" in blk and "p3" in blk
    assert "PDF 텍스트에는 없는" in blk  # 챗봇에게 왜 이걸 봐야 하는지 명시


def test_figure_block_truncates_long_analysis():
    """비용 상한 — 분석문이 길어도 400자에서 잘린다"""
    blk = fa.build_figure_block([{"analysis": "가" * 2000, "title": "t", "page": 1}])
    assert len(blk) < 700


def test_relevant_analyses_empty_on_short_query(conn):
    """3글자 미만 토큰뿐이면 회수 안 함(FTS trigram 한계) → 비용 0"""
    assert fa.relevant_analyses(conn, "a b") == []


# ══════════════════════════════════════════════════════════════════
# 4) 매칭 강도 — 비용 최적화 검증 (그림질문=OR넉넉 / 일반질문=AND엄격)
# ══════════════════════════════════════════════════════════════════
def _seed_fts(c):
    """blocks_fts + 부속 테이블을 최소 구성으로 만든다."""
    c.executescript(
        "CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5("
        " doc_id UNINDEXED, block_order UNINDEXED, page UNINDEXED, body, tokenize='trigram');"
        "CREATE TABLE IF NOT EXISTS documents (doc_id TEXT PRIMARY KEY, title TEXT);"
        "CREATE TABLE IF NOT EXISTS blocks (doc_id TEXT, block_order INTEGER, page INTEGER);"
    )
    c.execute("INSERT INTO documents VALUES ('d1','paper_A')")
    c.execute("INSERT INTO blocks VALUES ('d1',1,3)")
    c.execute(
        "INSERT INTO blocks_fts (doc_id, block_order, page, body) VALUES ('d1',1,3,?)",
        ("Nyquist plot 임피던스 반원이 320에서 120 mOhm cm2로 감소한다 impedance",),
    )
    _add_analysis(c)


def test_figure_question_uses_loose_or_match(conn):
    """그림 질문 → OR 매칭이라 일부 단어만 맞아도 회수된다"""
    _seed_fts(conn)
    got = fa.relevant_analyses(conn, "Nyquist 그래프에서 완전히무관한단어 변화는?")
    assert len(got) >= 1


def test_plain_question_uses_strict_and_match(conn):
    """일반 질문 → AND 매칭. 한 단어라도 없으면 회수 0 = 주입 토큰 0"""
    _seed_fts(conn)
    got = fa.relevant_analyses(conn, "impedance 모델에서 완전히무관한단어 무시한 손실은?")
    assert got == [], "일반 질문에 무관한 그림분석이 딸려오면 토큰 낭비"


def test_plain_question_still_gets_strongly_related_analysis(conn):
    """단, 일반 질문이라도 강하게 관련되면 회수한다(암묵 전달 유지)"""
    _seed_fts(conn)
    got = fa.relevant_analyses(conn, "임피던스 반원 감소")
    assert len(got) >= 1


# ══════════════════════════════════════════════════════════════════
# 5) 무료 대안 제거 — 키 없으면 실행 전에 안내 (배포 전제)
# ══════════════════════════════════════════════════════════════════
def test_no_key_message_guides_to_registration():
    import guard

    assert "[사용자]" in guard.NO_KEY_MESSAGE
    assert "aistudio.google.com/apikey" in guard.NO_KEY_MESSAGE
    assert "자기 키로 과금" in guard.NO_KEY_MESSAGE


def test_vertex_channel_needs_no_user_key(monkeypatch):
    """vertex 채널은 gcloud 인증을 쓰므로 사용자 키 없이도 실행 가능"""
    import guard

    monkeypatch.setenv("TRANSLATE_CHANNEL", "vertex")
    assert guard.usable_api_key(None) == "vertex"


def test_aistudio_without_any_key_returns_none(monkeypatch, tmp_path):
    """aistudio 채널 + 등록 키 없음 + .env 폴백 없음 → None (실행 차단 신호)"""
    import guard
    import store
    import users

    monkeypatch.setenv("TRANSLATE_CHANNEL", "aistudio")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "k.db")
    with store.connect() as c:
        users.set_active(c, None)
        assert guard.usable_api_key(c) is None
