with open("client/agent.py", "r") as f:
    lines = f.readlines()

def get_indent(line): return len(line) - len(line.lstrip())

def check_loop(idx):
    while_line = lines[idx]
    base_indent = get_indent(while_line)

    start_idx = idx + 1
    while start_idx < len(lines) and "if PAUSE_AGENT:" not in lines[start_idx]:
        start_idx += 1

    end_idx = start_idx
    while end_idx < len(lines):
        if "Subtask retry limit reached" in lines[end_idx]:
            # This line should probably not be shifted, but what is its indent?
            # actually it doesn't matter, we want to shift right before the `if sub_task...`
            break
        if "if sub_task_iteration >= max_sub_task_iterations:" in lines[end_idx]:
            break

        if lines[end_idx].strip() == "time.sleep(2)" and get_indent(lines[end_idx]) == base_indent:
            break

        end_idx += 1

    print(f"Loop at {idx+1}: Base indent = {base_indent}")
    print(f"Shifting lines {start_idx+1} to {end_idx}")
    print(f"Line {end_idx}: {lines[end_idx-1].strip()}")
    print("-" * 40)

for i, line in enumerate(lines):
    if "while sub_task_iteration < max_sub_task_iterations:" in line:
        check_loop(i)
