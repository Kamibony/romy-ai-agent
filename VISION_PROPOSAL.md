# Architectural Analysis: Overcoming "Semantic Blindness" on Modern SPAs

## The Root Cause: "Semantic Blindness"

The failure of the agent on complex Czech SPAs (Sreality.cz, Jobs.cz) stems from an architectural limitation inherent in our Phase 2 "Semantic-First" approach. Modern web frameworks (React, Angular, Vue) heavily rely on non-semantic HTML constructs (e.g., `<div>` tags acting as buttons) paired with complex CSS styling and JavaScript event listeners.

Our current pipeline relies on `dom_mapper.js` to extract an `Accessibility (A11y) Tree` and a structural UI array. To prevent massive JSON payloads that trigger LLM API timeouts, we aggressively prune the DOM:
1.  **Strict Heuristics:** Elements are filtered based on semantic tags (`<button>`, `<input>`), explicit ARIA attributes, and a fragile list of class name heuristics (`btn`, `dropdown`, etc.).
2.  **Payload Capping:** The Python Orchestrator (`agent.py`) strictly limits the `ui_elements` array to `MAX_UI_ELEMENTS = 75` and strips crucial coordinate data (`bounds`) before dispatching to the backend.

**The Consequence:** The LLM receives a highly filtered, text-only representation of the DOM. If a crucial interactive element (like the "Pronájem" button or a custom Search bar) is built using a non-semantic `<div>` and falls outside our heuristic net, or if it gets truncated by the 75-element limit, the agent becomes literally "blind" to it. It simply cannot interact with what it cannot see in the JSON payload, leading to an `AWAITING_HUMAN_INPUT` state.

## The Proposal: Transition to "Vision-First, Coordinate-Based Execution"

To enable the agent to interact with modern, non-semantic UIs without reverting to massive, timeout-inducing 10,000-token payloads, we must pivot from a "Semantic-First" to a "Vision-First" architecture. We need to leverage Gemini's native multimodal capabilities to analyze the raw visual state of the application.

### Key Architectural Shifts

#### 1. Decouple from DOM Pruning (Embrace Raw Vision)
Instead of relying on `dom_mapper.js` to aggressively guess what is interactive, we will provide the LLM with the unadulterated visual truth: a high-quality screenshot. Gemini 2.5 Pro/Flash is highly capable of identifying buttons, input fields, and text directly from pixels, regardless of the underlying HTML structure.

#### 2. Coordinate-Based Actions (The "Point and Click" Paradigm)
Currently, actions (`CLICK`, `TYPE`) are dispatched based on a generated `target_id` mapped to an injected Set-of-Mark (SoM) overlay or a backend node ID. We will transition to **absolute coordinate-based actions (`x, y`)**.

**The New Workflow:**
1.  **State Capture:** The Chrome Extension captures a clean, full-viewport screenshot (`Page.captureScreenshot` via CDP) *without* injecting the cluttered SoM overlay.
2.  **Backend Analysis:** The LLM receives the screenshot and the user's intent. Using its vision capabilities, it visually locates the target element (e.g., "Find the 'Pronájem' button").
3.  **Coordinate Output:** The LLM outputs the estimated `[x, y]` coordinates of the center of the target element.
4.  **Execution:** The Python Orchestrator sends the coordinates back to the Chrome Extension.
5.  **Native Dispatch:** The Chrome Extension uses CDP (`Input.dispatchMouseEvent`) to simulate a native OS-level click directly at those `[x, y]` coordinates.

#### 3. Deprecating `MAX_UI_ELEMENTS` and Complex Heuristics
By relying on vision for spatial understanding, we dramatically reduce the need for the bulky `ui_elements` JSON payload. We can:
*   Remove the arbitrary `MAX_UI_ELEMENTS = 75` limit, which arbitrarily truncates long pages.
*   Simplify `dom_mapper.js` to extract only a minimal accessibility tree (for screen reader context if needed), drastically improving client-side performance.
*   Eliminate the complex and fragile class-matching heuristics, making the system universally applicable to any language or framework.

#### 4. Handling Text Input (`TYPE` Action)
For typing into inputs, the workflow remains vision-first:
1.  **Visual Location:** The LLM visually identifies the target input field and outputs its `[x, y]` coordinates.
2.  **Focus via Click:** The system executes a CDP click at `[x, y]` to focus the field.
3.  **Keyboard Simulation:** The system natively dispatches `Input.dispatchKeyEvent` events to type the text, perfectly simulating human interaction and triggering any necessary frontend framework bindings.

### Benefits of the Vision-First Approach

*   **Universal Compatibility:** Works flawlessly on React, Angular, Canvas-based SPAs, and any non-standard UI, completely bypassing "Semantic Blindness".
*   **Reduced Latency:** Eliminates the computational overhead of complex DOM mapping and traversal on the client.
*   **Smaller Payloads:** Sending a single, optimized WebP screenshot is significantly faster and cheaper than serializing and transmitting a massive, complex DOM tree.
*   **Human-like Execution:** Interacting via visual coordinates and simulated native keystrokes perfectly mimics human behavior, increasing resilience against bot detection mechanisms.

### Implementation Roadmap

1.  **Backend Prompt Engineering:** Update the Navigator LLM's system prompt to prioritize visual analysis and output strict `[x, y]` coordinate arrays for interaction targets.
2.  **Client-Side Simplification:** Remove the Set-of-Mark (SoM) injection logic from `content_script.js` and `service_worker.js` to ensure clean screenshots.
3.  **Action Primitives Update:** Modify the `EXECUTE_ACTION` handler in `service_worker.js` to accept `[x, y]` coordinates for `CLICK` and `TYPE` actions, replacing the `target_id` mapping logic.
4.  **Verification Update:** Update the Critic LLM to verify success primarily by comparing before-and-after screenshots, rather than relying on diffs of the heavily pruned `ui_elements` array.