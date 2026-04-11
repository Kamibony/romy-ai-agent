# Phase 3 Architecture Proposal: Live Chrome Execution Bridge

## Overview
The goal of Phase 3 is to establish a robust, bi-directional communication bridge between the Python Agent (`AgentStateMachine`) and the live Chrome Extension. This replaces the `MockExtensionBridge` and enables live DOM state capture and command execution.

## 1. Codebase Analysis Summary

### Chrome Extension (`extension/`)
- **`service_worker.js`**: Already contains logic for a local WebSocket bridge (`ws://127.0.0.1:8765`), dynamic intent routing, `chrome.debugger` (CDP) attachment for taking pure screenshots, dispatching native events (`CLICK`, `TYPE`), and injecting `dom_mapper.js`. It explicitly chunks Base64 data over WebSocket to avoid payload limitations.
- **`dom_mapper.js`**: Contains a sophisticated DOM extraction logic (`extractUIElements`) that gathers semantic attributes, computes spatial bounds, deduplicates structural noise, and applies an aggressive A11y extraction.
- **`utils/api.js`**: Currently holds generic backend API references.

### Python Backend (`client/agent.py`)
- The `AgentStateMachine` relies heavily on an injected `bridge` dependency via `delegate_command(payload, timeout)`.
- When `intent == "WEB"`, it asks the bridge for `GET_STATE` to fetch `screenshot_base64`, `ui_elements`, `url`, etc., and uses `EXECUTE_ACTION` to send commands back.
- Currently, it utilizes `MockExtensionBridge` which fakes these responses.

## 2. Gap Analysis & Proposed Approaches

We need a secure, real-time, low-latency conduit. Since the target is a local Python agent orchestrating the browser on the same machine, Localhost communication is the primary vector.

### The Communication Protocol

#### Approach A: Local WebSocket Server (Recommended)
- **Architecture**: The Python client runs a lightweight asynchronous WebSocket server (e.g., using the `websockets` library) on `localhost:8765`. The Chrome Extension's `service_worker.js` connects to this port.
- **Pros**:
  - **Full Duplex**: Both sides can push data at any time (e.g., Python sending commands, Chrome pushing DOM changes or async event notifications).
  - **Code Alignment**: `service_worker.js` already implements a `connectLocalBridge()` function via WebSocket. Adopting this requires minimal extension changes.
  - **Low Latency**: Ideal for the fast ReAct loop.
- **Cons**:
  - Requires maintaining an active WebSocket connection and handling reconnect logic (which `service_worker.js` handles decently, but needs robust server-side handling).

#### Approach B: HTTP Long-Polling / Server-Sent Events (SSE)
- **Architecture**: The Python client exposes a local HTTP server (like it does on port `8764`). Chrome extension polls `/api/commands` continuously or connects to an SSE stream. To send the state, Chrome POSTs to `/api/state`.
- **Pros**:
  - Simpler server implementation. Follows standard REST paradigms.
- **Cons**:
  - SSE is unidirectional (Server -> Client). Chrome still needs to POST state.
  - Long-polling creates overhead and latency. Not ideal for transferring large Base64 screenshots repeatedly.

### Execution Layer

#### Approach A: Extension-Managed CDP (Recommended)
- **Architecture**: The Python client sends intent payloads (`CLICK`, `TYPE`, `target_id`, `coordinates`) to the `service_worker.js`. The Service Worker uses `chrome.debugger` to attach to the target tab and dispatch native CDP commands (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`).
- **Pros**:
  - **Code Alignment**: `service_worker.js` already implements a `CDPLifecycleManager` and handles complex fallback logic (JIT coordinate calculation, scroll discovery, DOM mutations).
  - Avoids Python needing to manage browser executable paths, debugging ports, and WebSocket connection URIs directly via PyChromeDevTools or similar.
- **Cons**:
  - Extension permission `debugger` triggers a persistent warning banner in Chrome ("Romy AI started debugging this browser").

#### Approach B: Python-Managed CDP (Direct)
- **Architecture**: Chrome is launched with `--remote-debugging-port=9222`. The Python client connects directly to this port via WebSockets and sends raw CDP JSON payloads.
- **Pros**:
  - Bypasses the Chrome extension for execution completely. No extension warning banner.
- **Cons**:
  - Forces Python to reimplement all the complex JIT target locating, frame handling, and stability logic currently residing in `service_worker.js`.
  - Violates the current extension-centric architecture.

### Data Contracts

Based on the `AgentStateMachine` and `service_worker.js`, the minimal payloads should be:

**1. Python -> Chrome: Request State (`GET_STATE`)**
```json
{
  "type": "command",
  "payload": {
    "action_type": "GET_STATE",
    "commandText": "Find the cheapest flights to Paris",
    "iteration": 0
  }
}
```

**2. Chrome -> Python: State Response (Chunked Base64)**
```json
{
  "type": "chunk", // or "result" if small enough
  "message_id": "uuid-1234",
  "chunk_index": 0,
  "total_chunks": 5,
  "chunk_data": "base64_encoded_string..." // Decodes to JSON: { success: true, ui_elements: [...], screenshot_base64: "...", url: "...", dpr: 1.0 }
}
```

**3. Python -> Chrome: Execute Command (`EXECUTE_ACTION`)**
```json
{
  "type": "command",
  "payload": {
    "action_type": "EXECUTE_ACTION",
    "action": {
      "action": "CLICK",
      "target_id": "12",
      "coordinates": [450, 300], // Physical pixels from LLM
      "stealth_mode": true
    },
    "iteration": 1
  }
}
```

**4. Chrome -> Python: Command Result**
```json
{
  "type": "result",
  "payload": {
    "success": true,
    "error": null // or string if failed
  }
}
```

## 3. Recommended Path Forward

I recommend **Approach A (Local WebSocket Server)** combined with **Approach A (Extension-Managed CDP)**.

The `service_worker.js` is already heavily engineered to support this exact pattern. It has robust JIT coordinate calculation, DOM stability waiting, and CDP abstraction. By building the Python WebSocket server, we plug directly into the existing extension infrastructure without rewriting complex browser orchestration logic in Python.
