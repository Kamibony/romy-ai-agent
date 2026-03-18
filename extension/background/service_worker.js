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

// Local bridge WebSocket to receive commands from the Desktop Agent Orchestrator
let localBridgeWs = null;
let reconnectTimeout = null;

function connectLocalBridge() {
    if (localBridgeWs) {
        return;
    }

    console.log("Connecting to local bridge via WebSocket...");
    try {
        localBridgeWs = new WebSocket('ws://127.0.0.1:8765');

        localBridgeWs.onopen = () => {
            console.log("WebSocket connected to local bridge.");
            if (reconnectTimeout) {
                clearTimeout(reconnectTimeout);
                reconnectTimeout = null;
            }
        };

        localBridgeWs.onmessage = async (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'command') {
                    const cmd = msg.payload;
                    console.log("Received command from Python Agent:", cmd);
                    let result;
                    try {
                        if (cmd.action_type === 'GET_STATE') {
                            result = await handleGetState(cmd);
                        } else if (cmd.action_type === 'EXECUTE_ACTION') {
                            result = await handleExecuteNativeAction(cmd);
                        } else {
                            // Legacy fallback if needed
                            result = await processCommandInternally(cmd);
                        }
                    } catch (err) {
                        console.error("Error processing command internally:", err);
                        result = { success: false, error: err.message || String(err) };
                    }

                    // Send result back
                    if (localBridgeWs && localBridgeWs.readyState === WebSocket.OPEN) {
                        localBridgeWs.send(JSON.stringify({ type: 'result', payload: result }));
                    } else {
                        console.error("WebSocket not open. Cannot send result.");
                    }
                }
            } catch (err) {
                console.error("Error handling WebSocket message:", err);
            }
        };

        localBridgeWs.onclose = () => {
            console.log("WebSocket connection closed. Reconnecting in 2s...");
            localBridgeWs = null;
            reconnectTimeout = setTimeout(connectLocalBridge, 2000);
        };

        localBridgeWs.onerror = (error) => {
            // Silence network errors to avoid spamming the console when Python agent is down
            // console.error("WebSocket error:", error);
            if (localBridgeWs) {
                localBridgeWs.close(); // Force close to trigger reconnect
            }
        };
    } catch (e) {
        console.error("Error setting up WebSocket:", e);
        reconnectTimeout = setTimeout(connectLocalBridge, 2000);
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

// Store the latest DOM bounds globally for native execution
let latestDomBounds = {};

async function handleGetState(payload) {
    const { commandText } = payload;
    sendTelemetryLog(`Requesting WEB State...`);

    // 1. Get Active Tab
    let [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab) {
        [tab] = await chrome.tabs.query({ active: true });
    }
    if (!tab) {
        throw new Error("No active tab found");
    }

    // Extract target URL from command text if available
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
        await new Promise(r => setTimeout(r, 1000));
    }

    // 2. Extract DOM Natively via CDP
    sendTelemetryLog(`Extracting DOM from tab natively via CDP...`);
    const uiElements = [];
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

        await new Promise(r => chrome.debugger.sendCommand({ tabId: tab.id }, "DOMSnapshot.enable", {}, r));
        const axTree = await new Promise((resolve, reject) => {
            chrome.debugger.sendCommand({ tabId: tab.id }, "Accessibility.getFullAXTree", {}, (res) => {
                if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                else resolve(res);
            });
        });
        const snap = await new Promise((resolve, reject) => {
            chrome.debugger.sendCommand({ tabId: tab.id }, "DOMSnapshot.captureSnapshot", {
                computedStyles: [],
                includePaintOrder: true,
                includeDOMRects: true
            }, (res) => {
                if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                else resolve(res);
            });
        });

        const layoutMetrics = await new Promise((resolve, reject) => {
            chrome.debugger.sendCommand({ tabId: tab.id }, "Page.getLayoutMetrics", {}, (res) => {
                if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                else resolve(res);
            });
        });

        const viewport = layoutMetrics.layoutViewport || { pageX: 0, pageY: 0, clientWidth: 1920, clientHeight: 1080 };
        const boundsMap = {};

        if (snap && snap.documents && snap.documents.length > 0) {
            const doc = snap.documents[0];
            const nodes = doc.nodes;
            const layout = doc.layout;

            for (let i = 0; i < layout.nodeIndex.length; i++) {
                const nodeIdx = layout.nodeIndex[i];
                const backendNodeId = nodes.backendNodeId[nodeIdx];
                const bounds = layout.bounds[i]; // [x, y, width, height]
                boundsMap[backendNodeId] = { x: bounds[0], y: bounds[1], width: bounds[2], height: bounds[3] };
            }
        }

        const interactiveRoles = ['button', 'link', 'textbox', 'searchbox', 'combobox', 'menuitem', 'tab', 'checkbox', 'radio', 'switch', 'slider'];
        let idCounter = 0;

        if (axTree && axTree.nodes) {
            for (const node of axTree.nodes) {
                if (!node.role) continue;
                const role = node.role.value;

                let isInteractive = interactiveRoles.includes(role);
                // Expand interactivity check
                if (!isInteractive && node.properties) {
                    const focusableProp = node.properties.find(p => p.name === 'focusable');
                    if (focusableProp && focusableProp.value && focusableProp.value.value === true) {
                        isInteractive = true;
                    }
                }

                if (isInteractive && node.backendDOMNodeId && boundsMap[node.backendDOMNodeId]) {
                    const bounds = boundsMap[node.backendDOMNodeId];

                    const isVisible = (
                        bounds.width > 0 && bounds.height > 0 &&
                        bounds.y + bounds.height > viewport.pageY &&
                        bounds.y < viewport.pageY + viewport.clientHeight &&
                        bounds.x + bounds.width > viewport.pageX &&
                        bounds.x < viewport.pageX + viewport.clientWidth
                    );

                    if (isVisible) {
                        let text = node.name ? node.name.value : '';
                        uiElements.push({
                            id: String(idCounter++),
                            type: role,
                            text: text,
                            bounds: bounds,
                            backendNodeId: node.backendDOMNodeId
                        });
                    }
                }
            }
        }

        // Store bounds for native execution
        latestDomBounds = {};
        uiElements.forEach(el => {
            if (el.bounds) {
                latestDomBounds[el.id] = el.bounds;
            }
        });

        // 3. Capture SoM Screenshot using CDP
        sendTelemetryLog(`Capturing Set-of-Mark (SoM) screenshot via CDP...`);

        try {
            await new Promise((resolve) => {
                chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.INJECT_SOM, elements: uiElements }, resolve);
            });
            await new Promise(r => setTimeout(r, 100));

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
            }
        } catch (cdpError) {
            sendTelemetryLog(`CDP Screenshot Error: ${cdpError.message}`);
        }
    } catch (e) {
        sendTelemetryLog(`Native DOM extraction or CDP Error: ${e.message}`);
        throw e;
    } finally {
        await new Promise((resolve) => {
            chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.REMOVE_SOM }, resolve);
        });
        chrome.debugger.detach({ tabId: tab.id }, () => {
            const err = chrome.runtime.lastError;
        });
    }

    return { success: true, ui_elements: uiElements, screenshot_base64: screenshotBase64, tabId: tab.id };
}

async function handleExecuteNativeAction(payload) {
    const action = payload.action;
    sendTelemetryLog(`Executing Native Action: ${action.action}`);

    let [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab) {
        [tab] = await chrome.tabs.query({ active: true });
    }
    if (!tab) throw new Error("No active tab found");

    if (action.action === "NAVIGATE") {
        await new Promise((resolve, reject) => {
            chrome.tabs.update(tab.id, { url: action.url }, (updatedTab) => {
                if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                else resolve();
            });
        });
        return { success: true };
    } else if (action.action === "OPEN_TAB") {
        await new Promise((resolve, reject) => {
            chrome.tabs.create({ url: action.url }, (newTab) => {
                if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                else resolve();
            });
        });
        return { success: true };
    } else if (action.action === "CLICK" || action.action === "TYPE") {
        const bounds = latestDomBounds[action.target_id];
        if (!bounds) {
            // Fallback to content script if bounds not found
            sendTelemetryLog(`Bounds not found for ID ${action.target_id}, falling back to content script execution.`);
            return await new Promise((resolve, reject) => {
                chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.EXECUTE_ACTION, payload: action }, (res) => {
                    if (chrome.runtime.lastError) resolve({error: chrome.runtime.lastError.message});
                    else if (res && res.error) reject(new Error(res.error));
                    else resolve(res);
                });
            });
        }

        // Calculate center point for CDP click
        const x = Math.round(bounds.x + bounds.width / 2);
        const y = Math.round(bounds.y + bounds.height / 2);

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

            // Native Click
            await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
                    type: 'mousePressed', x: x, y: y, button: 'left', clickCount: 1
                }, (result) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(result);
                });
            });
            await new Promise(r => setTimeout(r, 50)); // Tiny delay
            await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
                    type: 'mouseReleased', x: x, y: y, button: 'left', clickCount: 1
                }, (result) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(result);
                });
            });

            if (action.action === "TYPE") {
                await new Promise(r => setTimeout(r, 100));

                // Natively insert text
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.insertText', {
                        text: action.text
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });

                // Optionally press enter or trigger events
            }

        } finally {
            chrome.debugger.detach({ tabId: tab.id }, () => {
                const err = chrome.runtime.lastError;
            });
        }
        return { success: true };
    } else {
        // SCROLL, PRESS_KEY, WAIT_FOR, HOVER, REPLY fall back to content script
        return await new Promise((resolve, reject) => {
            chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.EXECUTE_ACTION, payload: action }, (res) => {
                if (chrome.runtime.lastError) resolve({error: chrome.runtime.lastError.message});
                else if (res && res.error) reject(new Error(res.error));
                else resolve(res);
            });
        });
    }
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

    // Extract target URL from command text if available
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
                if (chrome.runtime.lastError) {
                    return reject(new Error(chrome.runtime.lastError.message));
                }
                const listener = (tabId, info) => {
                    if (tabId === updatedTab.id && info.status === 'complete') {
                        chrome.tabs.onUpdated.removeListener(listener);
                        chrome.tabs.onRemoved.removeListener(removedListener);
                        resolve(updatedTab);
                    }
                };
                const removedListener = (tabId) => {
                    if (tabId === updatedTab.id) {
                        chrome.tabs.onUpdated.removeListener(listener);
                        chrome.tabs.onRemoved.removeListener(removedListener);
                        reject(new Error("Tab closed before loading completed"));
                    }
                };
                chrome.tabs.onUpdated.addListener(listener);
                chrome.tabs.onRemoved.addListener(removedListener);
            });
        }).catch(err => {
            sendTelemetryLog(`Navigation error: ${err.message}`);
            throw err;
        });
    } else if (isRestrictedUrl(tab.url)) {
        sendTelemetryLog(`Restricted tab detected: ${tab.url}. Handling dynamic navigation.`);
        const urlToOpen = targetUrl || 'https://www.google.com';
        sendTelemetryLog(`Opening new tab: ${urlToOpen}`);
        tab = await new Promise((resolve, reject) => {
            chrome.tabs.create({ url: urlToOpen }, (newTab) => {
                if (chrome.runtime.lastError) {
                    return reject(new Error(chrome.runtime.lastError.message));
                }
                const listener = (tabId, info) => {
                    if (tabId === newTab.id && info.status === 'complete') {
                        chrome.tabs.onUpdated.removeListener(listener);
                        chrome.tabs.onRemoved.removeListener(removedListener);
                        resolve(newTab);
                    }
                };
                const removedListener = (tabId) => {
                    if (tabId === newTab.id) {
                        chrome.tabs.onUpdated.removeListener(listener);
                        chrome.tabs.onRemoved.removeListener(removedListener);
                        reject(new Error("Tab closed before loading completed"));
                    }
                };
                chrome.tabs.onUpdated.addListener(listener);
                chrome.tabs.onRemoved.addListener(removedListener);
            });
        }).catch(err => {
            sendTelemetryLog(`Navigation error: ${err.message}`);
            throw err;
        });
    }

    let iteration = 0;
    let totalActionsExecuted = 0;
    const threadHistory = [];

    while (true) {
        sendTelemetryLog(`Iteration ${iteration + 1}...`);

        // 2. Extract DOM Natively via CDP
        sendTelemetryLog(`Extracting DOM from tab natively via CDP...`);
        const uiElements = [];
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

            await new Promise(r => chrome.debugger.sendCommand({ tabId: tab.id }, "DOMSnapshot.enable", {}, r));
            const axTree = await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, "Accessibility.getFullAXTree", {}, (res) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(res);
                });
            });
            const snap = await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, "DOMSnapshot.captureSnapshot", {
                    computedStyles: [],
                    includePaintOrder: true,
                    includeDOMRects: true
                }, (res) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(res);
                });
            });

            const layoutMetrics = await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, "Page.getLayoutMetrics", {}, (res) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(res);
                });
            });

            const viewport = layoutMetrics.layoutViewport || { pageX: 0, pageY: 0, clientWidth: 1920, clientHeight: 1080 };
            const boundsMap = {};

            if (snap && snap.documents && snap.documents.length > 0) {
                const doc = snap.documents[0];
                const nodes = doc.nodes;
                const layout = doc.layout;

                for (let i = 0; i < layout.nodeIndex.length; i++) {
                    const nodeIdx = layout.nodeIndex[i];
                    const backendNodeId = nodes.backendNodeId[nodeIdx];
                    const bounds = layout.bounds[i]; // [x, y, width, height]
                    boundsMap[backendNodeId] = { x: bounds[0], y: bounds[1], width: bounds[2], height: bounds[3] };
                }
            }

            const interactiveRoles = ['button', 'link', 'textbox', 'searchbox', 'combobox', 'menuitem', 'tab', 'checkbox', 'radio', 'switch', 'slider'];
            let idCounter = 0;

            if (axTree && axTree.nodes) {
                for (const node of axTree.nodes) {
                    if (!node.role) continue;
                    const role = node.role.value;

                    let isInteractive = interactiveRoles.includes(role);
                    // Expand interactivity check
                    if (!isInteractive && node.properties) {
                        const focusableProp = node.properties.find(p => p.name === 'focusable');
                        if (focusableProp && focusableProp.value && focusableProp.value.value === true) {
                            isInteractive = true;
                        }
                    }

                    if (isInteractive && node.backendDOMNodeId && boundsMap[node.backendDOMNodeId]) {
                        const bounds = boundsMap[node.backendDOMNodeId];

                        const isVisible = (
                            bounds.width > 0 && bounds.height > 0 &&
                            bounds.y + bounds.height > viewport.pageY &&
                            bounds.y < viewport.pageY + viewport.clientHeight &&
                            bounds.x + bounds.width > viewport.pageX &&
                            bounds.x < viewport.pageX + viewport.clientWidth
                        );

                        if (isVisible) {
                            let text = node.name ? node.name.value : '';
                            uiElements.push({
                                id: String(idCounter++),
                                type: role,
                                text: text,
                                bounds: bounds,
                                backendNodeId: node.backendDOMNodeId
                            });
                        }
                    }
                }
            }

            sendTelemetryLog(`Extracted ${uiElements.length} elements from DOM.`);

            // 3. Capture SoM Screenshot using CDP
            sendTelemetryLog(`Capturing Set-of-Mark (SoM) screenshot via CDP...`);

            try {
                // Inject SoM overlay
                await new Promise((resolve) => {
                    chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.INJECT_SOM, elements: uiElements }, resolve);
                });

                // Give the browser a moment to render the SVG overlay
                await new Promise(r => setTimeout(r, 100));

                // Capture Screenshot
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
                    sendTelemetryLog(`Successfully captured SoM screenshot.`);
                } else {
                    sendTelemetryLog(`Failed to capture screenshot data.`);
                }

            } catch (cdpError) {
                sendTelemetryLog(`CDP Screenshot Error: ${cdpError.message}`);
            }

        } catch (e) {
            sendTelemetryLog(`Native DOM extraction failed: ${e.message}`);
            throw e;
        } finally {
            // Always remove the SoM overlay immediately
            await new Promise((resolve) => {
                chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.REMOVE_SOM }, resolve);
            });

            // Detach debugger
            chrome.debugger.detach({ tabId: tab.id }, () => {
                // Ignore detach errors since it might have already been detached
                const err = chrome.runtime.lastError;
            });
        }

        // 4. Send to Backend
        sendTelemetryLog(`Sending payload to Backend...`);
        const token = await getAuthToken();
        if (!token) {
            throw new Error("User is not authenticated. Please log in.");
        }

        const apiPayload = {
            audio_base64: audioBase64,
            command_text: commandText,
            ui_elements: uiElements,
            screenshot_base64: screenshotBase64,
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
                sendTelemetryLog(`Executing [${i+1}/${actions.length}]: ${action.action} ${action.target_id ? 'target ' + action.target_id : (action.url ? 'url ' + action.url : '')}`);

                if (action.action === "NAVIGATE") {
                    await new Promise((resolve, reject) => {
                        chrome.tabs.update(tab.id, { url: action.url }, (updatedTab) => {
                            if (chrome.runtime.lastError) {
                                reject(new Error(chrome.runtime.lastError.message));
                            } else {
                                // Wait for tab to load
                                const listener = (tabId, info) => {
                                    if (tabId === updatedTab.id && info.status === 'complete') {
                                        chrome.tabs.onUpdated.removeListener(listener);
                                        resolve();
                                    }
                                };
                                chrome.tabs.onUpdated.addListener(listener);
                            }
                        });
                    });
                    totalActionsExecuted++;
                    await new Promise(r => setTimeout(r, 1000));
                } else if (action.action === "OPEN_TAB") {
                    await new Promise((resolve, reject) => {
                        chrome.tabs.create({ url: action.url }, (newTab) => {
                            if (chrome.runtime.lastError) {
                                reject(new Error(chrome.runtime.lastError.message));
                            } else {
                                tab = newTab; // Update the active tab reference to the new tab
                                const listener = (tabId, info) => {
                                    if (tabId === newTab.id && info.status === 'complete') {
                                        chrome.tabs.onUpdated.removeListener(listener);
                                        resolve();
                                    }
                                };
                                chrome.tabs.onUpdated.addListener(listener);
                            }
                        });
                    });
                    totalActionsExecuted++;
                    await new Promise(r => setTimeout(r, 1000));
                } else {
                    // Send other actions (CLICK, TYPE, SCROLL, PRESS_KEY, HOVER, WAIT_FOR) to the content script
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
                }
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
