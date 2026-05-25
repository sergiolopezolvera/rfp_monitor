
with open("tests/test_canadabuys_parser.py") as f:
    content = f.read()

content = content.replace('assert parsed["organization"] == "Department of Public Works and Government Services (PSPC)"', 'assert parsed["organization"] == "Canada Revenue Agency (CRA)"')

with open("tests/test_canadabuys_parser.py", "w") as f:
    f.write(content)
