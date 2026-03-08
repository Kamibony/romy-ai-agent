import re
import sys

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Add logging import
    if 'import logging' not in content:
        # Find the first import and add it there
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                lines.insert(i, 'import logging')
                break
        else:
            lines.insert(0, 'import logging')
        content = '\n'.join(lines)

    # Replace print("...") with logging.info("...")
    # Replace print(f"...") with logging.info(f"...")
    # Replace print(f"Error...") with logging.error(f"Error...")

    def replacer(match):
        text = match.group(1)
        if 'Error' in text or 'error' in text.lower():
            if 'Critical' in text:
                return f'logging.critical({text})'
            return f'logging.error({text})'
        return f'logging.info({text})'

    content = re.sub(r'print\((.*?)\)', replacer, content)

    with open(filepath, 'w') as f:
        f.write(content)

process_file('client/main.py')
process_file('client/agent.py')
process_file('client/auth_window.py')
process_file('client/hotkey_manager.py')
process_file('client/tray_manager.py')
