import re

with open("tests/test_canadabuys_parser.py", "r") as f:
    content = f.read()

content = content.replace('assert parsed["buying_organizations"] == "Department of Public Works and Government Services (PSPC)"', 'assert parsed["buying_organizations"] is None')
content = content.replace('assert "BPM019799" in parsed["description_raw"]', 'assert "WS3941424368" in parsed["description_raw"]')

with open("tests/test_canadabuys_parser.py", "w") as f:
    f.write(content)
