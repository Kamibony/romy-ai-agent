# Romy AI: Architectural Proposal for Semantic Perception and Automated Recording

## 1. Perception Depth (Extension Layer): Overcoming Systemic Blindness

### Analysis of `extension/content/dom_mapper.js`
The root cause of Romy's "systemic blindness" lies in the aggressive filtering mechanisms within `dom_mapper.js`, specifically the `isInteractive` function and its integration into `getAllNodes`.

Currently, `getAllNodes` only retains elements that pass the `isInteractive` heuristic check. This check mandates that an element must match specific interactive tags (`button`, `a`, `input`, etc.), possess specific ARIA roles (`button`, `link`, etc.), contain specific class names (e.g., `btn`, `action`), or have a computed `cursor: pointer` style.

**The Flaw:** This heavily biases the extracted DOM payload towards action-oriented elements, completely discarding static but mission-critical "Information Nodes" (e.g., prices, statuses, data tables, article text). If Romy is tasked with "find the cheapest item" or "verify the account status," the essential data nodes are filtered out before they even reach the backend.

### Architectural Proposal: Context-Aware Semantic Mapping
To achieve domain-agnostic and context-aware mapping without introducing fatal payload bloat (the original reason for pruning), we must shift from binary "interactive vs. non-interactive" filtering to a **Hierarchical Semantic Weighting** system.

**Implementation Strategy (Zero Hardcoding):**
1.  **Remove Interactive-Only Pruning:** Modify `getAllNodes` to capture a broader spectrum of nodes, including text-heavy elements (`p`, `span`, `div`, `td`, `th`) that contain actual text content.
2.  **Semantic Significance Scoring:** Instead of dropping non-interactive nodes, assign a `semantic_weight` to each node during the mapping phase.
    *   *High Weight:* Interactive elements, elements with explicit ARIA labels, headers (`h1`-`h6`).
    *   *Medium Weight:* Text nodes with significant content length, data tables (`table`, `tr`, `td`), elements containing numerical data (potential prices/metrics).
    *   *Low Weight:* Structural wrappers, empty `div`s, decorative elements.
3.  **Intelligent Pruning/Deduplication:** Apply deduplication based on structural ancestry (already partially implemented in Phase 2) but preserve "Information Nodes" if their text content is unique and significant.
4.  **Viewport Prioritization:** Maintain sorting by viewport visibility (top-left to bottom-right) but ensure that visible text nodes are included in the final payload alongside interactive elements.

---

## 2. Cognitive Alignment (Backend Layer): Restructuring LLM Reasoning

### Analysis of `backend/ai_service.py`
The current system prompts in `ai_service.py` inadvertently force Gemini into a purely tactical, execution-focused mindset. The core instruction—*"Determine the correct target element from the image and output the JSON array of actions using target_id or [x, y] coordinates"*—implies that the only valid response is a physical interaction.

While there is a `REPLY` action, the overarching context conditions the LLM to hunt for buttons and inputs rather than synthesize information. Furthermore, there is no discrete action for "absorbing" or "storing" data for subsequent reasoning.

### Architectural Proposal: The Observation-Action Loop
We need to decouple "Perception" from "Execution" within the LLM's reasoning cycle, aligning it more closely with a ReAct (Reasoning and Acting) framework.

**Implementation Strategy:**
1.  **Introduce an `OBSERVE` or `EXTRACT_DATA` Action Primitive:** Allow the LLM to explicitly state what data it is reading from the DOM/Image.
    *   *Example Action:* `{"action": "EXTRACT_DATA", "keys": ["current_price", "account_status"], "thought": "I need to read the price before deciding to click buy."}`
2.  **Refine the Core Prompt:** Shift the prompt's focus from immediate interaction to state evaluation.
    *   *New Prompt Focus:* "Analyze the current visual and structural state. If your task requires information, identify and extract it. If you have the necessary information, determine the next logical interaction to advance the state."
3.  **Stateful Memory Context:** When the LLM extracts data, the orchestrator (`client/agent.py`) should temporarily store this data in the `system_state` and pass it back in the next iteration. This allows Romy to "remember" the price she just read on page 1 when clicking a button on page 2.

---

## 3. The "Romy-Vision" Automation: Unobtrusive Mission Recording

### Analysis of Current State
Currently, flight records capture discrete screenshots and JSON data, but there is no native, automated way to produce a continuous, human-readable video of Romy's entire thought process and execution (the "Anet demos") without manual screen recording software, which is prone to hardware conflicts and requires human intervention.

### Architectural Proposal: Integrated Telemetry Rendering
We must build an automated recording pipeline directly into the Python Orchestrator (`client/agent.py`) that operates independently of the host OS's physical display constraints.

**Implementation Strategy (Automation-First):**
1.  **Background Frame Buffer Capture:** Utilize a lightweight, cross-platform library like `mss` (or leverage existing `pyautogui` screenshotting at a higher frequency) running in a dedicated asynchronous thread within `agent.py`.
2.  **Telemetry Overlay (The "Romy HUD"):** For each captured frame, programmatically overlay text using a library like `Pillow` (PIL) or `OpenCV` (`cv2`).
    *   *What to Overlay:* Current Sub-Task, Romy's `thought` (from the LLM JSON), current action being executed, and a visual marker (e.g., a simulated cursor or crosshair at the `[x, y]` coordinates of the current action).
3.  **Continuous Video Encoding:** Feed the overlaid frames into an in-memory or streamed video encoder (using `OpenCV`'s `VideoWriter` or a minimal `ffmpeg` wrapper).
4.  **Mission Lifecycle Triggers:**
    *   Begin recording automatically when a new mission/task is initialized.
    *   Encode and save the final `.mp4` artifact automatically when the agent reaches `DONE`, `TERMINATED`, or `ASK_HUMAN`.
    *   This ensures a self-contained, reproducible artifact for every execution without manual keystrokes or external software dependencies.
