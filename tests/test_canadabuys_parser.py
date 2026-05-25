from pathlib import Path

from app.parsers.canadabuys_parser import parse_canadabuys_notice

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "canadabuys"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def test_parse_canadabuys_notice_extracts_structured_fields() -> None:
    parsed = parse_canadabuys_notice(_load_fixture("opp_1.html"))

    assert (
        parsed["title"]
        == "Notice of Planned Procurement (NPP) for The Provision of Multi-Tier IM/IT Research "
        "and Advisory Services for Fisheries and Oceans Canada under Supply Arrangement EN578-260567"
    )
    assert parsed["solicitation_number"] == "30007769"
    assert parsed["organization"] == "Department of Fisheries and Oceans (DFO)"
    assert parsed["location"] == "National Capital Region (NCR)"
    assert parsed["notice_type"] == "RFP against Supply Arrangement"
    assert parsed["category"] == "80161604 Information technology IT management services"
    assert parsed["contact_email"] == "Bassam.EL-DAYA@dfo-mpo.gc.ca"
    assert "NPP EN - 30007769.pdf | EN | 2026/04/17" in parsed["documents"]
    assert parsed["raw_text"].startswith("Title:")
    assert "Description:" in parsed["raw_text"]
    assert "Documents:" in parsed["raw_text"]



