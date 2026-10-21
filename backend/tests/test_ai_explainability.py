"""Unit tests for the local-AI explainability helpers (no database, graph or model needed)."""
from app.llm import grounding
from app.llm.glossary import explain_terms
from app.llm.retrieval import _terms

SOURCES = [
    {"id": "S1", "text": "Pembrolizumab 200 mg is given intravenously on Day 1 of each 21-day cycle.", "filename": "67. KEYNOTE-355.pdf", "title": "", "nct_id": "NCT02819518"},
    {"id": "S2", "text": "Participants must be at least 18 years of age on the day of signing informed consent.", "filename": "67. KEYNOTE-355.pdf", "title": "", "nct_id": ""},
]


def test_cited_answer_is_well_grounded():
    ans = "- Pembrolizumab 200 mg is given on Day 1 of each 21-day cycle [S1].\n- Participants must be at least 18 years old [S2]."
    g = grounding.check(ans, SOURCES)
    assert g["cited_sources"] == ["S1", "S2"]
    assert g["statements_cited"] == 2 and g["invalid_citations"] == []
    assert g["numbers_unverified"] == []
    assert g["verdict"] == "well grounded"


def test_uncited_statement_is_matched_and_marked():
    ans = "Participants must be at least 18 years of age when they sign informed consent."
    g = grounding.check(ans, SOURCES)
    assert g["statements_matched"] == 1
    assert "[~S2]" in g["annotated_text"]


def test_invented_number_and_missing_source_are_flagged():
    ans = "- The dose is 400 mg every 6 weeks [S1].\n- Treatment lasts 2 years [S9]."
    g = grounding.check(ans, SOURCES)
    assert "S9" in g["invalid_citations"]
    assert "400 mg" in g["numbers_unverified"]


def test_trial_identifiers_are_not_treated_as_numbers():
    g = grounding.check("KEYNOTE-355 tests pembrolizumab (MK-3475) at 200 mg [S1].", SOURCES)
    assert g["numbers_unverified"] == []


def test_glossary_finds_plain_language_terms():
    terms = [e["term"] for e in explain_terms("Randomized phase 3 study; primary endpoint PFS by RECIST in HER2-low metastatic disease")]
    for t in ("Randomized", "Progression-free survival (PFS)", "RECIST", "HER2-low", "Metastatic"):
        assert t in terms


def test_question_words_are_not_search_terms():
    assert _terms("What treatment do participants receive, and how often?") == []
    assert "palbociclib" in _terms("Which trials compare palbociclib with letrozole?")
