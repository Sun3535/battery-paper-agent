"""소스 파서 단위 테스트 — 실 API 호출 없음, 고정 픽스처로 파싱 로직만 검증.

'유료 API 호출 전 단위 검증 의무' 원칙과 같은 정신: 무료 API라도 실행 전에
파서가 응답 구조를 제대로 읽는지 먼저 확인한다.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from crawler.sources.arxiv_source import ArxivSource
from crawler.sources.semantic_scholar_source import SemanticScholarSource

FIXTURES = Path(__file__).parent / "fixtures"


def test_arxiv_parse():
    xml_text = (FIXTURES / "arxiv_sample_response.xml").read_text(encoding="utf-8")
    papers = ArxivSource()._parse(xml_text, keyword_label="고체전해질")
    assert len(papers) == 1
    p = papers[0]
    assert p.paper_id == "arxiv:2401.01234"
    assert p.source == "arxiv"
    assert p.title == "Solid Electrolyte Ionic Conductivity Study"
    assert p.authors == ["Jane Doe", "John Smith"]
    assert p.published_date == "2024-01-15"
    assert p.pdf_url == "http://arxiv.org/pdf/2401.01234v2"
    assert p.keyword_matched == "고체전해질"


@patch("crawler.sources.arxiv_source.requests.get")
def test_arxiv_search_calls_api_and_parses(mock_get):
    xml_text = (FIXTURES / "arxiv_sample_response.xml").read_text(encoding="utf-8")
    mock_resp = Mock(status_code=200, text=xml_text)
    mock_resp.raise_for_status = Mock()
    mock_get.return_value = mock_resp

    papers = ArxivSource().search("solid electrolyte", max_results=5, keyword_label="고체전해질")
    assert len(papers) == 1
    assert mock_get.call_count == 1


@patch("crawler.sources.semantic_scholar_source.requests.get")
def test_semantic_scholar_parse(mock_get):
    data = json.loads((FIXTURES / "semantic_scholar_sample_response.json").read_text(encoding="utf-8"))
    mock_resp = Mock(status_code=200)
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = data
    mock_get.return_value = mock_resp

    papers = SemanticScholarSource().search("silicon anode", max_results=5, keyword_label="실리콘음극재")
    assert len(papers) == 1
    p = papers[0]
    assert p.paper_id == "s2:abc123def456"
    assert p.source == "semantic_scholar"
    assert p.pdf_url == "https://example.com/paper.pdf"
    assert p.doi == "10.1000/example2.doi"


@patch("crawler.sources.semantic_scholar_source.requests.get")
def test_semantic_scholar_rate_limit_returns_empty_not_raise(mock_get):
    mock_get.return_value = Mock(status_code=429)
    papers = SemanticScholarSource().search("silicon anode", max_results=5)
    assert papers == []


def test_arxiv_parse_skips_entry_without_id():
    xml_text = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>No id entry</title></entry>
    </feed>"""
    papers = ArxivSource()._parse(xml_text, keyword_label="테스트")
    assert papers == []
