# Romy Agent: SOP Integration Testing Strategy

## 1. Architectural Philosophy: Gray-Box Integration Testing

The Romy Agent (`client/agent.py`) is a complex, asynchronous state machine heavily coupled with OS-level libraries (pyautogui, uiautomation) and network bridges. Traditional unit testing by mocking internal state transitions leads to tautological tests that verify mock configurations rather than actual system behavior.

Therefore, our strategy for the "Teachable Integration" suite will utilize **Process-Level Gray-Box Testing**.

*   **No Internal Mocking:** We will not mock internal methods of `AgentStateMachine` (e.g., `step_executing`, `verify_action_natively`). The agent must run its real orchestration loop.
*   **Boundary Mocking Only:** We will mock the edges of the system—specifically the interfaces where the Agent communicates with the outside world (the LLM Backend and the Chrome Extension Bridge).

## 2. Mocking the Boundaries

To achieve deterministic, fast, and token-free tests, we must control the Agent's inputs and verify its outputs at the architectural boundaries.

### 2.1 The Mock Extension Bridge (The "World")
We will replace the actual `LocalBridgeManager` with a `MockExtensionBridge`.
*   **Input to Agent:** The mock bridge will provide canned DOM states (like our `stable_mock_app.html`) and base64 screenshots when the Agent calls for a state update (`GET_STATE`).
*   **Verification:** When the Agent dispatches an action (e.g., `CLICK target_id="submit-btn"`), the mock bridge intercepts it. The test asserts that the correct sequence of actions was dispatched to the bridge, proving the Agent made the right decisions.
*   **State Manipulation:** The test framework can dynamically alter the mock DOM between steps (e.g., hiding a button) to simulate dynamic SPAs and induce failures.

### 2.2 The Mock LLM Service (The "Brain")
We will intercept requests to the backend `ai_service.py` to prevent actual Gemini API calls.
*   **SOP Compilation:** Mock `compile_sop_with_gemini` to immediately return pre-defined, deterministic Semantic Anchoring rules (e.g., `WAIT_FOR stability; CLICK role select; SELECT admin; CLICK submit-btn`).
*   **Evaluation Bypassing:** When testing deterministic SOP execution, the Agent should rarely hit the LLM. If it does (e.g., for outcome verification), the mock LLM will return a predetermined `{"status": "complete"}` to keep the test deterministic.

## 3. The Three Core SOP Testing Pillars

Our integration suite (e.g., `tests/integration/test_sop_loop.py`) will launch the Agent process and execute tests against these three pillars:

### Pillar 1: SOP Ingestion & Memory (The "Inbound" Flow)
**Goal:** Verify that a user recording an SOP in the Flutter UI is correctly ingested, compiled, and saved.
*   **Action:** The test framework sends a simulated payload containing raw pseudo-XPath to the `/api/v1/memory/inject_sop` backend endpoint.
*   **Verification:**
    1. Assert the endpoint responds with `200 OK`.
    2. Assert the backend correctly called the LLM compiler.
    3. Assert the compiled rule (Semantic Anchors) is properly written to the mocked Firestore/ChromaDB memory module.

### Pillar 2: Deterministic Execution (The "Happy Path")
**Goal:** Verify the Agent can blindly and reliably execute a saved SOP against a stable target, bypassing zero-shot reasoning.
*   **Setup:** Seed the Mock Memory with a specific SOP rule for the target domain. Seed the `MockExtensionBridge` with the corresponding stable HTML fixture.
*   **Action:** Send a command to the Agent (e.g., "Login as Admin").
*   **Verification:**
    1. Monitor the `MockExtensionBridge`.
    2. Assert the Agent pulls the correct DOM state.
    3. Assert the Agent dispatches the exact sequence of CDP actions dictated by the SOP (e.g., `CLICK submit-btn`).
    4. Assert the Agent transitions to the `TERMINATED` success state without relying on the zero-shot LLM planner for action generation.

### Pillar 3: Graceful Failure & HITL Trigger (The "Recovery Path")
**Goal:** Verify that when deterministic execution fails, the Agent correctly halts, protects the state, and requests human guidance.
*   **Setup:** Seed the Mock Memory with the SOP. Seed the `MockExtensionBridge` with an *altered* HTML fixture where a required target ID (e.g., `submit-btn`) is missing or renamed.
*   **Action:** Send the command to the Agent.
*   **Verification:**
    1. The Agent attempts the action and native verification fails.
    2. Assert the Agent's sub-task circuit breaker trips after `max_iterations` (3).
    3. Assert the Agent transitions to `TRAINING_NEEDED` to package the failure context (screenshot, DOM, URL).
    4. Assert the Agent transitions to `SUSPENDED_HITL` and exposes this status to the Flutter UI polling endpoints.
    5. **Recovery:** The test framework injects a corrected action via `/api/human_guidance`. Assert the Agent wakes up, executes the injected action, and successfully resumes the workflow.
