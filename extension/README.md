# Architectural Proposal: Hybrid RPA System - Phase 1 (Web Module)

## Folder Structure

```text
extension/
├── manifest.json              # Extension configuration (Manifest V3)
├── background/
│   └── service_worker.js      # Orchestrator, Auth management, API communication, Native messaging
├── content/
│   ├── dom_mapper.js          # Injects `data-romy-id` and extracts structural representation
│   └── content_script.js      # Listens to background commands, executes DOM interactions
├── popup/
│   ├── popup.html             # User interface for voice capture and status
│   ├── popup.css              # Styling for popup
│   └── popup.js               # Handles UI events, voice recording, and sends messages to background
├── utils/
│   ├── api.js                 # Helper functions for Backend API communication
│   ├── auth.js                # Helper functions for Firebase Auth token management
│   └── message_types.js       # Constants for internal message passing to ensure consistency
└── assets/
    └── icons/                 # Extension icons
```

## Component Responsibilities
- **Popup (`popup/popup.*`)**: The user-facing interface. Handles capturing voice input (via MediaRecorder API), displaying agent status (recording, processing, executing), and sending raw audio/text data to the background service worker.
- **Background Service Worker (`background/service_worker.js`)**: The central brain. Manages state (Firebase Auth tokens), handles communication with the LLM backend (routing commands), receives action JSON arrays from the backend, and orchestrates execution by passing specific commands to the active tab's content script. In Phase 2, this will also route OS-level tasks via `chrome.runtime.sendNativeMessage`.
- **Content Scripts (`content/*`)**: The hands and eyes. `dom_mapper.js` parses the current page, injecting `data-romy-id` attributes and building the UI element array. `content_script.js` receives actions (CLICK, TYPE, SCROLL) from the background script and executes them natively in the DOM using the `data-romy-id` locators.

## Data Flow: Voice Capture to DOM Interaction

1. **Voice Capture (Popup)**: User clicks "Record" in `popup.html`. `popup.js` captures audio via `MediaRecorder`. Upon stop, it converts the audio to Base64 and sends a `PROCESS_COMMAND` message to the `service_worker.js`.
2. **DOM Extraction (Content Script)**: Before hitting the backend, the `service_worker.js` sends a `REQUEST_DOM_MAP` message to the active tab's `content_script.js`. The content script executes `dom_mapper.js`, maps the UI, injects `data-romy-id` tags, and returns the structural UI JSON array to the background worker.
3. **Backend Communication (Background Worker)**: The `service_worker.js` combines the Base64 audio, the structural UI JSON array, and the Auth Token, and sends a POST request to the backend `/api/v1/agent/command` endpoint.
4. **Action Routing (Background Worker)**: The backend responds with a JSON array of actions (e.g., `[{action: "CLICK", target_id: "...", ...}]`). The `service_worker.js` iterates through these actions. If the action is web-based, it sends an `EXECUTE_ACTION` message to the `content_script.js`. (In Phase 2, if it's an OS action, it uses `sendNativeMessage`).
5. **DOM Interaction (Content Script)**: The `content_script.js` receives the `EXECUTE_ACTION` message, locates the element using `document.querySelector('[data-romy-id="..."]')`, and natively dispatches the required event (click, input, scroll). It returns the execution status to the background worker to proceed to the next step.
