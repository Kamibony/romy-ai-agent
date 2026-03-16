import { API_ENDPOINTS, API_CONFIG } from '../utils/api.js';
import { MESSAGE_TYPES } from '../utils/message_types.js';
import { getAuthToken } from '../utils/auth.js';
// Removed firebase imports because Chrome is now decoupled from Firestore

// Central orchestrator for the Chrome Extension
console.log("Romy Agent Service Worker initialized.");

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

// Local bridge polling to receive commands from the Desktop Agent Orchestrator
let localBridgeInterval = null;

function startLocalBridgePolling() {
    if (localBridgeInterval) return;
    console.log("Starting local bridge polling...");
    localBridgeInterval = setInterval(async () => {
        try {
            const response = await fetch('http://127.0.0.1:8765/command');
            if (response.ok) {
                const cmd = await response.json();
                if (cmd && Object.keys(cmd).length > 0) {
                    console.log("Received command from Python Agent:", cmd);
                    const result = await processCommandInternally(cmd);
                    // Send result back
                    await fetch('http://127.0.0.1:8765/result', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(result)
                    });
                }
            }
        } catch (error) {
            // Silence network errors to avoid spamming the console when Python agent is down
            // console.error("Local bridge polling error:", error);
        }
    }, 2000); // Poll every 2 seconds
}

startLocalBridgePolling();

export function stopLocalBridgePolling() {
    if (localBridgeInterval) {
        clearInterval(localBridgeInterval);
        localBridgeInterval = null;
        console.log("Local bridge polling stopped.");
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

    let iteration = 0;
    let totalActionsExecuted = 0;
    const threadHistory = [];

    while (true) {
        sendTelemetryLog(`Iteration ${iteration + 1}...`);

        // 2. Request DOM Map from Content Script (This also waits for DOM stability via MutationObserver)
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
            thread_history: threadHistory
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

        if (actions.length === 0) {
            sendTelemetryLog(`No actions returned, assuming done.`);
            break;
        }

        // Add actions to history
        threadHistory.push(...actions);
        let hasTerminalAction = false;
        let needsHumanHelp = false;
        let humanHelpReason = "";

        // 4. Execute Actions Sequentially
        for (let i = 0; i < actions.length; i++) {
            const action = actions[i];

            if (action.action === "DONE" || action.action === "ASK_HUMAN" || action.action === "ERROR") {
                hasTerminalAction = true;
                if (action.action === "ASK_HUMAN") {
                    needsHumanHelp = true;
                    humanHelpReason = action.reason || action.text || "Human help needed.";
                }
            }

            if (action.action !== "DONE" && action.action !== "ERROR" && action.action !== "ASK_HUMAN") {
                sendTelemetryLog(`Executing [${i+1}/${actions.length}]: ${action.action} ${action.target_id ? 'target ' + action.target_id : ''}`);

                // Check if action is for OS or Web (Phase 2 integration)
                // if (isOSAction(action)) { ... } else {

                await new Promise((resolve, reject) => {
                    chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.EXECUTE_ACTION, payload: action }, (res) => {
                        if (chrome.runtime.lastError) {
                            console.warn("Execute action error, tab closed?", chrome.runtime.lastError);
                            resolve({error: chrome.runtime.lastError.message});
                        }
                        else if (res && res.error) reject(new Error(res.error));
                        else resolve(res);
                    });
                });
                totalActionsExecuted++;
                // Optional micro-sleep here for DOM stability
                await new Promise(r => setTimeout(r, 500));
            } else {
                sendTelemetryLog(`Received terminal action: ${action.action}${action.action === "ASK_HUMAN" ? " - " + humanHelpReason : ""}`);
            }
        }

        if (hasTerminalAction || iteration > 50) { // Safety break
            if (needsHumanHelp) {
                return { success: false, helpNeeded: true, reason: humanHelpReason, actionsExecuted: totalActionsExecuted };
            }
            break;
        }

        iteration++;
        // The DOM map request at the beginning of the next loop iteration will naturally wait for DOM stability using the MutationObserver.
    }

    sendTelemetryLog(`Execution complete. Total actions: ${totalActionsExecuted}`);
    return { success: true, actionsExecuted: totalActionsExecuted };
}

async function handleProcessCommand(payload, sender, sendResponse) {
    isProcessing = true;
    let finalResult = null;
    try {
        finalResult = await processCommandInternally(payload);
        sendResponse(finalResult);
    } catch (error) {
        console.error("Error processing command:", error);
        let errorMsg = error.message;
        if (error.name === 'AbortError') {
            errorMsg = "Backend request timed out.";
        }
        finalResult = { success: false, error: errorMsg };
        sendResponse(finalResult);
    } finally {
        isProcessing = false;
        chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXECUTION_COMPLETE, result: finalResult }).catch(() => {
            // Popup might be closed, ignore
        });
    }
}
