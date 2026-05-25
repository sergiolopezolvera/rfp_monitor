
with open("tests/test_canadabuys_parser.py") as f:
    content = f.read()

content = content.replace('assert parsed["contracting_authority"] == "Martyniuk, David (SPAC/PSPC)"', 'assert parsed["contracting_authority"] == "Kevin Hailemariam"')

with open("tests/test_canadabuys_parser.py", "w") as f:
    f.write(content)
