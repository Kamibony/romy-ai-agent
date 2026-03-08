import re
text = """print(f"Error starting main client application: {e}")
print("hello world")
"""
def replacer(match):
    text = match.group(1)
    if 'Error' in text or 'error' in text.lower():
        if 'Critical' in text:
            return f'logging.critical({text})'
        return f'logging.error({text})'
    return f'logging.info({text})'
print(re.sub(r'print\((.*?)\)', replacer, text))
