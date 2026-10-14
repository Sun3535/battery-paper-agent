"""관련성 필터 단위 테스트 — 실제 크롤에서 나온 오탐 사례 기반."""

from crawler.relevance import is_relevant, matched_terms


def test_relevant_battery_paper():
    assert is_relevant(
        "Silicon Anode Volume Expansion in Lithium-ion Batteries",
        "We study coulombic efficiency and cycle life of silicon anodes.",
    )


def test_relevant_by_abstract_only():
    assert is_relevant(
        "A study of interphase chemistry",
        "The solid electrolyte interphase (SEI) governs dendrite formation in lithium metal cells.",
    )


def test_rejects_off_topic_fuel_cell():
    # 실제 오탐 사례: solid oxide fuel cell — 배터리 아님
    assert not is_relevant(
        "Toward in-situ X-ray absorption spectroscopy of solid oxide fuel cells",
        "We characterize solid oxide fuel cells using operando spectroscopy.",
    )


def test_rejects_off_topic_force_field():
    assert not is_relevant(
        "Differentiable OPLS Force Field Parameterization for Ionic Systems",
        "We parameterize force fields for molecular dynamics simulations of ionic liquids.",
    )


def test_rejects_generic_lithium_optics():
    # lithium 단독은 통과시키지 않음 (lithium niobate 광학 논문 등 오탐 방지)
    assert not is_relevant(
        "Nonlinear optics in lithium niobate waveguides",
        "We demonstrate second-harmonic generation in lithium niobate.",
    )


def test_matched_terms_reports():
    terms = matched_terms("Cathode degradation", "NMC cathode and electrolyte study")
    assert "cathode" in terms
    assert "electrolyte" in terms
