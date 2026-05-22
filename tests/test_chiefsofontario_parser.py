from pathlib import Path

from app.parsers.chiefsofontario_parser import parse_chiefs_of_ontario_notice


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "chiefs_of_ontario"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def test_parse_chiefs_of_ontario_notice_handles_non_matching_closing_patterns() -> None:
    parsed = parse_chiefs_of_ontario_notice(_load_fixture("opp_1000.html"))

    assert (
        parsed["title"]
        == "Request for Proposals: COO Education Sector – Evaluation of the Ontario Technical Table on the Interim Funding Approach"
    )
    assert parsed["organization"] == "Chiefs of Ontario"
    assert parsed["publication_date"].isoformat() == "2022-06-28"
    assert parsed["closing_date"].isoformat() == "2022-07-13"
    assert parsed["notice_type"] == "Request for Proposals"
    assert parsed["raw_text"].startswith("Title:")


def test_parse_chiefs_of_ontario_notice_excludes_sitewide_noise_from_full_text() -> None:
    parsed = parse_chiefs_of_ontario_notice(_load_fixture("opp_993.html"))

    assert "Chiefs of Ontario Responds to 2026 Ontario Budget" not in parsed["full_text"]
    assert "Chiefs of Ontario Overview" not in parsed["full_text"]
    assert "All Rights Reserved" not in parsed["full_text"]
    assert "First Nation Post-Secondary Supports Costing Model" in parsed["full_text"]
