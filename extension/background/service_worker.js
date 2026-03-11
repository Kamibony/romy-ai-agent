import { API_ENDPOINTS, API_CONFIG } from '../utils/api.js';
import { MESSAGE_TYPES } from '../utils/message_types.js';
import { getAuthToken } from '../utils/auth.js';

// Central orchestrator for the Chrome Extension
console.log("Romy Agent Service Worker initialized.");

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    switch (request.type) {
        case MESSAGE_TYPES.PROCESS_COMMAND:
            handleProcessCommand(request.payload, sender, sendResponse);
            return true; // Keep the message channel open for async response

        // Future OS actions handler (Phase 2)
        // case MESSAGE_TYPES.OS_NATIVE_ACTION:
        //     chrome.runtime.sendNativeMessage('com.romy.nativehost', request.payload, ...);
        //     return true;

        default:
            console.warn(`Unknown message type: ${request.type}`);
    }
});

async function handleProcessCommand(payload, sender, sendResponse) {
    try {
        const { audioBase64, commandText } = payload;

        // 1. Get Active Tab
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab) throw new Error("No active tab found");

        // 2. Request DOM Map from Content Script
        const domMapResponse = await new Promise((resolve, reject) => {
            chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.REQUEST_DOM_MAP }, (response) => {
                if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
                else resolve(response);
            });
        });

        if (domMapResponse.error) throw new Error(domMapResponse.error);
        const uiElements = domMapResponse.elements;

        // 3. Send to Backend
        const token = await getAuthToken();
        if (!token) {
            throw new Error("User is not authenticated. Please log in.");
        }

        const apiPayload = {
            audio_base64: audioBase64,
            command_text: commandText,
            ui_elements: uiElements,
            // Include thread history if needed
        };

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), API_CONFIG.TIMEOUT || 30000);

        let response;
        try {
            response = await fetch(API_ENDPOINTS.COMMAND, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(apiPayload),
                signal: controller.signal
            });
        } finally {
            clearTimeout(timeoutId);
        }

        if (!response.ok) throw new Error(`Backend error: ${response.status}`);
        const actions = await response.json(); // Expected JSON array of actions

        // 4. Execute Actions Sequentially
        for (const action of actions) {
            // Check if action is for OS or Web (Phase 2 integration)
            // if (isOSAction(action)) { ... } else {

            await new Promise((resolve, reject) => {
                chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.EXECUTE_ACTION, payload: action }, (res) => {
                     if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
                     else if (res && res.error) reject(new Error(res.error));
                     else resolve(res);
                });
            });
            // Optional micro-sleep here for DOM stability
            await new Promise(r => setTimeout(r, 500));
        }

        sendResponse({ success: true, actionsExecuted: actions.length });

    } catch (error) {
        console.error("Error processing command:", error);
        let errorMsg = error.message;
        if (error.name === 'AbortError') {
            errorMsg = "Backend request timed out.";
        }
        sendResponse({ success: false, error: errorMsg });
    }
}
