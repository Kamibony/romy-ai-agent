import { API_ENDPOINTS, API_CONFIG } from '../utils/api.js';
import { MESSAGE_TYPES } from '../utils/message_types.js';
import { getAuthToken } from '../utils/auth.js';
// Removed firebase imports because Chrome is now decoupled from Firestore

// Central orchestrator for the Chrome Extension
console.log("Romy Agent Service Worker initialized.");

function generateId() {
    return Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
}

async function sendChunkedMessage(ws, type, payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        console.error("WebSocket not open. Cannot send chunked message.");
        return;
    }

    const messageStr = JSON.stringify({ type, payload });
    const chunkSize = 128 * 1024; // 128KB chunks
    const totalChunks = Math.ceil(messageStr.length / chunkSize);
    const messageId = generateId();

    for (let i = 0; i < totalChunks; i++) {
        const start = i * chunkSize;
        const end = Math.min(start + chunkSize, messageStr.length);
        const chunk = messageStr.substring(start, end);

        const chunkMsg = JSON.stringify({
            type: 'chunk',
            message_id: messageId,
            chunk_index: i,
            total_chunks: totalChunks,
            data: chunk
        });

        ws.send(chunkMsg);

        // Yield to the event loop occasionally to avoid blocking the thread or flooding the socket buffer
        if (i % 10 === 0) {
            await new Promise(resolve => setTimeout(resolve, 1));
        }
    }
}

let isRecording = false;
let isProcessing = false;
let activeSessionTabId = null;

async function setupOffscreenDocument(path) {
    if (await chrome.offscreen.hasDocument()) return;
    await chrome.offscreen.createDocument({
        url: path,
        reasons: ['USER_MEDIA', 'DOM_PARSER'],
        justification: 'Recording audio and coordinating continuous DOM structural processing'
    });
}

// Local bridge WebSocket to receive commands from the Desktop Agent Orchestrator
let localBridgeWs = null;
let reconnectTimeout = null;
let reconnectAttempts = 0;
let isConnecting = false;
let heartbeatInterval = null;

function connectLocalBridge() {
    if (localBridgeWs || isConnecting) {
        return;
    }

    isConnecting = true;
    console.log(`Connecting to local bridge via WebSocket... (Attempt ${reconnectAttempts + 1})`);
    try {
        localBridgeWs = new WebSocket('ws://127.0.0.1:8765');

        localBridgeWs.onopen = () => {
            isConnecting = false;
            console.log("WebSocket connected to local bridge.");
            reconnectAttempts = 0; // Reset counter on successful connection
            if (reconnectTimeout) {
                clearTimeout(reconnectTimeout);
                reconnectTimeout = null;
            }

            // Start heartbeat to keep connection alive
            if (heartbeatInterval) clearInterval(heartbeatInterval);
            heartbeatInterval = setInterval(() => {
                if (localBridgeWs && localBridgeWs.readyState === WebSocket.OPEN) {
                    localBridgeWs.send(JSON.stringify({ type: 'ping' }));
                }
            }, 10000); // 10 seconds
        };

        localBridgeWs.onmessage = async (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'pong') {
                    // Definitively keep Service Worker V3 alive
                    chrome.runtime.getPlatformInfo(() => { /* dummy callback */ });
                } else if (msg.type === 'command') {
                    const cmd = msg.payload;
                    console.log("Received command from Python Agent:", cmd);
                    let result;
                    try {
                        if (cmd.action_type === 'GET_STATE') {
                            result = await handleGetState(cmd);
                            // Send via HTTP POST
                            try {
                                const response = await fetch('http://127.0.0.1:8766/api/state', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify(result)
                                });
                                if (!response.ok) {
                                    throw new Error(`HTTP Error: ${response.status}`);
                                }
                            } catch (httpErr) {
                                console.error("HTTP State Transfer failed, falling back to WebSocket chunking:", httpErr);
                                await sendChunkedMessage(localBridgeWs, 'result', result);
                            }
                        } else if (cmd.action_type === 'EXECUTE_ACTION') {
                            result = await handleExecuteNativeAction(cmd);
                            await sendChunkedMessage(localBridgeWs, 'result', result);
                        } else {
                            result = { success: false, error: "Unknown action_type." };
                            await sendChunkedMessage(localBridgeWs, 'result', result);
                        }
                    } catch (err) {
                        console.error("Error processing command internally:", err);
                        result = { success: false, error: err.message || String(err) };
                        // Even if it failed, we must return the result via WebSocket or HTTP so Python doesn't hang
                        if (cmd.action_type === 'GET_STATE') {
                             try {
                                await fetch('http://127.0.0.1:8766/api/state', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify(result)
                                });
                             } catch(e) {
                                await sendChunkedMessage(localBridgeWs, 'result', result);
                             }
                        } else {
                            await sendChunkedMessage(localBridgeWs, 'result', result);
                        }
                    }
                }
            } catch (err) {
                console.error("Error handling WebSocket message:", err);
            }
        };

        localBridgeWs.onclose = () => {
            isConnecting = false;
            localBridgeWs = null;
            if (heartbeatInterval) clearInterval(heartbeatInterval);
            reconnectAttempts++;
            // Exponential backoff, max 30 seconds
            const backoff = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
            console.log(`WebSocket connection closed. Reconnecting in ${backoff}ms...`);
            reconnectTimeout = setTimeout(connectLocalBridge, backoff);
        };

        localBridgeWs.onerror = (error) => {
            // Silence network errors to avoid spamming the console when Python agent is down
            isConnecting = false;
            if (localBridgeWs) {
                localBridgeWs.close(); // Force close to trigger reconnect
            }
        };
    } catch (e) {
        isConnecting = false;
        console.error("Error setting up WebSocket:", e);
        reconnectAttempts++;
        const backoff = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
        reconnectTimeout = setTimeout(connectLocalBridge, backoff);
    }
}

connectLocalBridge();

export function disconnectLocalBridge() {
    if (localBridgeWs) {
        localBridgeWs.close();
        localBridgeWs = null;
    }
    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    switch (request.type) {
        case MESSAGE_TYPES.REQUEST_START_RECORDING:
            handleStartRecording(sendResponse);
            return true;

        case MESSAGE_TYPES.REQUEST_STOP_RECORDING:
            handleStopRecording(sendResponse);
            return true;

        case MESSAGE_TYPES.GET_STATE:
            sendResponse({ isRecording, isProcessing });
            return false;

        case MESSAGE_TYPES.TELEMETRY_LOG:
            // Explicitly handle TELEMETRY_LOG sent from background script itself or other contexts
            // so we don't trigger the "Unknown message type" warning
            return false;

        case MESSAGE_TYPES.HUMAN_CLICK_INTERCEPTED:
            handleGhostClick(request.payload);
            return false;

        // Future OS actions handler (Phase 2)
        // case MESSAGE_TYPES.OS_NATIVE_ACTION:
        //     chrome.runtime.sendNativeMessage('com.romy.nativehost', request.payload, ...);
        //     return true;

        default:
            console.warn(`Unknown message type: ${request.type}`);
    }
});

function handleGhostClick(payload) {
    sendTelemetryLog(`Forwarding ghost click to local agent: ${payload.xpath}`);
    fetch('http://127.0.0.1:8764/api/human_guidance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).catch(err => {
        console.error("Failed to forward ghost click to local agent:", err);
    });
}

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
    } catch (err) {
        console.error("Failed to stop recording:", err);
        isRecording = false;
        sendResponse({ error: err.message });
    }
}

// Helper to send telemetry logs to the popup and local bridge
function sendTelemetryLog(message) {
    console.log(`[Telemetry] ${message}`);
    chrome.runtime.sendMessage({ type: MESSAGE_TYPES.TELEMETRY_LOG, payload: message }).catch(() => {
        // Popup might be closed, ignore
    });
    // Send to local Python agent to aid debugging and maintain active connection
    if (localBridgeWs && localBridgeWs.readyState === WebSocket.OPEN) {
        sendChunkedMessage(localBridgeWs, 'telemetry', message).catch(err => {
            console.error("Failed to send telemetry chunked:", err);
        });
    }
}

async function handleGetState(payload) {
    const { commandText, iteration } = payload;
    sendTelemetryLog(`Requesting WEB State (Vision-First)... Iteration: ${iteration}`);

    let targetUrl = null;
    if (commandText) {
        const urlRegex = /(?:https?:\/\/)?(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{2,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)/i;
        const urlMatch = commandText.match(urlRegex);
        if (urlMatch) {
            targetUrl = urlMatch[0];
            if (!targetUrl.startsWith('http')) {
                targetUrl = 'https://' + targetUrl;
            }
        }
    }

    let tab = null;

    if (iteration === 0) {
        // Start of a new session: always create a new tab
        const urlToOpen = targetUrl || 'https://www.google.com';
        sendTelemetryLog(`New session. Creating new tab: ${urlToOpen}`);
        tab = await new Promise((resolve, reject) => {
            chrome.tabs.create({ url: urlToOpen }, (newTab) => {
                if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
                const listener = (tabId, info) => {
                    if (tabId === newTab.id && info.status === 'complete') {
                        chrome.tabs.onUpdated.removeListener(listener);
                        resolve(newTab);
                    }
                };
                chrome.tabs.onUpdated.addListener(listener);
            });
        });
        activeSessionTabId = tab.id;
        await new Promise(r => setTimeout(r, 1000));
    } else {
        // Ongoing session: use tracked tab if it exists
        if (activeSessionTabId) {
            try {
                tab = await chrome.tabs.get(activeSessionTabId);
            } catch (e) {
                // Tab was closed
                sendTelemetryLog(`Tracked tab ${activeSessionTabId} closed. Falling back to active tab.`);
                tab = null;
            }
        }

        if (!tab) {
            let [activeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
            if (!activeTab) {
                [activeTab] = await chrome.tabs.query({ active: true });
            }
            if (!activeTab) throw new Error("No active tab found");
            tab = activeTab;
            activeSessionTabId = tab.id;
        }

        const isEmptyOrNewTab = (url) => {
            return !url || url === 'about:blank' || url.startsWith('chrome://newtab') || url.startsWith('edge://newtab');
        };

        const isRestrictedUrl = (url) => {
            if (!url) return true;
            return (url.startsWith('chrome://') && !url.startsWith('chrome://newtab')) ||
                   (url.startsWith('edge://') && !url.startsWith('edge://newtab')) ||
                   (url.startsWith('about:') && url !== 'about:blank') ||
                   url.startsWith('chrome-extension://');
        };

        if (targetUrl && isEmptyOrNewTab(tab.url)) {
            sendTelemetryLog(`Navigating empty/new tab to extracted URL: ${targetUrl}`);
            tab = await new Promise((resolve, reject) => {
                chrome.tabs.update(tab.id, { url: targetUrl }, (updatedTab) => {
                    if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
                    const listener = (tabId, info) => {
                        if (tabId === updatedTab.id && info.status === 'complete') {
                            chrome.tabs.onUpdated.removeListener(listener);
                            resolve(updatedTab);
                        }
                    };
                    chrome.tabs.onUpdated.addListener(listener);
                });
            });
            await new Promise(r => setTimeout(r, 1000));
        } else if (isRestrictedUrl(tab.url)) {
            sendTelemetryLog(`Restricted tab detected. Opening new tab: ${targetUrl || 'https://www.google.com'}`);
            tab = await new Promise((resolve, reject) => {
                chrome.tabs.create({ url: targetUrl || 'https://www.google.com' }, (newTab) => {
                    if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
                    const listener = (tabId, info) => {
                        if (tabId === newTab.id && info.status === 'complete') {
                            chrome.tabs.onUpdated.removeListener(listener);
                            resolve(newTab);
                        }
                    };
                    chrome.tabs.onUpdated.addListener(listener);
                });
            });
            activeSessionTabId = tab.id;
            await new Promise(r => setTimeout(r, 1000));
        }
    }

    // 2. Capture Clean Screenshot Natively via CDP
    sendTelemetryLog(`Capturing pure screenshot via CDP for tab ${tab.id}...`);
    let screenshotBase64 = null;

    try {
        await new Promise((resolve, reject) => {
            chrome.debugger.attach({ tabId: tab.id }, "1.3", () => {
                if (chrome.runtime.lastError && !chrome.runtime.lastError.message.includes("Cannot attach to this target")) {
                    reject(new Error(chrome.runtime.lastError.message));
                } else {
                    resolve();
                }
            });
        });

        const captureResult = await new Promise((resolve, reject) => {
            chrome.debugger.sendCommand({ tabId: tab.id }, "Page.captureScreenshot", { format: "webp", quality: 80 }, (result) => {
                if (chrome.runtime.lastError) {
                    reject(new Error(chrome.runtime.lastError.message));
                } else {
                    resolve(result);
                }
            });
        });

        if (captureResult && captureResult.data) {
            screenshotBase64 = captureResult.data;
            sendTelemetryLog(`Successfully captured pure screenshot.`);
        }
    } catch (e) {
        sendTelemetryLog(`CDP Screenshot Error: ${e.message}`);
        throw e;
    } finally {
        chrome.debugger.detach({ tabId: tab.id }, () => {
            const err = chrome.runtime.lastError;
        });
    }

    // Return empty ui_elements as we now rely on vision
    return { success: true, ui_elements: [], screenshot_base64: screenshotBase64, tabId: tab.id, url: tab.url };
}

async function handleExecuteNativeAction(payload) {
    // Custom CDP actuation logic has been stripped out in Phase 2.
    // Execution is now handled natively by Playwright in the Python orchestrator.
    // We only retain minimal fallback support if needed, or simply return success.
    const action = payload.action;
    console.log(`Intercepted EXECUTE_ACTION request for ${action.action}. Action should be handled by Playwright.`);
    return { success: false, error: "Actuation relegated to Playwright orchestrator." };
}
