import re

with open("client/tests/integration/test_sop_loop.py", "r") as f:
    content = f.read()

# remove the old if __name__ block
content = re.sub(r'if __name__ == "__main__":\s+unittest\.main\(\)', '', content)

# remove trailing lines
content = re.sub(r'\s+# Remove the extra line', '', content)

# append it at the end
content += "\n\nif __name__ == \"__main__\":\n    unittest.main()\n"

with open("client/tests/integration/test_sop_loop.py", "w") as f:
    f.write(content)
