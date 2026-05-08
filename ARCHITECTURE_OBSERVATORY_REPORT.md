# Romy AI: System Architecture & Operations Report
**Prepared for: The Scientific Observatory**
**Date:** May 2026

This document provides an objective, deeply technical, and strictly factual analysis of the current Romy AI system architecture. It specifically maps the live capabilities of the repository against the foundational requirements of the "Scientific Observatory," including black-box telemetry, human-in-the-loop (HITL) interventions, semantic healing, and academic compliance.

---

## 1. High-Level Topology

The current system operates on a Push/Pull Multi-Agent State Graph, distributed across four distinct planes:

1. **FastAPI Cloud Backend (`backend/main.py`):** Acts as the central nervous system, managing state memory (Firestore & ChromaDB) and exposing AI reasoning endpoints. It utilizes `run_in_threadpool` to prevent ASGI event loop starvation during intensive Gemini API operations and database transactions.
2. **Python Client Daemon (`client/agent.py`):** A background worker running locally that pulls chained mission blocks via a REST polling loop (`_poll_sessions_loop`). It executes the core `AgentStateMachine` to drive intent and route actions.
3. **MV3 Chrome Extension:** Operates the perception layer using a Split-Plane Bridge. Control signals are transmitted via WebSockets (`ws://127.0.0.1:8765`), while large data payloads (Base64 DOM screenshots) bypass V8 limits using an asynchronous HTTP POST fallback (`http://127.0.0.1:8764/api/state`). Actions are executed natively via the Chrome DevTools Protocol (CDP).
4. **Flutter Dashboard:** The visual mission command and control center, communicating purely via REST with the backend, dynamic mapping environment ports to eliminate hardcoding.

---

## 2. The "Scientific Observatory" (Telemetry & Compliance)

To answer the core stakeholder question: *Yes, the system is actively capturing fixes and interventions during failures.*

### Black Box Telemetry (Flight Records)
The `save_flight_record` function in `client/agent.py` establishes the reality of the Observatory's data ingestion. Rather than abstracting state, the system forcefully saves a hard copy of every ReAct cycle execution loop.

These "Flight Records" are persisted locally at `RomyAgentBrowserData/flight_records/<doc_id>/` and include:
- `timestamp` and iteration counts.
- `system_state`: A highly detailed snapshot of the DOM capture (`ui_elements`) via hierarchical semantic weighting, allowing the system to observe non-interactive data nodes.
- `prompt_payload`: The exact instructions sent to the LLM.
- `llm_response`: The raw AI decision vector.
- `action_executed`: The exact native CDP action taken (or attempted).
- `screenshot_<iteration>_<timestamp>.png`: Base64 decoded frame buffers of the physical screen state at the moment of execution.

### Compliance: EU AI Act 2026 (PII Masking)
Before any execution state or telemetry is pushed out of the local OS environment, it traverses the `client/telemetry/masking.py` module.
The system relies on an active `mask_dict_pii` recursive parser to proactively sanitize data based on regex patterns before transmission. Specifically, it scrubs:
- Email Addresses (`[REDACTED_EMAIL]`)
- Social Security Numbers (`[REDACTED_SSN]`)
- Credit Card sequences (`[REDACTED_CC]`)
- Phone Numbers (`[REDACTED_PHONE]`)

---

## 3. Auto-Curriculum & Human-In-The-Loop (HITL)

When an interaction fails or standard Standard Operating Procedures (SOPs) are exhausted, the agent enters a strict failure hierarchy.

### The Circuit Breaker & `SUSPENDED_HITL`
If an action natively fails (e.g., CDP cannot find coordinates) three times (`max_sub_task_iterations = 3`), the `AgentStateMachine` trips a circuit breaker. Instead of looping infinitely or halting silently, it transitions the agent into the `SUSPENDED_HITL` state.

### Capturing Interventions (Ghost Clicks)
While in `SUSPENDED_HITL`, the system exposes a webhook to the Flutter Dashboard. An academic or operator provides a "Ghost Click" (a manual override indicating the correct UI element or coordinate).
The Python Daemon wakes up via `hitl_event.wait()` and intercepts this interaction. If the intent was physical (e.g., a missing button), it executes the CDP click natively. If the intent was observation (`EXTRACT_DATA`), it logs the semantic location without mutating the DOM.

### The Synthesizer Agent
The capture of the fix is not merely logged; it is dynamically synthesized into a new capability. When a Ghost Click occurs, the daemon builds a telemetry package containing the `failed_sub_task` and the human intervention, and sends it to the `Synthesizer Agent` (`synthesize_playbook_rule_with_gemini` in `backend/ai_service.py`).
This agent analyzes the human correction and extracts a universal "Playbook Rule" (an SOP). This rule is permanently saved into ChromaDB. Future executions of this sub-task will pull this new SOP automatically, bypassing the previous failure—this is the realization of the Auto-Curriculum.

---

## 4. Semantic Self-Healing Architecture

Before defaulting to HITL, the system implements an intermediary defense layer: Semantic Self-Healing.

When a sub-task fails because a UI element has shifted (stale selector), the `AgentStateMachine` transitions into a `SELF_HEALING` state and invokes the `rescue_element_with_gemini` endpoint.
This function (defined in `backend/ai_service.py` and routed via FastAPI) acts as a specialized rescue prompt. It accepts the `failed_selector`, the `intent` of the action, and a fresh snippet of the current DOM. Gemini is tasked strictly with determining the *new* target location or selector based on the updated DOM state. If successful, the agent dynamically self-corrects and resumes the mission autonomously, logging the recovery in the telemetry pipeline.

---

## 5. Data Pipeline & Academic Export Roadmap

**Current State:**
All observability data is currently localized as JSON payloads (`flight_records`) and asynchronous background events sent to the FastAPI telemetry queue (`queue_worker.py`), eventually persisting in Google Firestore as document trees.

**Roadmap to Academic Export (`.sav` / R):**
To fulfill the requirement for SPSS and R integration, a dedicated parsing pipeline must be engineered.
1. **Extraction:** A chron job or manual dashboard trigger will need to query the Firestore `telemetry_logs` collection to pull the nested JSON ReAct logs.
2. **Flattening:** The hierarchical data (DOM states, arrays of AI responses) must be mapped to a tabular statistical format (rows as discrete iterations, columns as defined execution variables and HITL states).
3. **Export Integration:** A new Python backend module leveraging the `pyreadstat` library will be required to write the flattened Pandas DataFrames natively into SPSS `.sav` binaries. This module will also generate the automated codebooks (variable labels and value maps) required by the Observatory, bridging the gap between JSON event streams and academic statistical engines.
