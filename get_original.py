with open("client/agent.py", "r") as f:
    lines = f.readlines()
for i in range(850, 860):
    print(f"{i}: '{lines[i-1]}'")
