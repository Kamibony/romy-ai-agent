with open("client/agent.py", "r") as f:
    lines = f.readlines()
for i in range(850, 860):
    print(len(lines[i-1]) - len(lines[i-1].lstrip()), repr(lines[i-1]))
