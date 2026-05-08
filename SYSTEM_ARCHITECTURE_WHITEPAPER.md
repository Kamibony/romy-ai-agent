# Romy AI Agent: System Architecture & Engineering Whitepaper

## 1. Executive Summary

The Romy AI Agent is a multi-domain (Web & OS) autonomous agent designed to execute complex, chained B2B workflows. Operating as a state-driven machine, the system fundamentally departs from monolithic zero-shot prompts in favor of a Distributed Multi-Agent State Graph and Contract-Driven Deterministic Execution. The MVP focuses on robust, predictable task execution by dynamically interpreting and routing intents across either web environments (via a specialized Chrome Extension) or native desktop operating systems. The core philosophy prioritizes exact state perception and deterministic physical actuation, treating the LLM strictly as a cognitive reasoning engine decoupled from the physical execution layer.

## 2. Component Topology

The architecture is implemented as a monorepo consisting of four heavily decoupled, distinct systems operating in concert:

*   **FastAPI Backend (Orchestration & LLM Proxy):** Housed in `backend/`, this cloud service exposes REST interfaces, manages dual-write memory (Firestore and ChromaDB), and acts as the secure proxy to the Gemini LLM. It hosts the `MissionOrchestrator` which manages the Directed Acyclic Graphs (DAGs) of task execution.
*   **Python Client Daemon (Local Execution & State Machine):** Located in `client/`, this OS-level background daemon (`agent.py`) is the execution heart of the system. It polls for tasks via a Push/Pull model and runs the `AgentStateMachine`. It handles direct OS-level perception and actuation and manages local hardware resources (like continuous background FFmpeg recordings).
*   **Manifest V3 Chrome Extension (Web Perception & Actuation):** Residing in `extension/`, this module acts as the "eyes and hands" for web domains. It uses a "Vision-First" DOM extraction strategy to parse complex UIs and bypasses typical DOM-level JavaScript manipulation by executing native, deterministic Chrome DevTools Protocol (CDP) commands.
*   **Flutter Dashboard (Telemetry & Teleoperation Interface):** Found in `dashboard/`, this cross-platform client communicates strictly with the FastAPI Backend (avoiding direct local network connections due to firewall restrictions) to provide the Mission Composer, live telemetry, and human-in-the-loop (HITL) teleoperation controls.

## 3. The Brain (Cognitive & Orchestration Layer)

The intelligence of the agent is structured hierarchically, separating high-level orchestration from low-level execution loop mechanics.

*   **Mission Orchestration:** The `backend/mission_orchestrator.py` manages `MissionGraph` DAGs. Using a Push/Pull model, the orchestrator writes structured `AUTOMATION` blocks (which can contain compiled Standard Operating Procedures from the Vector DB) to Firestore `task_sessions`. It does not execute actions directly but queues them for the local client.
*   **The State Machine (`AgentStateMachine`):** Implemented in `client/agent.py`, the local client polls Firestore via `_poll_sessions_loop`. When a block is received, it is processed through the state machine, cycling through well-defined states: `INITIALIZING`, `EVALUATING`, `THINKING`, `ACTING`, and `TERMINATED`.
*   **Intent Parsing & Routing:** The backend classifies user or system intents dynamically. The `AgentStateMachine` interprets this classification. If the intent is `[WEB]`, it delegates the action to the Chrome Extension bridge. If `[OS]`, it delegates to local native automation threads.
*   **Fault Tolerance:** The state machine incorporates a circuit breaker mechanism. If a sub-task iteratively fails to achieve its intended state (tracked via `sub_task_iteration` up to a maximum), it triggers a `TRAINING_NEEDED` or `SUSPENDED_HITL` state, pausing execution to request human intervention.

## 4. Perception Layer (Vision-First Approach)

Perception is treated as a distinct, critical phase (the "Read" phase) occurring before any reasoning or action.

*   **Web DOM Extraction (`RomyDomMapper`):** Found in `extension/content/dom_mapper.js`, this module employs a "Hierarchical Semantic Weighting" strategy. It actively mitigates layout thrashing by separating spatial filtering (`getBoundingClientRect`) from style evaluation. Crucially, it captures not just interactive elements but static "Information Nodes" (text, prices) to provide complete context, outputting a deterministic, spatially sorted (top-left to bottom-right) flat JSON schema.
*   **OS-Level State Capture:** For native OS intents, the client daemon utilizes `mss` for frame buffer capture and integrates structural UI scraping (e.g., via `uiautomation` on Windows) to construct a representation of the desktop environment.
*   **Network Stability Mitigation:** To prevent hallucinations caused by stale DOMs during single-page application (SPA) loads, `extension/content/network_tracker.js` monitors active fetch requests, delaying state extraction until the network is quiet.

## 5. Execution Layer (The Actuators)

Once an action is determined, it is routed to the appropriate domain actuator for physical execution. The system mandates absolute system paths and explicit commands over brittle shortcuts.

*   **Web Mutations via CDP Bridge:** To bypass the limitations and security boundaries of standard JavaScript DOM manipulation (like untrusted event warnings), the Chrome Extension orchestrates actions via a `CDPLifecycleManager` (`service_worker.js`). It uses `chrome.debugger` to directly inject native hardware-level events like `Input.dispatchMouseEvent` and `Input.dispatchKeyEvent`, ensuring clicks and typing behave exactly as a human user would.
*   **Native OS Automation:** For non-web tasks, `client/agent.py` leverages `uiautomation` and `pyautogui`. To prevent OS-level interference or hotkey limitations, operations like application launches strictly use absolute system paths via `subprocess` (e.g., launching `C:\Windows\System32\calc.exe` instead of using run dialogs).

## 6. Transport & Communication Bridge

To handle the immense data payloads of continuous state extraction while maintaining a real-time control plane, the system utilizes a Split-Plane Architecture.

*   **Control Plane (WebSocket):** The Chrome Extension (`service_worker.js`) maintains a persistent WebSocket connection (`ws://127.0.0.1:8765`) to the local Python client's `LocalBridgeManager`. This channel handles lightweight signaling, commands, and immediate acknowledgments to bypass Manifest V3's 30-second Service Worker idle termination limit.
*   **Data Plane (REST HTTP):** To circumvent V8 WebSocket memory limits and prevent bridge crashes, massive payloads—such as Base64 encoded screenshots and the heavily nested DOM JSON structures generated by `GET_STATE`—are pushed asynchronously via HTTP POST directly to the local Python daemon's REST API (`http://127.0.0.1:8764/api/state`).
