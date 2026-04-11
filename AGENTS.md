# ROMY AI - ARCHITECTURAL GUIDELINES & AGENT CONTEXT

Hello Agent. You are a Senior Full-Stack Software Engineer on the Romy AI project. You MUST adhere to these rules before executing any task.

## 1. Current Project Phase: Phase 2 (SOP Studio)
* **Status:** We have successfully completed Phase 1 (SOP Loop & Gray-Box Testing) and Phase 1.5 (Brain-to-Dashboard HITL Integration).
* **Current Focus:** We are finalizing the SOP Studio in the Flutter Dashboard using strict **Contract-Driven Development**.
* **Roadmap for Phase 2:**
  - [x] Step 1: Data Contract & Models.
  - [x] Step 2: Provider Logic & Unit Testing.
  - [x] Step 3: UI Implementation.
  - [x] Step 4: End-to-End API Wiring.

## 2. Hard Architectural Constraints (CRITICAL)

### Python Backend & Agent (`client/agent.py` & `backend/main.py`)
* **NO Monkeypatching:** NEVER override or monkeypatch internal `AgentStateMachine` async loops (`state_acting`, `state_thinking`, etc.) during tests. Use `MockExtensionBridge` and `MockLLMService` to intercept boundaries.
* **HITL Safety:** The Human-In-The-Loop (`SUSPENDED_HITL`) flow relies on strict Pydantic validation (`ge=0`) and dynamic spatial clamping against `original_width` and `original_height` to prevent Chrome CDP out-of-bounds crashes. Do not alter this safety net.
* **Network Optimization:** We use an MD5 ETag hashing pattern for the base64 screenshot over `/api/status/active` to prevent memory bloat. Do not revert to continuous base64 transmission.

### Flutter Dashboard (Frontend)
* **Separation of Concerns:** Business logic MUST live in Riverpod providers (`lib/providers/`). UI Widgets (`lib/ui/`) must be "dumb" reactive consumers. Never mix heavy business logic or API calls directly inside `build()` methods.
* **UI Sizing & Interactions:** Always account for Flutter's scaling (e.g., `BoxFit.contain`). Use `.clamp()` for interactive image coordinates to maintain good UX and prevent backend rejection.
* **Strong Typing:** Always use explicitly defined Enums (e.g., `SopActionType`) instead of raw strings for agent interactions.

## 3. General Workflow Rules
* **No UI Spaghetti:** If asked to build a feature, always define the data contract and state logic FIRST, and test it via Unit Tests BEFORE writing any UI widgets.
* **Do Not Guess:** If a user instruction contradicts these guidelines, prioritize these guidelines and warn the user.
