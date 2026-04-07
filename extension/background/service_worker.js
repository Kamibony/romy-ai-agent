import { API_ENDPOINTS, API_CONFIG } from '../utils/api.js';
import { MESSAGE_TYPES } from '../utils/message_types.js';
import { getAuthToken } from '../utils/auth.js';
// Removed firebase imports because Chrome is now decoupled from Firestore

// Central orchestrator for the Chrome Extension
console.log("Romy Agent Service Worker initialized.");

function generateId() {
    return Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
}


let isRecording = false;
let isProcessing = false;
let activeSessionTabId = null;

// Flag to ignore ghost clicks triggered by our own native actions
let isExecutingNativeAction = false;

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

// Keep service worker alive dynamically
chrome.alarms.create("keepAlive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "keepAlive") {
        if (!localBridgeWs || localBridgeWs.readyState !== WebSocket.OPEN) {
            connectLocalBridge();
        }
    }
});

function connectLocalBridge() {
    if (localBridgeWs && (localBridgeWs.readyState === WebSocket.OPEN || localBridgeWs.readyState === WebSocket.CONNECTING)) {
        return;
    }
    if (isConnecting) {
        return;
    }

    isConnecting = true;
    console.log(`Connecting to local bridge via WebSocket... (Attempt ${reconnectAttempts + 1})`);
    try {
        const ws = new WebSocket('ws://127.0.0.1:8765');
        localBridgeWs = ws;

        ws.onopen = () => {
            if (localBridgeWs !== ws) return;
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
                if (localBridgeWs === ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'ping' }));
                }
            }, 10000); // 10 seconds
        };

        ws.onmessage = async (event) => {
            if (localBridgeWs !== ws) return;
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
                            if (ws.readyState === WebSocket.OPEN) {
                                const payloadStr = JSON.stringify(result);
                                // Safely chunk base64 instead of raw utf-16 string to avoid severing multibyte characters
                                // We'll convert the whole payload to base64, chunk it, and decode on Python side
                                // In JS, btoa() requires Latin1, so we encode URI component and unescape first
                                const base64Payload = btoa(unescape(encodeURIComponent(payloadStr)));
                                const chunkSize = 128 * 1024; // 128KB chunks
                                const totalChunks = Math.ceil(base64Payload.length / chunkSize);
                                const messageId = crypto.randomUUID();

                                for (let i = 0; i < totalChunks; i++) {
                                    const chunk = base64Payload.substring(i * chunkSize, (i + 1) * chunkSize);
                                    ws.send(JSON.stringify({
                                        type: 'chunk',
                                        message_id: messageId,
                                        chunk_index: i,
                                        total_chunks: totalChunks,
                                        chunk_data: chunk
                                    }));
                                }
                            }
                        } else if (cmd.action_type === 'EXECUTE_ACTION') {
                            result = await handleExecuteNativeAction(cmd);
                            if (ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({ type: 'result', payload: result }));
                            }
                        } else if (cmd.action_type === 'GET_FRESH_TOKEN') {
                            const token = await getAuthToken();
                            result = { success: !!token, token: token };
                            if (ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({ type: 'result', payload: result }));
                            }
                        } else {
                            result = { success: false, error: "Unknown action_type." };
                            if (ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({ type: 'result', payload: result }));
                            }
                        }
                    } catch (err) {
                        console.error("Error processing command internally:", err);
                        result = { success: false, error: err.message || String(err) };
                        if (ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({ type: 'result', payload: result }));
                        }
                    }
                }
            } catch (err) {
                console.error("Error handling WebSocket message:", err);
            }
        };

        ws.onclose = () => {
            if (localBridgeWs !== ws) {
                return;
            }
            isConnecting = false;
            localBridgeWs = null;
            if (heartbeatInterval) clearInterval(heartbeatInterval);
            reconnectAttempts++;

            // Adjust backoff: initially fast retries, maxing out at 15 seconds to catch Python agent restarts quickly
            const backoff = Math.min(1000 * Math.pow(1.5, reconnectAttempts), 15000);
            console.log(`WebSocket connection closed. Reconnecting in ${backoff}ms...`);
            if (reconnectTimeout) clearTimeout(reconnectTimeout);
            reconnectTimeout = setTimeout(connectLocalBridge, backoff);
        };

        ws.onerror = (error) => {
            if (localBridgeWs !== ws) return;
            // Silence network errors to avoid spamming the console when Python agent is down
            if (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN) {
                // If we get an error while connecting (e.g. connection refused), close it
                // so the onclose handler can trigger a reconnect attempt.
                try {
                    ws.close();
                } catch(e) {}
            }
        };
    } catch (e) {
        isConnecting = false;
        console.error("Error setting up WebSocket:", e);
        reconnectAttempts++;
        const backoff = Math.min(1000 * Math.pow(1.5, reconnectAttempts), 15000);
        if (reconnectTimeout) clearTimeout(reconnectTimeout);
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
            if (isExecutingNativeAction) {
                console.log("[Telemetry] Ignored ghost click during native action execution.");
                return false;
            }
            handleGhostClick(request.payload);
            return false;

        default:
            console.warn(`Unknown message type: ${request.type}`);
    }
});

function handleGhostClick(payload) {
    sendTelemetryLog(`Forwarding ghost click to local agent: ${payload.xpath || payload.type}`);
    fetch('http://127.0.0.1:8764/api/human_guidance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: typeof payload === 'string' ? payload : JSON.stringify(payload)
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
        try {
            localBridgeWs.send(JSON.stringify({ type: 'telemetry', payload: message }));
        } catch (err) {
            console.error("Failed to send telemetry:", err);
        }
    }
}


class CDPLifecycleManager {
    constructor() {
        this.attachedTabs = new Set();
        chrome.debugger.onDetach.addListener((source, reason) => {
            if (source.tabId) {
                this.attachedTabs.delete(source.tabId);
                sendTelemetryLog(`[CDP] Session detached for tab ${source.tabId}. Reason: ${reason}`);
            }
        });
    }

    async attach(tabId) {
        if (this.attachedTabs.has(tabId)) {
            return;
        }
        return new Promise((resolve, reject) => {
            chrome.debugger.attach({ tabId: tabId }, "1.3", () => {
                const err = chrome.runtime.lastError;
                if (err && !err.message.includes("Cannot attach to this target")) {
                    reject(new Error(err.message));
                } else {
                    this.attachedTabs.add(tabId);
                    resolve();
                }
            });
        });
    }

    async detach(tabId) {
        if (!this.attachedTabs.has(tabId)) {
            return;
        }
        return new Promise((resolve) => {
            chrome.debugger.detach({ tabId: tabId }, () => {
                const err = chrome.runtime.lastError; // Ignore errors
                this.attachedTabs.delete(tabId);
                resolve();
            });
        });
    }

    async sendCommand(tabId, method, params = {}) {
        if (!this.attachedTabs.has(tabId)) {
            throw new Error(`[CDP] Cannot send command ${method} to unattached tab ${tabId}`);
        }
        return new Promise((resolve, reject) => {
            chrome.debugger.sendCommand({ tabId: tabId }, method, params, (result) => {
                const err = chrome.runtime.lastError;
                if (err) {
                    if (err.message.includes("Session with given id not found") || err.message.includes("Cannot send command to a detached session")) {
                         this.attachedTabs.delete(tabId);
                         reject(new Error(`[CDP] Session detached while sending ${method}: ${err.message}`));
                    } else {
                         reject(new Error(`[CDP Error] ${method}: ${err.message}`));
                    }
                } else {
                    resolve(result);
                }
            });
        });
    }
}
const cdpManager = new CDPLifecycleManager();

// --- Utility: Robust Navigation Wrapper ---
async function waitForTabStable(tabId, maxTimeoutMs = 10000) {
    return new Promise((resolve, reject) => {
        let isResolved = false;
        let listener = null;
        let timeoutId = null;

        const cleanup = () => {
            if (isResolved) return;
            isResolved = true;
            if (listener) chrome.tabs.onUpdated.removeListener(listener);
            if (timeoutId) clearTimeout(timeoutId);
        };

        const resolveSafe = (tId) => {
            chrome.tabs.get(tId, (t) => {
                if (chrome.runtime.lastError) {
                    // Ignore error on final resolve, just resolve null/undefined or current state if possible
                }
                resolve(t);
            });
        };

        // 1. Attach Listener for future completion FIRST to avoid micro race condition
        listener = (updatedTabId, info) => {
            if (updatedTabId === tabId && info.status === 'complete') {
                sendTelemetryLog(`[Navigation] Tab ${tabId} reached 'complete' status.`);
                cleanup();
                resolveSafe(tabId);
            }
        };
        chrome.tabs.onUpdated.addListener(listener);

        // 2. Immediate Check: Is it already complete?
        chrome.tabs.get(tabId, (tab) => {
            if (chrome.runtime.lastError) {
                cleanup();
                return reject(new Error(chrome.runtime.lastError.message));
            }
            if (tab.status === 'complete') {
                sendTelemetryLog(`[Navigation] Tab ${tabId} already complete.`);
                cleanup();
                return resolve(tab);
            }

            // 3. Hard Timeout Fallback (start timeout only after we confirm it's not complete yet)
            timeoutId = setTimeout(() => {
                sendTelemetryLog(`[Navigation] Tab ${tabId} stability timed out after ${maxTimeoutMs}ms. Forcing proceed.`);
                cleanup();
                resolveSafe(tabId); // Resolve anyway, assume 'good enough'
            }, maxTimeoutMs);
        });
    });
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
                resolve(newTab);
            });
        });
        tab = await waitForTabStable(tab.id);
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
                    resolve(updatedTab);
                });
            });
            tab = await waitForTabStable(tab.id);
            await new Promise(r => setTimeout(r, 1000));
        } else if (isRestrictedUrl(tab.url)) {
            sendTelemetryLog(`Restricted tab detected. Opening new tab: ${targetUrl || 'https://www.google.com'}`);
            tab = await new Promise((resolve, reject) => {
                chrome.tabs.create({ url: targetUrl || 'https://www.google.com' }, (newTab) => {
                    if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
                    resolve(newTab);
                });
            });
            tab = await waitForTabStable(tab.id);
            activeSessionTabId = tab.id;
            await new Promise(r => setTimeout(r, 1000));
        }
    }

    // 2. Universal UI Quiescence (Wait for SPA Hydration to Settle)
    sendTelemetryLog(`Waiting for UI Quiescence (DOM + Network stabilization) on tab ${tab.id}...`);
    try {
        await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            world: "MAIN",
            func: () => {
                return new Promise((resolve) => {
                    const maxTimeout = 5000;
                    const debounceMs = 500;

                    let timeoutId;
                    let debounceId;
                    let intervalId;

                    const settle = () => {
                        observer.disconnect();
                        clearTimeout(timeoutId);
                        clearTimeout(debounceId);
                        clearInterval(intervalId);
                        resolve('settled');
                    };

                    const observer = new MutationObserver(() => {
                        clearTimeout(debounceId);
                        debounceId = setTimeout(checkStability, debounceMs);
                    });

                    observer.observe(document.body, { childList: true, subtree: true, attributes: true });

                    function checkStability() {
                        const activeReqs = window.__romyActiveRequests || 0;
                        if (activeReqs === 0) {
                            settle();
                        } else {
                            // If network is still active, wait and re-check via interval
                            clearTimeout(debounceId);
                            debounceId = setTimeout(checkStability, debounceMs);
                        }
                    }

                    // Also set up a polling interval to catch network drops if DOM doesn't mutate
                    intervalId = setInterval(() => {
                        const activeReqs = window.__romyActiveRequests || 0;
                        if (activeReqs === 0) {
                             // Do not resolve yet if debounceId is running (DOM mutation recently)
                        } else {
                            // Reset the DOM stability timer because network is active
                            clearTimeout(debounceId);
                            debounceId = setTimeout(checkStability, debounceMs);
                        }
                    }, 100);

                    debounceId = setTimeout(checkStability, debounceMs);
                    timeoutId = setTimeout(settle, maxTimeout);
                });
            }
        });
        sendTelemetryLog(`UI + Network stabilized.`);
    } catch (qErr) {
        sendTelemetryLog(`Warning: UI Quiescence script failed: ${qErr.message}. Proceeding anyway.`);
    }

    // 3. Capture Clean Screenshot Natively via CDP and Extract UI Elements
    sendTelemetryLog(`Capturing pure screenshot via CDP for tab ${tab.id}...`);
    let screenshotBase64 = null;
    let uiElements = [];
    let dpr = 1.0;
    let clipboardStatus = "unknown";

    try {
        await cdpManager.attach(tab.id);

        // Fetch Device Pixel Ratio to properly scale coordinates/image bounds
        const dprResult = await cdpManager.sendCommand(tab.id, "Runtime.evaluate", {
            expression: "window.devicePixelRatio"
        });
        dpr = dprResult?.result?.value || 1.0;

        // Optimizing screenshot by requesting a scaled down image directly from CDP
        // to reduce base64 transfer time overhead
        const captureResult = await cdpManager.sendCommand(tab.id, "Page.captureScreenshot", {
            format: "jpeg",
            quality: 60,
            optimizeForSpeed: true // Custom hint for faster captures if supported
        });

        if (captureResult && captureResult.data) {
            screenshotBase64 = captureResult.data;
            sendTelemetryLog(`Successfully captured pure screenshot.`);
        }

        // 3. Request DOM Map from the content script using scripting API
        sendTelemetryLog(`Requesting structural UI array from RomyDomMapper across all frames...`);
        try {
            const results = await chrome.scripting.executeScript({
                target: { tabId: tab.id, allFrames: true },
                func: () => {
                    if (window.RomyDomMapper && typeof window.RomyDomMapper.extractUIElements === 'function') {
                        return window.RomyDomMapper.extractUIElements();
                    }
                    return [];
                }
            });

            if (results && results.length > 0) {
                for (const result of results) {
                    if (result.result && Array.isArray(result.result)) {
                        // Tag each element with its frameId so we can interact with it later
                        const elementsWithFrameId = result.result.map(el => {
                            el.frameId = result.frameId;
                            return el;
                        });
                        uiElements = uiElements.concat(elementsWithFrameId);
                    }
                }
                sendTelemetryLog(`Successfully extracted ${uiElements.length} UI elements across ${results.length} frames.`);
            }
        } catch (domErr) {
            sendTelemetryLog(`Warning: Failed to extract UI elements via scripting: ${domErr.message}. Falling back to empty array.`);
        }

        // 4. Try to fetch clipboard status (Requires document focus/permissions)
        try {
            const clipResults = await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                func: async () => {
                    try {
                        const text = await navigator.clipboard.readText();
                        return text ? "contains text" : "empty";
                    } catch (e) {
                        return "unknown"; // Might not have permission, or not text
                    }
                }
            });
            if (clipResults && clipResults[0] && clipResults[0].result) {
                clipboardStatus = clipResults[0].result;
            }
        } catch (clipErr) {
            sendTelemetryLog(`Warning: Failed to extract clipboard status: ${clipErr.message}`);
        }

    } catch (e) {
        sendTelemetryLog(`CDP Screenshot Error: ${e.message}`);
        throw e;
    } finally {
        await cdpManager.detach(tab.id);
    }

    return { success: true, ui_elements: uiElements, screenshot_base64: screenshotBase64, tabId: tab.id, url: tab.url, dpr: dpr, clipboard_status: clipboardStatus };
}

async function handleExecuteNativeAction(payload) {
    const actionData = payload.action;
    const actionType = actionData.action.toUpperCase();
    sendTelemetryLog(`Executing Native Action via CDP: ${actionType}`);

    if (!activeSessionTabId) {
        return { success: false, error: "No active session tab to execute action on." };
    }

    isExecutingNativeAction = true;

    try {
        await cdpManager.attach(activeSessionTabId);

        // 1. Get window.devicePixelRatio to scale physical pixels
        const evalResult = await cdpManager.sendCommand(activeSessionTabId, "Runtime.evaluate", {
            expression: "window.devicePixelRatio"
        });
        const dpr = evalResult?.result?.value || 1;

        // Helper function for JIT target locating
        const getRealTimeCoordinates = async (targetId, fallbackXpath, fallbackCss, targetFrameId, attemptScrollDiscovery = true) => {
            // Escape quotes in selectors to prevent eval errors
            const safeXpath = fallbackXpath ? fallbackXpath.replace(/"/g, '\\"') : '';
            const safeCss = fallbackCss ? fallbackCss.replace(/"/g, '\\"') : '';

            let evalFunc = (targetId, fallbackXpath, fallbackCss) => {
                let el = document.querySelector(`[data-romy-id="${targetId}"]`);
                if (!el && fallbackXpath) {
                    try { el = document.evaluate(fallbackXpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; } catch(e) {}
                }
                if (!el && fallbackCss) {
                    try { el = document.querySelector(fallbackCss); } catch(e) {}
                }
                if (el) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0) return { found: false };

                    // We need absolute coordinates from the main frame.
                    // If we're inside an iframe, getBoundingClientRect is relative to the iframe.
                    // We need to calculate absolute position, but we can only access window/frame locally.
                    // A trick is to use screenX/Y or pass it up. However, chrome.scripting handles the translation implicitly if we just return the element's rect and add the iframe's rect from the parent.
                    // But from inside the frame we don't know our parent iframe element securely if cross-origin.
                    // Actually, the simplest way is to let CDP handle it or just rely on the fallback coordinates LLM gave us for iframes since CDP events are viewport relative.
                    // Let's just return relative to the current frame's viewport.
                    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, found: true };
                }
                return { found: false };
            };

            // Using chrome.scripting.executeScript since we need to target specific frameIds robustly
            try {
                const results = await chrome.scripting.executeScript({
                    target: { tabId: activeSessionTabId, frameIds: targetFrameId !== undefined ? [targetFrameId] : undefined },
                    func: evalFunc,
                    args: [targetId, safeXpath, safeCss]
                });

                if (results && results[0] && results[0].result) {
                     let coords = results[0].result;
                     if (coords.found) return coords;
                }
            } catch (e) {
                sendTelemetryLog(`JIT locating error via scripting: ${e.message}`);
            }

            // Virtualized DOM Scroll Discovery Heuristic:
            // If target is missing, iterate over scrollable containers and slowly scroll down to force rendering,
            // then check if the element has appeared.
            if (attemptScrollDiscovery) {
                sendTelemetryLog(`Target ${targetId} not found natively. Attempting Virtualized DOM Scroll Discovery...`);
                try {
                    const scrollResults = await chrome.scripting.executeScript({
                        target: { tabId: activeSessionTabId, frameIds: targetFrameId !== undefined ? [targetFrameId] : undefined },
                        func: async (targetId, fallbackXpath, fallbackCss) => {
                            const scrollables = Array.from(document.querySelectorAll('*')).filter(el => {
                                if (el === document.body || el === document.documentElement) return false;
                                const style = window.getComputedStyle(el);
                                return (style.overflowY === 'auto' || style.overflowY === 'scroll') && el.scrollHeight > el.clientHeight;
                            });

                            if (scrollables.length === 0) return { found: false };

                            // Helper function evaluating target presence
                            const checkTarget = () => {
                                let el = document.querySelector(`[data-romy-id="${targetId}"]`);
                                if (!el && fallbackXpath) {
                                    try { el = document.evaluate(fallbackXpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; } catch(e) {}
                                }
                                if (!el && fallbackCss) {
                                    try { el = document.querySelector(fallbackCss); } catch(e) {}
                                }
                                if (el) {
                                    const rect = el.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0) {
                                        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, found: true };
                                    }
                                }
                                return null;
                            };

                            for (const container of scrollables) {
                                // Try scrolling down a few times
                                for (let i = 0; i < 5; i++) {
                                    if (container.scrollTop + container.clientHeight >= container.scrollHeight - 10) break;
                                    container.scrollTop += 300;

                                    // Wait for rendering
                                    await new Promise(r => setTimeout(r, 400));

                                    const coords = checkTarget();
                                    if (coords) return coords;
                                }
                                // We don't revert the scroll position so the element stays in view
                            }
                            return { found: false };
                        },
                        args: [targetId, safeXpath, safeCss]
                    });

                    if (scrollResults && scrollResults[0] && scrollResults[0].result) {
                        let coords = scrollResults[0].result;
                        if (coords.found) {
                            sendTelemetryLog(`Scroll Discovery SUCCESS: Found target ${targetId} after scrolling.`);
                            return coords;
                        }
                    }
                } catch (e) {
                    sendTelemetryLog(`Scroll Discovery execution failed: ${e.message}`);
                }
            }

            return { found: false };
        };

        if (actionType === 'CLICK') {
            // Mitigate Hydration & CLS Delays by waiting for stability before clicking
            try {
                await new Promise((resolve) => {
                    chrome.tabs.sendMessage(activeSessionTabId, { type: 'WAIT_FOR_STABILITY', debounceMs: 500, timeoutMs: 3000 }, (response) => {
                        // ignore errors from sendMessage (e.g. if content script isn't fully ready)
                        const err = chrome.runtime.lastError;
                        resolve();
                    });
                });
            } catch (e) {
                // Ignore timeout/errors and just proceed
            }

            let x, y;
            if (actionData.target_id) {
                sendTelemetryLog(`JIT locating target_id: ${actionData.target_id}`);
                const coords = await getRealTimeCoordinates(actionData.target_id, actionData.fallback_xpath || '', actionData.fallback_css || '', actionData.frameId);
                if (coords && coords.found) {
                    // JIT provides CSS pixels
                    x = coords.x;
                    y = coords.y;
                    sendTelemetryLog(`Target located at CSS coords: (${x}, ${y})`);
                } else if (actionData.fallback_x !== undefined && actionData.fallback_y !== undefined) {
                    sendTelemetryLog(`JIT failed. Using fallback coordinates from DOM snapshot.`);
                    x = actionData.fallback_x;
                    y = actionData.fallback_y;
                } else if (actionData.coordinates && actionData.coordinates.length >= 2) {
                    sendTelemetryLog(`JIT failed. Using LLM coordinates.`);
                    x = actionData.coordinates[0] / dpr;
                    y = actionData.coordinates[1] / dpr;
                } else {
                    return { success: false, error: `Could not locate target_id ${actionData.target_id} in DOM (even with fallbacks) and no coordinates provided` };
                }
            } else {
                const coords = actionData.coordinates;
                if (!coords || coords.length < 2) {
                    return { success: false, error: "Coordinates missing for action CLICK" };
                }
                // LLM outputs coordinates based on scaled physical image, so we divide by DPR to get CSS pixels
                x = coords[0] / dpr;
                y = coords[1] / dpr;
            }

            x = Math.round(x);
            y = Math.round(y);

            // Draw a red dot for HITL feedback before clicking (using CSS pixels)
            try {
                await cdpManager.sendCommand(activeSessionTabId, "Runtime.evaluate", {
                    expression: `
                        (function() {
                            const dot = document.createElement('div');
                            dot.style.position = 'fixed';
                            dot.style.left = '${x}px';
                            dot.style.top = '${y}px';
                            dot.style.width = '10px';
                            dot.style.height = '10px';
                            dot.style.backgroundColor = 'rgba(255, 0, 0, 0.7)';
                            dot.style.borderRadius = '50%';
                            dot.style.zIndex = '2147483647'; // Max z-index
                            dot.style.pointerEvents = 'none'; // Don't block the actual click
                            dot.style.transform = 'translate(-50%, -50%)';
                            document.body.appendChild(dot);
                            setTimeout(() => {
                                if(dot.parentNode) dot.parentNode.removeChild(dot);
                            }, 1000);
                        })();
                    `
                });
            } catch (err) {
                sendTelemetryLog(`[CDP] Failed to draw HITL feedback dot: ${err.message}`);
            }

            if (actionData.stealth_mode !== false) {
                // Stealth Kinematics: Add an interpolated mouse move before clicking
                const currentMouseX = Math.floor(Math.random() * 500); // Simulate coming from somewhere
                const currentMouseY = Math.floor(Math.random() * 500);

                await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", {
                    type: "mouseMoved",
                    x: Math.floor((x + currentMouseX) / 2),
                    y: Math.floor((y + currentMouseY) / 2)
                });
                await new Promise(r => setTimeout(r, Math.floor(Math.random() * 50) + 20));

                await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", {
                    type: "mouseMoved",
                    x: x,
                    y: y
                });
                await new Promise(r => setTimeout(r, Math.floor(Math.random() * 100) + 50));
            }

            // Dispatch MouseEvent (Click)
            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", {
                type: "mousePressed",
                x: x,
                y: y,
                button: "left",
                clickCount: 1
            });

            if (actionData.stealth_mode !== false) {
                // Stealth Kinematics: Randomized click duration
                const clickDuration = Math.floor(Math.random() * (120 - 40 + 1)) + 40;
                await new Promise(r => setTimeout(r, clickDuration));
            } else {
                await new Promise(r => setTimeout(r, 50)); // Fast fixed delay
            }

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", {
                type: "mouseReleased",
                x: x,
                y: y,
                button: "left",
                clickCount: 1
            });

            sendTelemetryLog(`Action CLICK at (${x}, ${y}) executed successfully.`);

        } else if (actionType === 'TYPE') {
            const text = actionData.text || "";
            if (!text) return { success: false, error: "Text missing for action TYPE" };

            sendTelemetryLog(`Typing text: ${text}`);

            // Trap B: The "Blind Typist". If coordinates/target_id are provided, click first to gain focus.
            let x, y;
            let focusFound = false;

            if (actionData.target_id) {
                sendTelemetryLog(`JIT locating target_id: ${actionData.target_id} for TYPE focus`);
                const coords = await getRealTimeCoordinates(actionData.target_id, actionData.fallback_xpath || '', actionData.fallback_css || '', actionData.frameId);
                if (coords && coords.found) {
                    x = coords.x;
                    y = coords.y;
                    focusFound = true;
                } else if (actionData.fallback_x !== undefined && actionData.fallback_y !== undefined) {
                    sendTelemetryLog(`JIT focus failed. Using fallback coordinates from DOM snapshot.`);
                    x = actionData.fallback_x;
                    y = actionData.fallback_y;
                    focusFound = true;
                } else if (actionData.coordinates && actionData.coordinates.length >= 2) {
                    sendTelemetryLog(`JIT focus failed. Using LLM coordinates.`);
                    x = actionData.coordinates[0] / dpr;
                    y = actionData.coordinates[1] / dpr;
                    focusFound = true;
                }
            } else if (actionData.coordinates && actionData.coordinates.length >= 2) {
                x = actionData.coordinates[0] / dpr;
                y = actionData.coordinates[1] / dpr;
                focusFound = true;
            }

            if (focusFound) {
                x = Math.round(x);
                y = Math.round(y);

                // Draw a red dot for HITL feedback before typing focus click (using CSS pixels)
                try {
                    await cdpManager.sendCommand(activeSessionTabId, "Runtime.evaluate", {
                        expression: `
                            (function() {
                                // Attempt to focus the element directly under the coordinates BEFORE appending dot
                                const el = document.elementFromPoint(${x}, ${y});
                                if (el && typeof el.focus === 'function') {
                                    el.focus();
                                }

                                const dot = document.createElement('div');
                                dot.style.position = 'fixed';
                                dot.style.left = '${x}px';
                                dot.style.top = '${y}px';
                                dot.style.width = '10px';
                                dot.style.height = '10px';
                                dot.style.backgroundColor = 'rgba(0, 0, 255, 0.7)'; // Blue for type focus
                                dot.style.borderRadius = '50%';
                                dot.style.zIndex = '2147483647';
                                dot.style.pointerEvents = 'none';
                                dot.style.transform = 'translate(-50%, -50%)';
                                document.body.appendChild(dot);
                                setTimeout(() => {
                                    if(dot.parentNode) dot.parentNode.removeChild(dot);
                                }, 1000);
                            })();
                        `
                    });
                } catch (err) {
                    sendTelemetryLog(`[CDP] Failed to draw HITL feedback dot or focus element: ${err.message}`);
                }

                await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", { type: "mousePressed", x: x, y: y, button: "left", clickCount: 1 });
                await new Promise(r => setTimeout(r, 50));
                await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", { type: "mouseReleased", x: x, y: y, button: "left", clickCount: 1 });
                await new Promise(r => setTimeout(r, 100)); // Allow focus to settle
            }

            for (let i = 0; i < text.length; i++) {
                const char = text[i];
                await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", {
                    type: "char",
                    text: char
                });
                if (actionData.stealth_mode !== false) {
                    // Stealth Kinematics: Randomized human-like typing jitter (50ms - 150ms)
                    const jitterDelay = Math.floor(Math.random() * (150 - 50 + 1)) + 50;
                    await new Promise(r => setTimeout(r, jitterDelay));
                } else {
                    await new Promise(r => setTimeout(r, 10)); // Typematic delay
                }
            }

            if (actionData.submit || actionData.pressEnter) {
                sendTelemetryLog(`Autonomously injecting Enter keystroke for native form submission...`);
                if (actionData.stealth_mode !== false) {
                    // Stealth Kinematics: Add realistic pause before pressing Enter
                    const preEnterDelay = Math.floor(Math.random() * (400 - 150 + 1)) + 150;
                    await new Promise(r => setTimeout(r, preEnterDelay));
                }

                const keyData = { keyIdentifier: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };

                await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", {
                    type: "keyDown",
                    keyIdentifier: keyData.keyIdentifier,
                    code: keyData.code,
                    windowsVirtualKeyCode: keyData.windowsVirtualKeyCode,
                    nativeVirtualKeyCode: keyData.nativeVirtualKeyCode
                });

                await new Promise(r => setTimeout(r, 50));

                await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", {
                    type: "keyUp",
                    keyIdentifier: keyData.keyIdentifier,
                    code: keyData.code,
                    windowsVirtualKeyCode: keyData.windowsVirtualKeyCode,
                    nativeVirtualKeyCode: keyData.nativeVirtualKeyCode
                });
                sendTelemetryLog(`Enter keystroke injected successfully.`);
            }

            sendTelemetryLog(`Action TYPE executed successfully.`);

        } else if (actionType === 'NAVIGATE' || actionType === 'OPEN_TAB') {
            const url = actionData.url;
            if (!url) return { success: false, error: "URL missing for NAVIGATE/OPEN_TAB" };

            if (actionType === 'OPEN_TAB') {

                 let newTab = await new Promise((resolve, reject) => {
                    chrome.tabs.create({ url: url }, (tab) => {
                        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
                        resolve(tab);
                    });
                });
                activeSessionTabId = newTab.id; // Switch tracking to new tab
                await waitForTabStable(newTab.id);

            } else {

                 let updatedTab = await new Promise((resolve, reject) => {
                    chrome.tabs.update(activeSessionTabId, { url: url }, (tab) => {
                        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
                        resolve(tab);
                    });
                });
                await waitForTabStable(updatedTab.id);

            }
             sendTelemetryLog(`${actionType} to ${url} executed successfully.`);
        } else if (actionType === 'PRESS_ENTER') {
            sendTelemetryLog(`Executing PRESS_ENTER action`);

            const keyData = { keyIdentifier: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", {
                type: "keyDown",
                keyIdentifier: keyData.keyIdentifier,
                code: keyData.code,
                windowsVirtualKeyCode: keyData.windowsVirtualKeyCode,
                nativeVirtualKeyCode: keyData.nativeVirtualKeyCode
            });

            await new Promise(r => setTimeout(r, 50));

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", {
                type: "keyUp",
                keyIdentifier: keyData.keyIdentifier,
                code: keyData.code,
                windowsVirtualKeyCode: keyData.windowsVirtualKeyCode,
                nativeVirtualKeyCode: keyData.nativeVirtualKeyCode
            });

            sendTelemetryLog(`PRESS_ENTER executed successfully.`);

        } else if (actionType === 'FOCUS_TAB') {
            if (activeSessionTabId) {
                chrome.tabs.update(activeSessionTabId, { active: true });
                chrome.tabs.get(activeSessionTabId, (tab) => {
                    if (tab && tab.windowId) {
                        chrome.windows.update(tab.windowId, { focused: true });
                    }
                });
            }
        } else if (actionType === 'SCROLL') {
            const direction = actionData.direction || 'down';
            sendTelemetryLog(`Scrolling ${direction}`);

            // Typical scroll amounts
            const amount = direction.toLowerCase() === 'up' ? -500 : 500;

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", {
                type: "mouseWheel",
                x: 0,
                y: 0,
                deltaX: 0,
                deltaY: amount
            });
            sendTelemetryLog(`SCROLL ${direction} executed successfully.`);
        } else if (actionType === 'PRESS' || actionType === 'PRESS_KEY') {
            const key = actionData.key;
            if (!key) return { success: false, error: "Key missing for action PRESS" };

            sendTelemetryLog(`Pressing key: ${key}`);

            // Map common names to CDP key names if necessary. Playwright often sends 'Enter', 'Escape', 'Tab', etc.
            const keyToCode = {
                'Enter': { isControl: true, keyIdentifier: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 },
                'Escape': { isControl: true, keyIdentifier: 'U+001B', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 },
                'Tab': { isControl: true, keyIdentifier: 'U+0009', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 },
                'Backspace': { isControl: true, keyIdentifier: 'U+0008', code: 'Backspace', windowsVirtualKeyCode: 8, nativeVirtualKeyCode: 8 }
            };

            const keyData = keyToCode[key] || { text: key, unmodifiedText: key, keyIdentifier: key, code: key, windowsVirtualKeyCode: 0, nativeVirtualKeyCode: 0 };

            const keyDownPayload = {
                type: "keyDown",
                keyIdentifier: keyData.keyIdentifier,
                code: keyData.code,
                windowsVirtualKeyCode: keyData.windowsVirtualKeyCode,
                nativeVirtualKeyCode: keyData.nativeVirtualKeyCode
            };

            if (!keyData.isControl) {
                keyDownPayload.text = keyData.text;
                keyDownPayload.unmodifiedText = keyData.unmodifiedText;
            }

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", keyDownPayload);

            await new Promise(r => setTimeout(r, 50));

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", {
                type: "keyUp",
                keyIdentifier: keyData.keyIdentifier,
                code: keyData.code,
                windowsVirtualKeyCode: keyData.windowsVirtualKeyCode,
                nativeVirtualKeyCode: keyData.nativeVirtualKeyCode
            });

            sendTelemetryLog(`PRESS ${key} executed successfully.`);
        } else if (actionType === 'HOVER') {
            let x, y;
            if (actionData.target_id) {
                sendTelemetryLog(`JIT locating target_id: ${actionData.target_id} for HOVER`);
                const coords = await getRealTimeCoordinates(actionData.target_id, actionData.fallback_xpath || '', actionData.fallback_css || '', actionData.frameId);
                if (coords && coords.found) {
                    x = coords.x;
                    y = coords.y;
                } else if (actionData.fallback_x !== undefined && actionData.fallback_y !== undefined) {
                    x = actionData.fallback_x;
                    y = actionData.fallback_y;
                } else if (actionData.coordinates && actionData.coordinates.length >= 2) {
                    x = actionData.coordinates[0] / dpr;
                    y = actionData.coordinates[1] / dpr;
                } else {
                    return { success: false, error: "Could not locate target for HOVER" };
                }
            } else if (actionData.coordinates && actionData.coordinates.length >= 2) {
                x = actionData.coordinates[0] / dpr;
                y = actionData.coordinates[1] / dpr;
            } else {
                return { success: false, error: "Coordinates missing for action HOVER" };
            }

            x = Math.round(x);
            y = Math.round(y);

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", {
                type: "mouseMoved",
                x: x,
                y: y
            });
            sendTelemetryLog(`Action HOVER at (${x}, ${y}) executed successfully.`);
        } else if (actionType === 'EXECUTE_JS') {
            const script = actionData.script || actionData.code || "";
            if (!script) return { success: false, error: "Script/Code missing for action EXECUTE_JS" };

            sendTelemetryLog(`Executing JS: ${script}`);
            const result = await cdpManager.sendCommand(activeSessionTabId, "Runtime.evaluate", {
                expression: script,
                returnByValue: true
            });

            if (result && result.exceptionDetails) {
                return { success: false, error: result.exceptionDetails.exception ? result.exceptionDetails.exception.description : "JS Execution Exception" };
            }

            sendTelemetryLog(`EXECUTE_JS executed successfully.`);

            // Return early for EXECUTE_JS to include the evaluation result
            return { success: true, result: result?.result?.value };
        } else if (actionType === 'REPLY') {
            const text = actionData.text || "";
            sendTelemetryLog(`Agent Replied: ${text}`);
            return { success: true };
        } else if (actionType === 'RESET_VIEW') {
            sendTelemetryLog(`Executing RESET_VIEW action`);

            const keyData = { keyIdentifier: 'U+001B', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 };

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", {
                type: "keyDown",
                keyIdentifier: keyData.keyIdentifier,
                code: keyData.code,
                windowsVirtualKeyCode: keyData.windowsVirtualKeyCode,
                nativeVirtualKeyCode: keyData.nativeVirtualKeyCode
            });

            await new Promise(r => setTimeout(r, 50));

            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchKeyEvent", {
                type: "keyUp",
                keyIdentifier: keyData.keyIdentifier,
                code: keyData.code,
                windowsVirtualKeyCode: keyData.windowsVirtualKeyCode,
                nativeVirtualKeyCode: keyData.nativeVirtualKeyCode
            });

            // Also dispatch a click outside (at 0,0) to close some menus
            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", { type: "mousePressed", x: 0, y: 0, button: "left", clickCount: 1 });
            await new Promise(r => setTimeout(r, 50));
            await cdpManager.sendCommand(activeSessionTabId, "Input.dispatchMouseEvent", { type: "mouseReleased", x: 0, y: 0, button: "left", clickCount: 1 });

            sendTelemetryLog(`RESET_VIEW executed successfully.`);
        } else if (actionType === 'WAIT') {
            const seconds = parseFloat(actionData.seconds) || 2;
            sendTelemetryLog(`Executing explicit WAIT for ${seconds} seconds...`);
            await new Promise(r => setTimeout(r, seconds * 1000));
            return { success: true };
        } else {
             sendTelemetryLog(`Unsupported native action type: ${actionType}`);
             return { success: false, error: `Unsupported action type: ${actionType}` };
        }

        // Trap A: Enforce Post-Action Stabilization (1.5s) to allow SPA DOM to settle
        if (['CLICK', 'TYPE', 'SCROLL', 'PRESS', 'PRESS_KEY', 'PRESS_ENTER', 'NAVIGATE', 'OPEN_TAB', 'HOVER', 'RESET_VIEW'].includes(actionType)) {
            sendTelemetryLog(`Enforcing 1.5s Post-Action Stabilization Wait after ${actionType}...`);
            await new Promise(r => setTimeout(r, 1500));
        }

        return { success: true };

    } catch (e) {
        sendTelemetryLog(`Native Execution Error: ${e.message}`);
        return { success: false, error: e.message };
    } finally {
        isExecutingNativeAction = false;
        await cdpManager.detach(activeSessionTabId);
    }
}
