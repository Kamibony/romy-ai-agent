import re

with open("client/agent.py", "r") as f:
    lines = f.readlines()

def get_indent(line):
    return len(line) - len(line.lstrip())

def fix_block(idx):
    while_line = lines[idx]
    base_indent = get_indent(while_line)

    start_idx = idx + 1
    while start_idx < len(lines) and "if PAUSE_AGENT:" not in lines[start_idx]:
        start_idx += 1

    if start_idx == len(lines): return

    # We want to force `if PAUSE_AGENT:` to base_indent + 4, and similarly
    # adjust every other line in the block based on its relative indent.

    # BUT! In original file, the lines were manually outdented by 4 spaces.
    # What if some were correctly indented, and only `if PAUSE_AGENT:` block is messed up?
    # No, the whole thing from `if PAUSE_AGENT:` down to `if sub_task_iteration >= max_sub_task_iterations:` is wrong.

    # Let's see original indent for `if PAUSE_AGENT:`
    # 640:                                 if PAUSE_AGENT: (indent 32, base 16) -> Wait! My test earlier printed 16 spaces for base indent...

    # Let's explicitly calculate target vs current indent
    first_line_indent = get_indent(lines[start_idx])
    target_first_line_indent = base_indent + 4
    indent_diff = target_first_line_indent - first_line_indent

    end_idx = start_idx
    while end_idx < len(lines):
        line = lines[end_idx]
        stripped = line.strip()
        indent = get_indent(line)

        if "Subtask retry limit reached" in stripped:
            if end_idx > 0 and lines[end_idx-1].strip() == "":
                pass
            break
        if stripped.startswith("if sub_task_iteration >= max_sub_task_iterations:"):
            if end_idx > 0 and "Subtask" in lines[end_idx-1]:
                end_idx -= 1
            break

        if stripped == "time.sleep(2)" and indent == base_indent:
            if end_idx > 0 and lines[end_idx-1].strip().startswith("# 7."):
                end_idx -= 1
            break

        end_idx += 1

    print(f"Fixing from {start_idx} to {end_idx} with diff {indent_diff}")
    for i in range(start_idx, end_idx):
        if not lines[i].strip():
            continue

        current = get_indent(lines[i])
        new_indent = current + indent_diff
        if new_indent < 0:
            new_indent = 0

        lines[i] = " " * new_indent + lines[i].lstrip()

loops = []
for i, line in enumerate(lines):
    if "while sub_task_iteration < max_sub_task_iterations:" in line:
        loops.append(i)

for l in loops:
    fix_block(l)

with open("client/agent.py", "w") as f:
    f.writelines(lines)
