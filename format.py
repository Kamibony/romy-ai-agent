import re

with open("client/tests/integration/test_sop_loop.py", "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.strip() != "import sys":
        new_lines.append(line)

with open("client/tests/integration/test_sop_loop.py", "w") as f:
    f.writelines(new_lines)
