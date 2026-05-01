import logging
import os
import sys
from unittest.mock import patch

# Mock environment variable for testing the verification script itself if needed
os.environ["ALLOWED_EXTENSION_IDS"] = "abc123def456,ghi789jkl012"

def verify_cors_fix():
    logging.basicConfig(level=logging.INFO)

    with open('backend/main.py', 'r', encoding="utf-8") as f:
        content = f.read()

    # 1. Check that allow_origins=["*"] is GONE (if it ever was there)
    if 'allow_origins=["*"]' in content:
        logging.error("❌ FAILED: allow_origins=['*'] still present in backend/main.py")
        sys.exit(1)

    # 2. Check for restricted origins list
    if 'origins = [' not in content:
        logging.error("❌ FAILED: origins list not found in backend/main.py")
        sys.exit(1)

    # 3. Check for the new dynamic logic
    dynamic_indicators = [
        'os.getenv("ALLOWED_EXTENSION_IDS", "").split(",")',
        'allow_origin_regex = f"chrome-extension://({extension_ids_pattern})"',
        'allow_origin_regex = None',
        're.escape(eid)'
    ]

    for indicator in dynamic_indicators:
        if indicator not in content:
            logging.error(f"❌ FAILED: Dynamic CORS logic indicator '{indicator}' not found in backend/main.py")
            sys.exit(1)

    # 4. Check that the generic wildcard regex is GONE
    if 'allow_origin_regex="chrome-extension://.*"' in content:
        logging.error("❌ FAILED: Generic 'chrome-extension://.*' regex still present in backend/main.py")
        sys.exit(1)

    logging.info("✅ SUCCESS: CORS policy is dynamically restricted to authorized extension IDs.")

if __name__ == "__main__":
    verify_cors_fix()
