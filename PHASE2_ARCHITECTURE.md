# ROMY AI Agent - Phase 2 Architecture (The Global Solution)

This document defines the architectural pillars for Phase 2 of the ROMY AI Agent.
The goal of Phase 2 is to transition from an "Open-Loop MVP" (fragile DOM scraping and batch execution) to a "Closed-Loop, Vision-First, Event-Driven" autonomous agent.

## 1. Core Execution: The ReAct Closed-Loop
We are abandoning batch-action execution (blindly firing sequential commands).
* **Single-Step Cycle:** The agent executes strictly ONE action at a time.
* **ReAct (Reason + Act):** Every cycle involves the LLM outputting a `Thought` (evaluating the screen) and an `Action`.
* **Implicit Verification:** Before deciding the *next* action, the agent must verify if the *previous* action succeeded by comparing the new state to the expected outcome.
* **Goal & Context Stack:** The agent maintains a short-term memory stack. If interrupted by a popup, it pushes "Handle Popup" to the stack, completes it, and pops back to the primary goal (e.g., "Book Flight").

## 2. Perception: Hybrid Modality (Vision + A11y)
Pure DOM scraping is dead (due to React, Shadow DOMs, and dynamic classes). Pure Vision hallucinates text. We use a hybrid approach.
* **Set-of-Mark (SoM) Injection:** A lightweight local script injects an SVG overlay with numbered bounding boxes over interactable elements in the active viewport.
* **Accessibility (A11y) Tree:** Alongside the SoM screenshot, we extract a simplified semantic tree (Role, Name, State, Bounding Box) to provide exact text and context without clutter.
* **Viewport Awareness:** The LLM prompt always includes viewport metadata (e.g., "Viewing Y: 0 to 1080 of 4000px"). Explicit `SCROLL` actions are first-class citizens.
* **Clutter Mitigation:** Bounding boxes are strictly applied ONLY to visible, un-obscured elements (respecting `z-index`, `opacity`, and `display` rules).

## 3. Communication: Event-Driven WebSockets
We are eliminating REST polling (`setInterval` / `time.sleep()`).
* **Local Bridge:** The Python core and Chrome Extension communicate via a persistent local WebSocket server.
* **Zero Latency:** Commands from the cloud (Firestore Realtime Listeners) are pushed instantly through the WebSocket to the extension.
* **Instant Telemetry:** The extension pushes DOM mutations and execution results back to Python instantaneously.

## 4. Execution & Interaction: Native CDP
We are moving away from fragile content script injections for simulating clicks.
* **Chrome DevTools Protocol (CDP):** The extension uses the `chrome.debugger` API.
* **Trusted Events:** All clicks, keystrokes, and scrolls are dispatched as OS-level native events, bypassing modern bot-detection and security policies.
* **Clean Screenshots:** `Page.captureScreenshot` is used natively from the background worker for perfect visual state capture.

## 5. Resilience: Self-Healing & HITL
* **Stuck Detector:** If the visual hash or A11y tree does not change after 2-3 action attempts, the agent automatically halts and triggers an `ASK_HUMAN` state.
* **Human-in-the-Loop (HITL):** The agent gracefully pauses, pushing a notification to the mobile/web dashboard, and waits for explicit user intervention before resuming.
* **Local Blackbox (Flight Recorder):** Every closed-loop cycle logs the `[Screenshot Before]`, `[LLM Prompt]`, `[LLM Response]`, and `[Action Taken]` locally for trivial debugging.

## 6. Proactive Threat Modeling & Actuation Guardrails
To transition successfully to a closed-loop execution model, the following architectural traps must be addressed at the actuation layer (`service_worker.js` and `agent.py`) to prevent infinite hangs, misfires, and DOM race conditions:

### Trap A: DOM Race Conditions (Premature Vision)
* **The Trap:** Natively executed actions (CLICK, TYPE, SCROLL) trigger asynchronous SPA animations or data fetching. Requesting the next `GET_STATE` immediately captures a mid-transition or pre-loaded frame, blinding the LLM.
* **The Guardrail (Post-Action Stabilization):** The Python orchestrator (`agent.py`) must enforce a strict, asynchronous "cooldown" (e.g., 1.5 seconds) immediately after dispatching any native action. This guarantees the SPA DOM settles before the next visual state is captured, ensuring the ReAct loop operates on a stable UI.

### Trap B: The "Blind Typist"
* **The Trap:** OS-level or CDP `TYPE` commands require an active cursor focus. If the LLM dispatches `TYPE` without a preceding `CLICK` on the input field, the keystrokes are sent into the void.
* **The Guardrail:** The Chrome Extension (`service_worker.js`) must automatically synthesize a native `mousePressed` and `mouseReleased` sequence at the provided `[x, y]` coordinates immediately before dispatching keyboard events (`Input.dispatchKeyEvent`). The orchestrator must ensure coordinates are extracted and passed for all `TYPE` actions.

### Trap C: Device Pixel Ratio (DPR) Misses
* **The Trap:** Vision models and extracted bounding boxes operate in CSS pixels, but CDP often requires physical pixels (or vice-versa depending on the scaling context). If a user's Windows display scaling is set to 150%, the native clicks will miss their intended targets.
* **The Guardrail:** Before executing native mouse events via CDP, the extension must actively query `window.devicePixelRatio`. The incoming `[x, y]` CSS coordinates from the AI orchestrator must be explicitly multiplied by the DPR to map correctly to the browser's physical viewport scaling.

### Trap D: HITL Resume Loop (The Zombie Suspension)
* **The Trap:** When the agent detects it is stuck (e.g., repeating the same state), it transitions to `SUSPENDED_HITL` and awaits human intervention. If a human provides a "Ghost Click", the agent processes it but abruptly shuts down if its internal iteration counters max out, breaking the continuous ReAct cycle.
* **The Guardrail:** The state machine (`AgentStateMachine`) must correctly suspend execution while waiting for the `hitl_event`. Crucially, upon waking up and delegating the human's Ghost Click, the orchestrator must enforce a post-action stabilization wait (Trap A) and actively **reset the sub-task iteration counter to 0**. This ensures the agent is granted a fresh set of attempts to evaluate the new, human-guided DOM state.
