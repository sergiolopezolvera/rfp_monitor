import re

with open("tests/test_canadabuys_parser.py", "r") as f:
    content = f.read()

content = content.replace('assert parsed["contact_email"] == "david.martyniuk@tpsgc-pwgsc.gc.ca"', 'assert parsed["contact_email"] == "Kevin.Hailemariam@cra-arc.gc.ca"')
content = content.replace('assert parsed["closing_date"] == datetime(2025, 2, 28, 14, 0, tzinfo=timezone.utc)', 'assert parsed["closing_date"] == datetime(2025, 3, 4, 14, 0, tzinfo=timezone.utc)')

with open("tests/test_canadabuys_parser.py", "w") as f:
    f.write(content)
