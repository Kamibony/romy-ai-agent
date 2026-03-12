import { API_ENDPOINTS, API_CONFIG } from '../utils/api.js';
import { MESSAGE_TYPES } from '../utils/message_types.js';
import { getAuthToken, app } from '../utils/auth.js';
import { getFirestore, collection, query, where, onSnapshot, doc, updateDoc } from '../utils/firebase-firestore.js';

// Central orchestrator for the Chrome Extension
console.log("Romy Agent Service Worker initialized.");

// Initialize Firestore
const db = getFirestore(app);
let isListeningToRemoteCommands = false;
let remoteCommandUnsubscribe = null;

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
                    const commandText = data.command;

                    console.log(`Received new remote command: "${commandText}" (ID: ${docId})`);

                    // Mark as in_progress immediately
                    const docRef = doc(db, "remote_commands", docId);
                    await updateDoc(docRef, { status: "in_progress" });

                    // Execute command
                    try {
                        const payload = { audioBase64: "", commandText: commandText };
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

        // Future OS actions handler (Phase 2)
        // case MESSAGE_TYPES.OS_NATIVE_ACTION:
        //     chrome.runtime.sendNativeMessage('com.romy.nativehost', request.payload, ...);
        //     return true;

        default:
            console.warn(`Unknown message type: ${request.type}`);
    }
});

async function processCommandInternally(payload) {
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

    return { success: true, actionsExecuted: actions.length };
}

async function handleProcessCommand(payload, sender, sendResponse) {
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
    }
}
