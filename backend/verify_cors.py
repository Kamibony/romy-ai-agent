import re
import sys

def verify_cors_fix():
    with open('backend/main.py', 'r', encoding="utf-8") as f:
        content = f.read()

    # Check that allow_origins=["*"] is GONE
    if 'allow_origins=["*"]' in content:
        print("❌ FAILED: allow_origins=['*'] still present in backend/main.py")
        sys.exit(1)

    # Check for restricted origins list
    if 'origins = [' not in content:
        print("❌ FAILED: origins list not found in backend/main.py")
        sys.exit(1)

    # Check for specific trusted domains
    trusted_domains = [
        "https://romy-ai-agent.web.app",
        "https://romy-ai-agent.firebaseapp.com",
        "chrome-extension://.*"
    ]

    for domain in trusted_domains:
        if domain not in content:
            print(f"❌ FAILED: Trusted domain '{domain}' not found in backend/main.py")
            sys.exit(1)

    # Check for allow_origin_regex
    if 'allow_origin_regex="chrome-extension://.*"' not in content:
        print("❌ FAILED: allow_origin_regex not found or incorrect in backend/main.py")
        sys.exit(1)

    print("✅ SUCCESS: CORS policy is restricted to trusted origins.")

if __name__ == "__main__":
    verify_cors_fix()
