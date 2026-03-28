import os

# Base URL for the backend Cloud Run endpoint
BACKEND_BASE_URL = os.environ.get("BACKEND_URL", "https://romy-backend-1049976869239.europe-west1.run.app")

# Ensure the base URL does not have a trailing slash for easier joining
if BACKEND_BASE_URL.endswith('/'):
    BACKEND_BASE_URL = BACKEND_BASE_URL[:-1]

# Endpoint Paths
GET_COMMAND_ENDPOINT = f"{BACKEND_BASE_URL}/api/v1/agent/command"
PRE_FLIGHT_ENDPOINT = f"{BACKEND_BASE_URL}/api/pre_flight"
SUPERVISOR_PLAN_ENDPOINT = f"{BACKEND_BASE_URL}/api/supervisor_plan"
EVALUATE_PLAN_PROGRESS_ENDPOINT = f"{BACKEND_BASE_URL}/api/evaluate_plan_progress"
CRITIC_VERIFY_ENDPOINT = f"{BACKEND_BASE_URL}/api/critic_verify"
CLASSIFY_INTENT_ENDPOINT = f"{BACKEND_BASE_URL}/api/classify_intent"
SYNTHESIZE_PLAYBOOK_ENDPOINT = f"{BACKEND_BASE_URL}/api/synthesize_playbook"
PLAYBOOK_RULES_ENDPOINT = f"{BACKEND_BASE_URL}/api/playbook_rules"
