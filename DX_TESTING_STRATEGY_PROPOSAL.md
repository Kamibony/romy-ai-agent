# Developer Experience (DX) and Automated Testing Strategy Proposal

## 1. Local Orchestration: Seamless Environment Management

**The Problem:** Juggling multiple terminals and virtual environments to start the FastAPI Backend, Python Daemon, Flutter Dashboard, and Chrome Extension.

**The Solution:**
*   **Unified Task Runner / Process Manager:** While Docker Compose is great for containerized microservices, local OS-level automation daemons (like the Romy Agent) and hot-reloading frontends (Flutter/Chrome Extensions) benefit from native process managers.
    *   *Recommendation:* Upgrade the existing `dev_runner.py` using a Python Terminal User Interface (TUI) library like **Textual** or **Rich**. This will transform the runner into a single split-pane terminal dashboard displaying the status and logs of the Backend, Client Daemon, and Flutter Web Server simultaneously.
    *   *Auto-Setup:* The runner will automatically manage virtual environments and install dependencies (`requirements.txt`, `pub get`) if they are missing or outdated, abstracting away the setup friction.

## 2. Execution & Triggering: Frictionless Task Initiation

**The Problem:** Manually formulating and sending complex JSON payloads via CLI or Postman just to trigger agent tasks.

**The Solution:**
*   **CLI Task Trigger Tool:** Introduce a lightweight developer CLI (e.g., `dev_cli.py` built with **Typer** or **Click**).
    *   Instead of raw JSON, developers can run: `python dev_cli.py trigger "Login as Admin"` or `python dev_cli.py run-scenario login_scenario.yaml`.
*   **Fixture Catalog:** Maintain a directory (`tests/fixtures/scenarios/`) containing YAML or JSON files defining complex test payloads.
*   **Dashboard "Dev Tools" Panel:** Add a hidden "Developer Tools" drawer in the Flutter Dashboard (enabled only in local dev mode) that lists predefined tasks and allows triggering them with a single click.

## 3. Log Aggregation & Observability: Centralized Debugging

**The Problem:** Hunting for scattered logs across the backend terminal, the daemon terminal, and the isolated Chrome Extension console to piece together failures.

**The Solution:**
*   **Unified Log Stream in TUI:** The upgraded `dev_runner.py` will capture `stdout/stderr` from all sub-processes and multiplex them into a single, color-coded, scrollable log viewer.
*   **Chrome Extension Log Forwarding:** When the extension detects local development mode, it will override standard `console.log/warn/error`. It will forward these logs via a lightweight local HTTP endpoint or WebSocket exposed by the `dev_runner.py` or the Backend. This brings extension logs directly into the centralized terminal view.
*   **Structured Tracing:** Implement a shared `request_id` or `session_id` that is passed from the Backend -> Client Daemon -> Chrome Extension. The central log viewer can then filter logs by this ID, instantly showing the full lifecycle of a single task across all components.

## 4. Automated Evaluation: End-to-End Test Verification

**The Problem:** Manually watching the Flutter UI or the browser to verify if the agent successfully completed its job.

**The Solution:**
*   **Playwright for Gray-Box Automation:** Utilize **Playwright (Python)** to automate the end-to-end evaluation, treating the system as a gray box.
*   **The Automated Test Flow:**
    1.  **Environment Setup:** Playwright programmatically launches a Chrome instance with the Romy Chrome Extension pre-loaded.
    2.  **Task Injection:** The test framework uses the Backend API to inject a specific agent task (e.g., "Extract table data").
    3.  **Synchronization:** The test polls the Backend API or listens to local state to wait until the Agent reports a `TERMINATED` or `COMPLETED` status.
    4.  **Verification:** Playwright directly inspects the DOM of the target website to verify the result (e.g., asserting a button was clicked, or data was entered) AND inspects the Backend to ensure the correct structured data was extracted.
*   **Mock Targets:** As outlined in the SOP Testing Strategy, Playwright will initially navigate to locally hosted, stable HTML fixtures to ensure deterministic, network-independent evaluation before scaling to live sites.

## Proposed Next Steps for Implementation
1.  **Review and refine** this proposal.
2.  **Phase 1:** Upgrade `dev_runner.py` with `Rich`/`Textual` for unified orchestration and log viewing.
3.  **Phase 2:** Build the `dev_cli.py` and fixture catalog for easy task triggering.
4.  **Phase 3:** Implement extension log forwarding to the central viewer.
5.  **Phase 4:** Write the first Playwright E2E evaluation script.
