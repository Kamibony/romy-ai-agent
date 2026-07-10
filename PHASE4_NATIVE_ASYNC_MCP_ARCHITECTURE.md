# Romy AI: Phase 4 Native Async & MCP Architecture

## 1. Executive Summary
This document proposes a systemic architectural upgrade for the Romy AI Agent ecosystem, advancing from the Phase 2/3 monolithic and blocking `AgentStateMachine` towards a fully decentralized, non-blocking Multi-Agent System (MAS). By leveraging Google Vertex AI's new native Asynchronous Execution and the Model Context Protocol (MCP), we eliminate synchronous HTTP timeouts, offload heavy cognitive tasks (e.g., visual SoM parsing, self-healing), and establish a robust, native communication bridge between the OS-level actuators and the cloud reasoning engine.

## 2. Async Self-Healing Pattern (Non-Blocking Loop)

### Current Limitation:
The `AgentStateMachine` in `client/agent.py` relies on blocking synchronous REST API calls (e.g., POST to `GET_COMMAND_ENDPOINT` with up to 120s timeout) to evaluate state and calculate self-healing coordinates. This stalls the local event loop and causes "The 'Wait and See' Delay".

### Proposed Architecture:
We will redesign the state machine to use an **Event-Driven Asynchronous Pipeline** backed by Vertex AI's `background: true` task execution and Firestore real-time listeners.

1.  **State Extraction (Local):** `client/agent.py` or the Chrome Extension extracts the local DOM/Screenshot state.
2.  **Async Task Dispatch:** Instead of blocking HTTP `POST` to get the next action, the client writes the current state payload directly to a Firestore document (e.g., `remote_commands/{doc_id}/state_updates/{update_id}`).
3.  **Cloud-Side Trigger:** A Google Cloud Function (or Cloud Run event listener) detects the Firestore write and dispatches a background task to Vertex AI Gemini via its native async API (`background: true`).
4.  **Local Non-Blocking Yield:** The local `AgentStateMachine` enters an `AWAITING_COGNITION` idle state. It dynamically yields CPU using `asyncio.sleep()` or processes other background tasks (like FFmpeg telemetry recording).
5.  **Cognitive Resolution:** Vertex AI processes the heavy visual reasoning, DOM parsing, or self-healing fallback logic asynchronously. Upon completion, the backend writes the resultant `actions_to_execute` back to the Firestore `remote_commands` document.
6.  **Callback Execution:** The local client, subscribed to the Firestore document via real-time listeners (`@firestore.on_snapshot`), instantly detects the update, transitions back to `ACTING`, and executes the actions deterministically via CDP or OS tools.

*Benefit:* Eliminates local thread starvation, bypasses API timeouts for heavy image processing, and drastically improves the perceived responsiveness of the local agent daemon.

## 3. MCP Tooling Bridge (Native Capabilities)

### Current Limitation:
Romy currently relies on a custom "Action JSON Protocol" where the LLM responds with custom JSON payloads (`{action: "CLICK", target_id: "..."}`), requiring extensive manual validation and error handling in `client/agent.py`.

### Proposed Architecture:
We will expose the local Romy capabilities (Web CDP manipulation, OS native interactions, File system access, FFmpeg triggers) natively via the **Model Context Protocol (MCP)**.

1.  **Local MCP Server Implementation:** Restructure the local Python daemon (`client/agent.py`) to run a standardized MCP Server. This server defines exact schemas for tools like `dispatch_cdp_click(x, y)`, `execute_os_type(text)`, or `trigger_ffmpeg_recording()`.
2.  **Bypassing the NAT Boundary (SSE Outbound Bridge):** Because the cloud Vertex AI engine cannot initiate inbound connections to a local developer machine (`127.0.0.1`), the local Romy MCP Server will establish an **outbound Server-Sent Events (SSE) connection** to the backend Cloud Run orchestration layer.
3.  **Native Gemini Tool Calling:** The Cloud Run backend proxies this SSE connection to Vertex AI. Vertex AI Gemini natively connects to the MCP session. When Gemini decides to act, it invokes the tool natively. The invocation flows down the SSE tunnel, and the local Romy MCP server executes the physical actuation and streams the result back.

*Benefit:* Removes custom LLM JSON parsing logic. Gemini fundamentally "understands" the tools available. The SSE architecture perfectly solves the NAT firewall restriction without requiring complex proxy middleware.

## 4. MAS Delegation (Planner-Worker Workflow)

### Current Limitation:
The current `MissionOrchestrator` executes DAG nodes linearly. Complex cognitive workflows bottleneck because the primary agent must wait for intermediate context extraction.

### Proposed Architecture:
Transition Romy from a singular loop into a **Hierarchical Planner-Worker Multi-Agent System**.

1.  **The Planner (Romy-Orchestrator):** The primary `AgentStateMachine` becomes the "Planner". It maintains the global context, reads the user intent, and breaks the mission into independent sub-tasks.
2.  **Asynchronous Dispatch:** When encountering parallelizable or deep-cognitive tasks (e.g., "Scan these 5 invoice pages and extract totals", "Monitor this changing DOM for a specific success banner"), the Planner creates specialized "Worker" tasks in Firestore.
3.  **Background Workers (Vertex AI Agents):** Specialized Vertex AI Agents (e.g., `Romy-Data-Extractor`, `Romy-Visual-Critic`) pick up these tasks via Cloud Run event triggers. They operate completely asynchronously in the background.
4.  **Context Synchronization:** As Workers complete their tasks, they write structured outputs (via MCP tools) back to a shared "Blackboard" in Firestore (the `MissionGraph` context state).
5.  **Planner Resumption:** The Planner observes the Blackboard. Once required prerequisite data appears, the Planner synthesizes the results and proceeds with physical OS/Web execution.

*Benefit:* True concurrent processing. Heavy data extraction no longer blocks physical UI navigation, aligning precisely with Google's native MAS design patterns.

## 5. Google-Native CI/CD & Deployment Alignment

### Current Infrastructure Review:
The project strictly uses GitHub Actions (`.github/workflows/deploy-backend.yml`), Google Cloud Run, Workload Identity Federation, and Firebase.

### Required Architecture Updates for Phase 4:
1.  **Vertex AI Model Registry CI/CD:** Add steps in `.github/workflows/deploy-backend.yml` to automatically register, version, and deploy updated Gemini Prompts/Tools configurations directly to the Vertex AI Model Registry, ensuring environment consistency.
2.  **Firestore Indexing for Async State:** The new async pipeline requires complex querying (e.g., finding pending background tasks for a specific `session_id`). Ensure `firestore.indexes.json` is updated and deployed via Firebase CLI (`firebase deploy --only firestore:indexes`) in the CI pipeline.
3.  **Cloud Functions/Eventarc Deployment:** If using Cloud Functions or Eventarc to trigger background Vertex AI workers upon Firestore writes, add infrastructure-as-code (e.g., Terraform or `gcloud` deploy scripts) to the existing GitHub Actions to manage these event triggers securely using the existing Workload Identity Federation (`github-provider-v2`).
4.  **Security Posture:** Ensure the SSE MCP bridge authenticates securely using the existing Google IAM service accounts (`github-actions@romy-ai-agent.iam.gserviceaccount.com`) configured in the CI pipeline.

*Benefit:* Maintains strict adherence to the Google Cloud / Vertex AI ecosystem while fully automating the deployment of the new asynchronous components without fragmenting the tech stack.
