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
