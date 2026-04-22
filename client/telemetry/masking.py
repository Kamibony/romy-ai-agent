import re

def mask_pii(text: str) -> str:
    if not text:
        return text

    # Mask emails
    text = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED_EMAIL]', text)

    # Mask SSN (basic)
    text = re.sub(r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b', '[REDACTED_SSN]', text)

    # Mask Credit Cards (basic)
    text = re.sub(r'\b(?:\d{4}[-\s]?){3}\d{4}\b', '[REDACTED_CC]', text)

    # Mask Phone numbers (basic)
    text = re.sub(r'\b(?:\+\d{1,2}\s)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b', '[REDACTED_PHONE]', text)

    return text

def mask_dict_pii(data: dict) -> dict:
    if not isinstance(data, dict):
        return data

    masked_data = {}
    for k, v in data.items():
        if isinstance(v, str):
            masked_data[k] = mask_pii(v)
        elif isinstance(v, dict):
            masked_data[k] = mask_dict_pii(v)
        elif isinstance(v, list):
            masked_data[k] = [mask_dict_pii(i) if isinstance(i, dict) else mask_pii(i) if isinstance(i, str) else i for i in v]
        else:
            masked_data[k] = v

    return masked_data
