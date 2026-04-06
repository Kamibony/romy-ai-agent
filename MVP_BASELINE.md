# Romy AI Agent: MVP Baseline & Capability Report

This document outlines the current state of the Romy AI Agent. It is divided into two sections: a deep dive into the Technical Architecture for the dev team, and practical QA expectations for testing.

---

## Part 1: Technical Architecture (For the Dev Team)

### 1. Data Flow of a Command

The lifecycle of an autonomous command follows a clear pipeline from UI to execution across domains:

1. **Dashboard / Mission Control**: The Flutter UI initializes the system (loading `firebase_options.dart`) and presents the command UI.
2. **Local Client (`client/agent.py`)**: A user or system command is captured and placed in the `COMMAND_QUEUE`.
3. **Intent Classification**: The backend (`backend/ai_service.py`) dynamically classifies the task via `classify_intent_with_gemini` (e.g., `[WEB]` or `[OS]`).
4. **Environment Routing**:
   - For `WEB` intents, `client/agent.py` requests an execution bridge via `local_bridge.py`.
   - The **Chrome Extension** (`extension/background/service_worker.js`) forwards the request to the target tab via CDP.
   - For `OS` intents, the `DesktopEnvironment` initiates native calls via `uiautomation` and `pyautogui` in a dedicated background worker thread to bypass COM lockups.
5. **DOM / State Extraction**: The `dom_mapper.js` (WEB) or `scan_ui_elements()` (OS) grabs the interactive schema.
6. **Backend ReAct Loop (`main.py`)**: The structured UI state, screenshot base64, clipboard status, and command text are sent to the `/api/v1/agent/command` endpoint.
7. **LLM Generation**: The prompt is processed through Gemini (`ai_service.process_with_gemini`), retrieving relevant memory playbooks from ChromaDB and yielding a sequence of JSON `actions`.
8. **Execution**: The local client parses these actions and executes them. For native OS macros like `LAUNCH_APP`, kinematic focus validation is employed. Actions complete, and the next `GET_STATE` re-evaluates the pipeline.

### 2. DOM Mapper Serialization

The Web DOM extraction is handled by `extension/content/dom_mapper.js`. It ensures visual nodes are captured without creating massive payload bloat.

- **Selective Node Capture**: Scrapes all generic DOM nodes and filters out irrelevant ones (e.g., containers spanning >50% viewport width without semantic role like `button`, `input`).
- **Layout Thrashing Mitigation**: Separates the "Read Phase" (`getBoundingClientRect`, `getComputedStyle`) from the "Write Phase" (injecting `data-romy-id` and mapping metadata).
- **A11y Enrichment**: Heavily relies on `aria-label`, `title`, and `alt` to provide fallback labels for "icon-only" elements (e.g., `<svg>`).
- **Spatial Order**: Sorts extracted interactive elements from top-left to bottom-right based on `bounds.y` and `bounds.x` to give the AI priority for items appearing highest in the DOM layout.
- **Output**: Generates a flat JSON schema containing `type`, `text`, `xpath`, `css_selector`, `ancestry`, and bounding `center` coordinates.

### 3. SOP Studio & Dual-Write Memory System

The SOP Studio is designed for B2B standard operating procedure injection, compiling natural language into machine-readable execution rules via Gemini.

- **UI Origin**: Located in `dashboard/lib/ui/sop_studio/sop_studio_screen.dart`, it sends raw inputs to `/api/v1/memory/inject_sop`.
- **LLM Compilation**: The backend `compile_sop_with_gemini` creates an agent-friendly structured rule.
- **Dual-Write Architecture (`backend/memory.py`)**:
    - **ChromaDB**: Stored locally in `/chroma_db/site_playbooks`. The document vector includes metadata like `domain`, `client_id`, and `goal` for precise similarity queries during ReAct generation (`get_playbook_rules`).
    - **Firestore**: Data is concurrently sent to Firebase (`tenants/{client_id}/memory_rules`) for fast UI CRUD operations on the Dashboard without querying the vector database.
- **Lifecycle Management**: Uses a deterministic SHA-256 hash of the rule or goal as the `doc_id` to ensure old rules are cleanly overwritten instead of duplicated.

---

## Part 2: QA & Tester Expectations (The Reality Check)

### The "Happy Paths" (What works today)
For initial manual testing, focus on these robust workflows:
- **Simple DOM Interaction**: Form filling, clicking native `<button>` tags, searching, and basic page navigation on static or lightweight SPAs.
- **Multi-Environment Routing**: Hand-offs between Chrome and OS contexts. e.g., using `LAUNCH_APP` to open Windows Calculator natively and passing inputs via fallback coordinates.
- **SOP Memory Injection**: Adding a rule like "Always close the Cookie banner first" in SOP Studio. The agent reliably pulls this into context for the specified domain.
- **Resilience Mechanisms**: Handling unexpected 401 Unauthorized errors by automatically fetching fresh tokens from the extension without UI crashing.

### Known Limitations & Brittleness (What will break)
Be aware of these failure points when testing edge cases:
- **Navigation Paralysis**: Without explicit Memory SOPs, the agent frequently gets stuck on overlapping consent modals (GDPR, cookie banners) blocking its intended target.
- **Non-Visual OS States**: While clipboard status is captured, native background applications processing data but not outputting clear visible UI changes often confuse the visual verification critic.
- **Dynamic Content & Speed**: SPAs with heavy async rendering or infinite scroll. The agent’s `WAIT` capability is simplistic and may timeout or click stale nodes if DOM hydration is slow.
- **IFrame Blindness**: The current `dom_mapper.js` does not robustly traverse deep cross-origin iframes.
- **Cross-Domain Drag & Drop**: Native drag-and-drop operations across multiple OS windows remain brittle due to DPI scaling quirks and animation latency.

### WIP Features (Mocked or Partially Wired UI)
Certain UI features in the Dashboard remain incomplete:
- **Memory Manager Delete**: Deleting a rule from the Flutter UI (`MemoryManagerScreen`) calls an endpoint, but UI state synchronization occasionally lags.
- **Emergency Abort Limitations**: While clicking "Emergency Abort" gracefully kills the `AgentStateMachine` Python loop and updates status, the *Chrome Extension* CDP connection might take a few seconds to drop pending macros fully.
- **Live Preview Flicker**: The base64 Image RepaintBoundary in Mission Control works, but is subject to latency based on the polling interval of the local desktop environment capture. Frame dropping during rapid native scroll is expected.
