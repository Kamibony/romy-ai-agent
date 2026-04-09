# Architectural Proposal: Romy Foundational Enhancements

## Challenge 1: Physical Layer Bottlenecks (Speed & Reliability)

### Symptom A: BFCache Disconnects and Hard Navigation Delays
**Problem**: When Romy triggers a hard navigation, the Chrome extension's content script context is destroyed or put into the BFCache. The `WAIT_FOR_STABILITY` message sent from `service_worker.js` hangs until its maximum timeout (5000ms), and then falls back to a 1.5s static wait. This results in a ~6.5s delay on every page load.

**Proposed Solution: Navigation-Aware Promise Race**
1. **File to modify**: `extension/background/service_worker.js`
2. **Logic Flow**:
   - Introduce a new listener using `chrome.webNavigation.onCommitted` (or by detecting port disconnects/tab updates via `chrome.tabs.onUpdated`) to detect when a hard navigation occurs on the active session tab.
   - Refactor the `WAIT_FOR_STABILITY` execution block into a `Promise.race()`.
   - The race will be between:
     a) The existing `chrome.tabs.sendMessage` for dynamic stability (content script debounce).
     b) A new `Navigation Observer` promise that instantly resolves when `chrome.tabs.onUpdated` fires with `status: 'loading'` or when the port disconnects due to navigation.
     c) The existing timeout fallback.
   - If the navigation promise wins, we bypass the static 1.5s fallback and immediately wait for the new page's `DOM_READY` or `load` event, avoiding the timeout penalty.

### Symptom B: The 'Stable State' Double-Penalty
**Problem**: In `client/agent.py`, the orchestrator actively drops the `SUB_TASK_COMPLETE` flag if it occurs in the same batch as a state-mutating action (e.g., `CLICK`). This forces a redundant `GET_STATE` round-trip to the LLM just to get the `SUB_TASK_COMPLETE` action again.

**Proposed Solution: Native State Verification Bypass**
1. **File to modify**: `client/agent.py` (specifically `AgentStateMachine.state_acting`)
2. **Logic Flow**:
   - Remove the hard drop of `SUB_TASK_COMPLETE` when `has_mutated_state` is true.
   - Instead, track if `SUB_TASK_COMPLETE` was emitted in the batch.
   - If a mutating action (like `CLICK`) succeeds natively (via `service_worker.js` or `DesktopEnvironment`), we *conditionally accept* the `SUB_TASK_COMPLETE` flag without a redundant LLM verification round-trip.
   - We still enforce a check to ensure the native action actually succeeded. If the native execution fails, the batch breaks, the completion flag is dropped, and the agent fast-fails into the next iteration.

## Challenge 2: Cognitive Layer (State, Fast-Failing, and Learning Hooks)

### Symptom A: Supervisor Amnesia
**Problem**: When the dynamic feedback loop is triggered (`trigger_supervisor_feedback_loop` in `agent.py`), the Supervisor is called to generate a new plan. Currently, it overwrites `self.sub_tasks` with the new plan and drops the original context, sometimes starting from Step 1.

**Proposed Solution: Contextual Plan Splicing**
1. **File to modify**: `client/agent.py` (`AgentStateMachine.trigger_supervisor_feedback_loop`)
2. **Logic Flow**:
   - Instead of asking the Supervisor to generate a "new plan", we ask it to "recover and amend the plan".
   - Pass the `current_sub_task_index`, `completed_tasks`, and the specific `reason` (roadblock) to the LLM prompt.
   - Splice the new steps into the existing `self.sub_tasks` list *after* the `current_sub_task_index`.
   - Ensure `self.current_sub_task_index` is properly maintained so the agent resumes execution seamlessly from the failure point, preserving the historical sequence in memory.

### Symptom B: Lack of Fast-Failing (Stuck State)
**Problem**: Romy doesn't realize she is stuck and burns retries on identical actions until the max iteration timeout, losing the opportunity to capture the exact failure state for training.

**Proposed Solution: Fast-Fail to Memory Pipeline**
1. **File to modify**: `client/agent.py` (add `TRAINING_NEEDED` to `AgentState` enum, update transition logic)
2. **Logic Flow**:
   - Add `TRAINING_NEEDED` as a distinct state in `AgentState`.
   - Implement an 'Action Hash' history in the orchestrator to detect repetitive failing loops (e.g., trying to click the same ID 3 times in a row without state change).
   - Once a loop is detected, or if the LLM explicitly returns a `TRAINING_NEEDED` action (or `ERROR`), immediately break the iteration and transition to `TRAINING_NEEDED`.
   - In the `TRAINING_NEEDED` state block:
     - Take a final snapshot of the DOM and screenshot.
     - Push a structured error payload to Firestore (`update_task_session` or similar) containing the goal, the failed sub-task, the action history, and the visual context.
     - Transition to `SUSPENDED_HITL` (Human-in-the-Loop) to await SOP Studio intervention, allowing the user to inject a semantic rule.

---
**Summary**: These architectural changes shift the paradigm from "blind persistence" to "agile verification and fast-failing." By fixing the physical timeouts and preserving cognitive state, Romy will run faster, fail gracefully, and seamlessly hand off context to the Memory Manager for continuous learning.