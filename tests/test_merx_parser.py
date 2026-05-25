from pathlib import Path

from app.parsers.merx_parser import parse_merx_notice

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "merx"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def test_parse_merx_notice_extracts_public_abstract_fields() -> None:
    parsed = parse_merx_notice(_load_fixture("opp_55.html"))

    assert parsed["title"] == "AB-2026-03023 - Consulting Services Corporate Business Development Plan"
    assert parsed["organization"] == "City of Chestermere"
    assert parsed["location"] == "Alberta"
    assert parsed["notice_type"] == "RFP - Request for Proposal (Formal)"
    assert parsed["purchase_type"] == "Not Stated"
    assert parsed["reference_number"] == "00005003360"
    assert parsed["solicitation_number"] == "AB-2026-03023"
    assert parsed["contact_name"] == "Andrea Pritchett"
    assert parsed["contact_email"] == "procurement@chestermere.ca"
    assert parsed["status"] == "This solicitation is OPEN"
    assert "Corporate Business Development Plan" in parsed["description_raw"]
    assert "AI Overview:" in parsed["raw_text"]


def test_parse_merx_notice_handles_interceptor_pages_gracefully() -> None:
    parsed = parse_merx_notice(_load_fixture("opp_51.html"))

    assert parsed["title"] is None
    assert parsed["organization"] is None
    assert parsed["location"] is None
    assert parsed["description_raw"] is None
