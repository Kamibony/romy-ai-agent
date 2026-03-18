# PHASE 3: The Cognitive Overhaul (Architectural Brainstorming)

## The Core Paradigm Shift
Phase 2 established a robust execution layer using a monolithic ReAct loop where a single prompt parsed intent, analyzed state, chose actions, and verified results. Phase 3 transitions this monolith into a **Distributed Multi-Agent State Graph**. This divides the cognitive load, allowing specialized agents to act asynchronously, reducing hallucination, and enabling autonomous reasoning and error correction.

## The Multi-Agent Team

### 1. Pre-Flight Agent (Fast Check)
*   **Role:** Analyzes the user command *before* invoking the web execution loop.
*   **Input:** User text/audio command.
*   **Output:** Returns `{"status": "ok"}` if the command has all necessary parameters (e.g., flight dates, destination), or `{"status": "ASK_HUMAN", "reason": "..."}` to request missing information natively.
*   **Benefit:** Prevents expensive browser spin-ups when foundational data is missing.

### 2. Supervisor Agent (The Planner)
*   **Role:** Generates a deterministic sequence of sub-tasks from the verified prompt.
*   **Input:** Verified User Command.
*   **Output:** JSON Array of strings (e.g., `["Navigate to pelikan.cz", "Type Origin", "Type Destination", "Select Dates", "Click Search"]`).
*   **Benefit:** Replaces the "What should I do next?" guess with a concrete roadmap.

### 3. Navigator Agent (The Actor)
*   **Role:** Responsible for determining the exact OS or CDP action to achieve the *current sub-task*.
*   **Input:** Current Sub-Task, Current DOM State, Screenshot (Visuals).
*   **Output:** A strict, single JSON Action Dictionary (e.g., `{"action": "CLICK", ...}`).
*   **Benefit:** Small, focused prompts tailored only to completing the immediate step.

### 4. Critic Agent (The Verifier)
*   **Role:** Validates the success of the Navigator's action based on state change.
*   **Input:** Target Sub-Task, Before State (DOM+Vision), Action Executed, After State (DOM+Vision).
*   **Output:** `{"success": true/false, "reason": "..."}`.
*   **Benefit:** Deterministic verification that loops the Navigator for retries upon failure before moving to the next task in the Supervisor's plan.

## The Learning System (Implemented)

### Autonomous Memory (RAG Vector DB)
To evolve beyond approaching every website identically, a local **ChromaDB** Vector DB stores domain-specific site playbooks.
*   **Mechanism:** When the Navigator operates on a specific URL (provided via `current_url`), the backend parses the domain and queries ChromaDB to retrieve site-specific rules.
*   **Application:** Injects retrieved rules directly into the Navigator's prompt as `[SITE_SPECIFIC_RULE]`, allowing the agent to anticipate dynamic site behaviors (e.g., "Wait for autocomplete dropdown on pelikan.cz") before failing.

### The Sleep Cycle (Synthesizer Agent)
*   **Mechanism:** An explicit endpoint (`/api/synthesize_playbook`) enables an asynchronous review process of completed tasks.
*   **Role:** The Synthesizer Agent uses Gemini 2.5 Flash to analyze the telemetry of executed actions for a given domain, focusing on retries and eventual successes.
*   **Output:** Generates concise, universal "Playbook Rules" and persists them in ChromaDB. This creates an auto-curriculum of successful workarounds that the Navigator naturally queries on subsequent runs.

## Action Primitives

### 1. `RESET_VIEW` (Active)
Natively integrated to handle dynamic SPA overlays (dropdowns, date pickers, modals). It sequentially dispatches an 'Escape' key press and a neutral mouse click (coordinates `1, 1`) via CDP to close overlays and allow the DOM to settle before state verification.

### 2. `EXECUTE_JS` (Planned - Dynamic Senses)
*   **Capability:** Allows the Navigator to write custom JS snippets (e.g., `return window.__INITIAL_STATE__.user.email;`) to extract data inaccessible via standard DOM mapping or Vision parsing.
*   **Security Constraint:** Execution must strictly occur within the **ISOLATED** world via `chrome.scripting.executeScript` to mitigate XSS risks and prevent unauthorized interaction with the page's MAIN world variables or tokens.
