import { API_ENDPOINTS, API_CONFIG } from '../utils/api.js';
import { MESSAGE_TYPES } from '../utils/message_types.js';
import { getAuthToken } from '../utils/auth.js';
import { db, collection, query, where, onSnapshot, doc, updateDoc } from '../utils/firebase-init.js';

// Central orchestrator for the Chrome Extension
console.log("Romy Agent Service Worker initialized.");

let isListeningToRemoteCommands = false;
let remoteCommandUnsubscribe = null;
const processedCommandIds = new Set();

let isRecording = false;
let isProcessing = false;

async function setupOffscreenDocument(path) {
    if (await chrome.offscreen.hasDocument()) return;
    await chrome.offscreen.createDocument({
        url: path,
        reasons: ['USER_MEDIA', 'DOM_PARSER'],
        justification: 'Recording audio and coordinating continuous DOM structural processing'
    });
}

// Initialize the remote listener immediately if token is available
async function initRemoteListener() {
    const token = await getAuthToken();
    if (token) {
        startRemoteListener();
    }
}
initRemoteListener();

export async function startRemoteListener() {
    const token = await getAuthToken();
    if (!token) {
        console.warn("Attempted to start remote listener without auth token.");
        return;
    }

    if (isListeningToRemoteCommands) {
        console.log("Remote listener already running.");
        return;
    }

    try {
        console.log("Starting remote command listener...");
        const q = query(collection(db, "remote_commands"), where("status", "==", "pending"));

        remoteCommandUnsubscribe = onSnapshot(q, (snapshot) => {
            snapshot.docChanges().forEach(async (change) => {
                if (change.type === "added") {
                    const data = change.doc.data();
                    const docId = change.doc.id;
                    const commandText = data.command || "";
                    const audioBase64 = data.audio_b64 || "";

                    if (processedCommandIds.has(docId)) {
                        console.log(`Command ${docId} already processed. Skipping to prevent double execution.`);
                        return;
                    }

                    processedCommandIds.add(docId);
                    if (processedCommandIds.size > 50) {
                        const iterator = processedCommandIds.values();
                        processedCommandIds.delete(iterator.next().value);
                    }

                    console.log(`Received new remote command: "${commandText}" (ID: ${docId}, has audio: ${!!audioBase64})`);

                    // Mark as in_progress immediately
                    const docRef = doc(db, "remote_commands", docId);
                    await updateDoc(docRef, { status: "in_progress" });

                    // Execute command
                    try {
                        const payload = { audioBase64: audioBase64, commandText: commandText };
                        const result = await processCommandInternally(payload);

                        if (result.success) {
                            await updateDoc(docRef, { status: "completed" });
                            console.log(`Remote command ${docId} completed successfully.`);
                        } else {
                            await updateDoc(docRef, { status: "failed", error: result.error });
                            console.log(`Remote command ${docId} failed: ${result.error}`);
                        }
                    } catch (error) {
                        await updateDoc(docRef, { status: "failed", error: error.message });
                        console.error(`Remote command ${docId} failed with exception:`, error);
                    }
                }
            });
        });

        isListeningToRemoteCommands = true;
    } catch (error) {
        console.error("Failed to start remote listener:", error);
    }
}

export function stopRemoteListener() {
    if (remoteCommandUnsubscribe) {
        remoteCommandUnsubscribe();
        remoteCommandUnsubscribe = null;
        isListeningToRemoteCommands = false;
        console.log("Remote command listener stopped.");
    }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    switch (request.type) {
        case MESSAGE_TYPES.PROCESS_COMMAND:
            handleProcessCommand(request.payload, sender, sendResponse);
            return true; // Keep the message channel open for async response

        case MESSAGE_TYPES.REQUEST_START_RECORDING:
            handleStartRecording(sendResponse);
            return true;

        case MESSAGE_TYPES.REQUEST_STOP_RECORDING:
            handleStopRecording(sendResponse);
            return true;

        case MESSAGE_TYPES.GET_STATE:
            sendResponse({ isRecording, isProcessing });
            return false;

        // Future OS actions handler (Phase 2)
        // case MESSAGE_TYPES.OS_NATIVE_ACTION:
        //     chrome.runtime.sendNativeMessage('com.romy.nativehost', request.payload, ...);
        //     return true;

        default:
            console.warn(`Unknown message type: ${request.type}`);
    }
});

async function handleStartRecording(sendResponse) {
    if (isRecording) {
        sendResponse({ error: "Already recording" });
        return;
    }

    try {
        await setupOffscreenDocument('../offscreen/offscreen.html');
        const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.START_RECORDING });
        if (response && response.error) {
            throw new Error(response.error);
        }
        isRecording = true;
        sendResponse({ success: true });
    } catch (err) {
        console.error("Failed to start recording:", err);
        isRecording = false;
        sendResponse({ error: err.message });
    }
}

async function handleStopRecording(sendResponse) {
    if (!isRecording) {
        sendResponse({ error: "Not recording" });
        return;
    }

    try {
        const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.STOP_RECORDING });
        if (response && response.error) {
            throw new Error(response.error);
        }
        isRecording = false;

        const base64Audio = response.audioBase64;
        sendResponse({ audioBase64: base64Audio });

        if (base64Audio) {
            // Initiate command processing autonomously
            handleProcessCommand({ audioBase64: base64Audio, commandText: "" }, null, () => {});
        }
    } catch (err) {
        console.error("Failed to stop recording:", err);
        isRecording = false;
        sendResponse({ error: err.message });
    }
}

// Helper to send telemetry logs to the popup
function sendTelemetryLog(message) {
    console.log(`[Telemetry] ${message}`);
    chrome.runtime.sendMessage({ type: MESSAGE_TYPES.TELEMETRY_LOG, payload: message }).catch(() => {
        // Popup might be closed, ignore
    });
}

async function processCommandInternally(payload) {
    const { audioBase64, commandText } = payload;

    sendTelemetryLog(`Starting command processing...`);

    // 1. Get Active Tab (Fallback strategy to ensure we grab the right tab even if focus shifts)
    let [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab) {
        [tab] = await chrome.tabs.query({ active: true });
    }
    if (!tab) {
        sendTelemetryLog(`Error: No active tab found.`);
        throw new Error("No active tab found");
    }

    sendTelemetryLog(`Target tab identified: ${tab.title || tab.id}`);

    // 2. Request DOM Map from Content Script
    sendTelemetryLog(`Extracting DOM from tab...`);
    const domMapResponse = await new Promise((resolve, reject) => {
        chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.REQUEST_DOM_MAP }, (response) => {
            if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
            else resolve(response);
        });
    });

    if (domMapResponse.error) {
        sendTelemetryLog(`Error extracting DOM: ${domMapResponse.error}`);
        throw new Error(domMapResponse.error);
    }
    const uiElements = domMapResponse.elements;
    sendTelemetryLog(`Extracted ${uiElements.length} elements from DOM.`);

    // 3. Send to Backend
    sendTelemetryLog(`Sending payload to Backend...`);
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

    if (!response.ok) {
        sendTelemetryLog(`Error from Backend: ${response.status}`);
        throw new Error(`Backend error: ${response.status}`);
    }
    const actions = await response.json(); // Expected JSON array of actions
    sendTelemetryLog(`Received ${actions.length} action(s) from Backend.`);

    // 4. Execute Actions Sequentially
    for (let i = 0; i < actions.length; i++) {
        const action = actions[i];
        sendTelemetryLog(`Executing [${i+1}/${actions.length}]: ${action.action} ${action.target_id ? 'target ' + action.target_id : ''}`);

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

    sendTelemetryLog(`Execution complete.`);
    return { success: true, actionsExecuted: actions.length };
}

async function handleProcessCommand(payload, sender, sendResponse) {
    isProcessing = true;
    try {
        const result = await processCommandInternally(payload);
        sendResponse(result);
    } catch (error) {
        console.error("Error processing command:", error);
        let errorMsg = error.message;
        if (error.name === 'AbortError') {
            errorMsg = "Backend request timed out.";
        }
        sendResponse({ success: false, error: errorMsg });
    } finally {
        isProcessing = false;
        chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXECUTION_COMPLETE }).catch(() => {
            // Popup might be closed, ignore
        });
    }
}
