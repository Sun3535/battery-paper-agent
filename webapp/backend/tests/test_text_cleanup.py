"""PDF 글자 깨짐 정리 — 리더 본문에 □ 가 섞여 나오던 문제.

원인은 폰트가 아니라 **매핑 없는 코드포인트**다(LaTeX 심볼 폰트에 ToUnicode CMap 부재).
브라우저는 어떤 폰트로도 못 그리므로 추출 단계에서 거르는 것만이 해법이다.
"""

import extract
import store


# ── 렌더 불가능한 글리프 제거 ────────────────────────────────────
def test_removes_private_use_area():
    """PUA(U+E000~) = 폰트 내부 코드. 어떤 폰트에도 없어 tofu(□)가 된다"""
    assert extract.sanitize_text("impedance  model") == "impedance model"


def test_removes_replacement_and_unassigned():
    assert extract.sanitize_text("forms: �") == "forms:"
    assert extract.sanitize_text("D2h ͸ group") == "D2h group"  # U+0378 = 미할당


def test_removes_control_chars_but_keeps_newline():
    assert extract.sanitize_text("a\x00b\x07c") == "abc"
    assert extract.sanitize_text("line1\nline2") == "line1\nline2"


def test_keeps_real_science_symbols():
    """진짜 유니코드 기호는 살아야 한다 — 이걸 지우면 논문이 망가진다"""
    for s in ["μ", "α", "Å", "≈", "±", "→", "°C", "Li⁺", "∫", "℃"]:
        assert extract.sanitize_text(f"value {s} here") == f"value {s} here"


def test_expands_ligatures():
    """PDF의 ﬁ/ﬂ 합자는 검색이 안 걸린다 — 풀어서 넣는다"""
    assert extract.sanitize_text("efﬁciency and ﬂow") == "efficiency and flow"


def test_collapses_runs_of_spaces():
    assert extract.sanitize_text("a    b") == "a b"


def test_empty_input():
    assert extract.sanitize_text("") == ""
    assert extract.sanitize_text("   ") == ""


# ── 수식 잔해 판정 ───────────────────────────────────────────────
def test_matrix_row_is_debris():
    """실측 사고 화면: 행렬이 텍스트로 흘러나온 조각"""
    assert extract.is_math_debris("a 0 0 0 b 0 0 0 c") is True
    assert extract.is_math_debris("0 d 0 e 0 0 0 0 0") is True
    assert extract.is_math_debris(",") is True
    assert extract.is_math_debris("") is True


def test_real_sentence_is_not_debris():
    assert (
        extract.is_math_debris(
            "irreducible representations of point group D2h have the following forms:"
        )
        is False
    )


def test_headings_and_captions_survive():
    """짧아도 진짜 텍스트는 남아야 한다 — 여기서 잘못 걸리면 논문이 사라진다"""
    for t in ["1. INTRODUCTION", "II. MODEL", "Figure 2", "Abstract", "Keywords: PEM fuel cell"]:
        assert extract.is_math_debris(t) is False, t


def test_long_numeric_table_row_survives():
    """단어가 없어도 길면 표 데이터일 수 있으니 남긴다"""
    long_row = "0.12 3.45 6.78 9.01 2.34 5.67 8.90 1.23 4.56 7.89 0.12 3.45 6.78 9.01"
    assert len(long_row) >= extract.DEBRIS_MAX_LEN
    assert extract.is_math_debris(long_row) is False


# ── 저장된 블록 일괄 정화 ────────────────────────────────────────
def _seed(conn, rows):
    conn.execute(
        "INSERT INTO documents (doc_id,title,filename,pdf_path,source,status,created_at)"
        " VALUES ('D','t','f.pdf','x.pdf','upload','ready','t')"
    )
    for order, kind, text in rows:
        conn.execute(
            "INSERT INTO blocks (doc_id,block_order,kind,page,bbox,text_en)"
            " VALUES ('D',?,?,1,'[]',?)",
            (order, kind, text),
        )


def test_clean_stored_blocks_fixes_and_removes(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "c.db")
    with store.connect() as conn:
        _seed(
            conn,
            [
                (1, "text", "Sodium ion battery  cathode design"),  # 정화 대상
                (2, "text", "a 0 0 0 b 0 0 0 c"),  # 삭제 대상
                (3, "text", "This paragraph is perfectly fine and stays."),  # 그대로
            ],
        )
        conn.execute(
            "INSERT INTO translations (doc_id,block_order,text_ko,model,created_at)"
            " VALUES ('D',2,'가 0 0 0','m','t')"
        )
        stats = extract.clean_stored_blocks(conn)

        assert stats["fixed"] == 1
        assert stats["removed"] == 1
        left = {r["block_order"]: r["text_en"] for r in conn.execute("SELECT * FROM blocks")}
        assert left[1] == "Sodium ion battery cathode design"
        assert 2 not in left
        assert left[3] == "This paragraph is perfectly fine and stays."
        # 잔해의 번역도 함께 사라져야 한다 (남으면 화면에 그대로 뜬다)
        assert conn.execute("SELECT COUNT(*) c FROM translations").fetchone()["c"] == 0


def test_clean_keeps_block_order_stable(tmp_path, monkeypatch):
    """번역 캐시가 block_order 로 묶여 있다 — 번호를 다시 매기면 이미 낸 돈이 어긋난다"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "c2.db")
    with store.connect() as conn:
        _seed(
            conn,
            [
                (1, "text", "First real paragraph of the paper body."),
                (2, "text", ","),
                (5, "text", "Fifth real paragraph of the paper body."),
            ],
        )
        conn.execute(
            "INSERT INTO translations (doc_id,block_order,text_ko,model,created_at)"
            " VALUES ('D',5,'다섯번째 문단','m','t')"
        )
        extract.clean_stored_blocks(conn)

        orders = [r["block_order"] for r in conn.execute("SELECT block_order FROM blocks")]
        assert orders == [1, 5]
        row = conn.execute("SELECT text_ko FROM translations WHERE block_order=5").fetchone()
        assert row["text_ko"] == "다섯번째 문단"


def test_caption_blocks_are_not_deleted(tmp_path, monkeypatch):
    """그림/표 블록의 캡션은 짧아도 지우면 안 된다 (그림 설명이 통째로 날아간다)"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "c3.db")
    with store.connect() as conn:
        _seed(conn, [(1, "image", "Fig. 3")])
        extract.clean_stored_blocks(conn)
        assert conn.execute("SELECT COUNT(*) c FROM blocks").fetchone()["c"] == 1
