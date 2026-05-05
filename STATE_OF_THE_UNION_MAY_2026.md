# Romy AI System Status & Architecture Report

Here is a comprehensive, objective, deep-dive audit of the current Romy AI Agent codebase based on the existing repository state.

---

## 1. 🎯 Executive Summary

The Romy AI ecosystem is currently in a transitional state between Phase 2 (SOP Studio & Deterministic Execution) and Phase 3 (Cognitive Overhaul & Live Chrome Execution). It operates as a modular, state-driven workflow agent capable of executing chained missions on web targets.

**Current Factual State & Capability:**
*   **Execution Model:** The system has moved away from a purely zero-shot, prompt-heavy monolith towards a **Distributed Multi-Agent State Graph** and **Contract-Driven Deterministic Execution**. It heavily relies on the `AgentStateMachine` in `client/agent.py`.
*   **Web Automation:** The agent drives Chrome via a dedicated extension bridge using native CDP (Chrome DevTools Protocol) commands (`CLICK`, `TYPE`, etc.), avoiding fragile OS-level GUI automation (`pyautogui`) where possible, although fallback capabilities remain.
*   **SOP Integration:** Romy successfully ingests, compiles (via Gemini), and executes pre-defined Standard Operating Procedures (SOPs) retrieved from a Vector DB (ChromaDB) to navigate known web applications predictably.
*   **Perception:** The DOM extraction in the Chrome extension (`dom_mapper.js`) captures both interactive UI elements and static "Information Nodes" (e.g., text, prices) using a Hierarchical Semantic Weighting strategy, overcoming previous "systemic blindness".
*   **Dashboard:** The Flutter dashboard acts as the command center, featuring a "Mission Composer" to build sequential JSON data structures containing Automation Blocks (SOPs) and AI/Logic Blocks.
*   **Recording:** An automated, background FFmpeg recording pipeline captures the entire agent's thought process without manual screen recording software.

## 2. 🌍 System Architecture & Data Flow

The architecture operates on a Push/Pull model, isolating cognitive processing from execution intent routing.

1.  **Cloud Backend (`backend/main.py`):**
    *   Exposes a FastAPI REST interface for the Flutter dashboard.
    *   Manages memory (Firestore & ChromaDB).
    *   Hosts the `MissionOrchestrator`, which processes `MissionGraph` DAGs (Directed Acyclic Graphs).
    *   When a mission starts, the backend writes `AUTOMATION` blocks to Firestore `task_sessions` documents.
    *   Provides specialized Gemini AI endpoints (`ai_service.py`) for Pre-flight, Supervisor Planning, Intent Classification, Execution, and Verification.

2.  **Python OS Client / Local Agent (`client/agent.py`):**
    *   A continuous background daemon that polls Firestore for new task sessions via `_poll_sessions_loop`.
    *   Runs the `AgentStateMachine`, cycling through states: `INITIALIZING`, `EVALUATING`, `THINKING`, `ACTING`, `TERMINATED`, or failure states like `TRAINING_NEEDED` and `SUSPENDED_HITL`.
    *   Hosts a Local API server (`socketserver.ThreadingTCPServer` binding to `0.0.0.0`) to handle requests (like the Dashboard telemetry heartbeat) and manage local recordings.
    *   Communicates with the Chrome Extension via a split-plane WebSocket/HTTP bridge.

3.  **Chrome Extension Perception (`extension/background/service_worker.js` & `extension/content/dom_mapper.js`):**
    *   **Control Plane:** Connects to the Local Python Agent via WebSocket (`ws://127.0.0.1:8765`) to receive lightweight commands (e.g., `GET_STATE`, `EXECUTE_ACTION`).
    *   **Data Plane:** Uses HTTP POST to push massive state payloads (DOM JSON and Base64 screenshots) back to the local Python Agent (`http://127.0.0.1:8764/api/state`) to bypass V8 WebSocket memory limits.
    *   Uses `chrome.debugger` to directly dispatch CDP commands (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`) natively, bypassing OS hotkey limitations.
    *   Monitors network stability (`network_tracker.js`) to delay state extraction until the page is quiet.

4.  **Flutter Dashboard:**
    *   Communicates entirely with the Python Backend via REST (`api_client_provider.dart`), using dynamically resolved ports.
    *   Manages state via Riverpod providers.
    *   Orchestrates missions and views telemetry.

## 3. ✅ Recently Implemented Foundations

Several major architectural shifts and technical debt resolutions have been successfully integrated:

*   **Semantic Data Extraction (`EXTRACT_DATA` Primitive):** Resolved "systemic blindness" by updating `backend/ai_service.py` to support an explicit `EXTRACT_DATA` action, prioritizing observation before mutation. `dom_mapper.js` now includes static text nodes via `isInformationNode`.
*   **Split-Plane Communication Architecture:** The fragile mock bridge was replaced with a robust live Chrome Extension bridge. Command signaling operates over WebSocket, while heavy state payloads (Screenshots, UI element arrays) are transmitted via HTTP POST.
*   **Deterministic SOP Execution (Gray-Box Flow):** The system now prioritizes deterministic execution of compiled rules (Semantic Anchors) fetched from memory over expensive, zero-shot LLM reasoning for every step.
*   **Chained Missions (Modular Workflow Agent):** The system can now execute sequential data structures (`MissionGraph`) composed of AI reasoning blocks and Automation blocks, passing variables between them.
*   **Continuous Telemetry Recording ("Romy-Vision"):** A background `mss` frame buffer capture and video encoding pipeline is active, overlaying the agent's thoughts and actions directly onto the video without relying on OS-level screen recorders.
*   **UTF-8 File Safety:** All file I/O `open()` operations are now explicitly bound to `encoding="utf-8"` to prevent Windows platform crashes.
*   **FastAPI Asynchronous Safety:** Blocking operations in the FastAPI backend (Firestore calls, AI prompts) are now safely wrapped in `run_in_threadpool` to prevent ASGI event loop starvation.

## 4. 🚧 Current Bottlenecks & Execution Realities

Despite architectural improvements, E2E missions currently face specific logical and technical friction points:

*   **Sub-Task Circuit Breaker Tripping:** In the `AgentStateMachine`, the `max_sub_task_iterations` is strictly set to 3. If an action fails natively (e.g., CDP cannot find coordinates, or the Critic Agent rejects the state change), the system abruptly trips the circuit breaker and enters `TRAINING_NEEDED` or `SUSPENDED_HITL`.
*   **Over-reliance on Native Verification:** The `verify_action_natively` function strictly requires a structural DOM change or successful CDP dispatch. In complex SPAs where DOM changes are subtle or delayed, the verification fails prematurely, causing a retry loop.
*   **The "Wait and See" Delay:** Because the agent operates in discrete `EVALUATING` -> `THINKING` -> `ACTING` loops relying on large base64 screenshot hashes and LLM processing (timeout constraints set to 15-120 seconds), a single visual step feels artificially slow to a human observer. The system prioritizes certainty over speed.
*   **Dynamic SPA Modals & Overlays:** The `dom_mapper` struggles to filter out invisible overlays (like collapsed dropdowns or obscured modals) mathematically. Consequently, the LLM may attempt to click an element that exists in the DOM but is visually occluded, resulting in a CDP coordinate failure.
*   **The `TRAINING_NEEDED` Bottleneck:** Currently, when deterministic SOP execution fails, the agent assumes its memory is outdated rather than attempting zero-shot recovery. It halts and waits for a "Human-In-The-Loop" (HITL) correction via the dashboard, halting autonomous progress.

## 5. 🔮 Technical Roadmap & Active Solutions

To address the immediate bottlenecks and stabilize Scenario C / HITL pipelines, the following architectural steps are currently in progress or planned:

1.  **Semantic Self-Healing (Live Healing Harness):**
    *   *Solution:* We are developing a `state_self_healing` flow within the `AgentStateMachine`. Instead of immediately dropping to `SUSPENDED_HITL` when a sub-task fails, the agent hits a `rescue_element_with_gemini` endpoint. This allows Gemini to analyze the failure context and propose an alternative action or selector dynamically, attempting self-correction before requiring human intervention.
2.  **`RESET_VIEW` Active Primitive Implementation:**
    *   *Solution:* To combat the SPA Modal issue, the `RESET_VIEW` action will be utilized more aggressively. When state extraction is ambiguous or occluded, the agent will sequentially dispatch an 'Escape' key press and a neutral mouse click (coordinates `1, 1`) to close overlays and force the DOM to settle before state evaluation.
3.  **Dynamic JS Execution Senses (`EXECUTE_JS`):**
    *   *Solution:* We will empower the Navigator Agent with the ability to dispatch read-only JS snippets into the Chrome ISOLATED world via `chrome.scripting.executeScript`. This will allow the LLM to read window state variables (e.g., `window.__INITIAL_STATE__`) directly when visual mapping fails, providing an alternative perception vector.
4.  **Auto-Curriculum (The Synthesizer Agent):**
    *   *Solution:* Implementing the `state_learning_routine` fully. When a human *does* provide guidance via HITL (Ghost Clicks) to recover a failed state, a background Synthesizer Agent will asynchronously review the telemetry and automatically compile a new "Playbook Rule" and persist it in ChromaDB, ensuring the failure does not repeat.