"""OpenAlex 소스 단위 테스트 — 실 API 호출 없음(모킹)."""

from unittest.mock import Mock, patch

from crawler.sources.openalex_source import OpenAlexSource, _reconstruct_abstract

SAMPLE = {
    "meta": {"count": 1},
    "results": [
        {
            "id": "https://openalex.org/W4281234567",
            "title": "Interface Engineering in All-Solid-State Battery Cathodes",
            "publication_date": "2026-05-01",
            "doi": "https://doi.org/10.1000/oa.doi",
            "open_access": {"is_oa": True, "oa_status": "gold"},
            "best_oa_location": {"pdf_url": "https://example.com/oa.pdf"},
            "authorships": [{"author": {"display_name": "Lee Min"}}],
            "abstract_inverted_index": {"Solid": [0], "cathode": [1], "works": [2]},
        }
    ],
}


def test_reconstruct_abstract():
    assert _reconstruct_abstract({"b": [1], "a": [0], "c": [2]}) == "a b c"
    assert _reconstruct_abstract(None) == ""


@patch("crawler.sources.openalex_source.requests.get")
def test_openalex_parse(mock_get):
    mock_resp = Mock(status_code=200)
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = SAMPLE
    mock_get.return_value = mock_resp

    papers = OpenAlexSource().search("all-solid-state", max_results=5, keyword_label="전고체양극재")
    assert len(papers) == 1
    p = papers[0]
    assert p.paper_id == "oa:W4281234567"
    assert p.pdf_url == "https://example.com/oa.pdf"
    assert p.doi == "10.1000/oa.doi"
    assert p.abstract == "Solid cathode works"
    assert p.keyword_matched == "전고체양극재"


@patch("crawler.sources.openalex_source.requests.get")
def test_openalex_rate_limit_returns_empty(mock_get):
    mock_get.return_value = Mock(status_code=429)
    assert OpenAlexSource().search("x", max_results=5) == []
