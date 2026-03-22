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
                        } else if (cmd.action_type === 'EXECUTE_ACTION') {
                            result = await handleExecuteNativeAction(cmd);
                        } else {
                            result = { success: false, error: "Unknown action_type." };
                        }
                    } catch (err) {
                        console.error("Error processing command internally:", err);
                        result = { success: false, error: err.message || String(err) };
                    }

                    // Send result back
                    await sendChunkedMessage(localBridgeWs, 'result', result);
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
    const { commandText } = payload;
    sendTelemetryLog(`Requesting WEB State (Vision-First)...`);

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

    // 2. Capture Clean Screenshot Natively via CDP
    sendTelemetryLog(`Capturing pure screenshot via CDP...`);
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
    } else if (action.action === "RESET_VIEW") {
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
            // Try pressing Escape first
            await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', {
                    type: 'keyDown', key: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27, macCharCode: 27
                }, (result) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(result);
                });
            });
            await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', {
                    type: 'keyUp', key: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27, macCharCode: 27
                }, (result) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(result);
                });
            });
            await new Promise(r => setTimeout(r, 100));
            // Also dispatch a click outside at (1,1)
            await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
                    type: 'mousePressed', x: 1, y: 1, button: 'left', clickCount: 1
                }, (result) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(result);
                });
            });
            await new Promise(r => setTimeout(r, 50));
            await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
                    type: 'mouseReleased', x: 1, y: 1, button: 'left', clickCount: 1
                }, (result) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(result);
                });
            });
        } finally {
            chrome.debugger.detach({ tabId: tab.id }, () => {
                const err = chrome.runtime.lastError;
            });
        }
        return { success: true };
    } else if (action.action === "CLICK" || action.action === "TYPE" || action.action === "PASTE" || action.action === "HOVER") {
        if (!action.coordinates || !Array.isArray(action.coordinates) || action.coordinates.length !== 2) {
            sendTelemetryLog(`Coordinates missing for action ${action.action}. Cannot execute native action.`);
            return { success: false, error: "Coordinates missing for vision-based action." };
        }

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

            // Adjust coordinates for device pixel ratio
            const evaluateDprResult = await new Promise((resolve) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Runtime.evaluate', {
                    expression: 'window.devicePixelRatio || 1',
                    returnByValue: true
                }, (result) => {
                    if (chrome.runtime.lastError) resolve({ result: { value: 1 } });
                    else resolve(result);
                });
            });
            const dpr = evaluateDprResult?.result?.value || 1;

            let x = Math.round(action.coordinates[0] / dpr);
            let y = Math.round(action.coordinates[1] / dpr);

            if (action.action === "HOVER") {
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
                        type: 'mouseMoved', x: x, y: y
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });
            } else {
                // Native Click using coordinates
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
                        type: 'mousePressed', x: x, y: y, button: 'left', clickCount: 1
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });
                await new Promise(r => setTimeout(r, 50));
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchMouseEvent', {
                        type: 'mouseReleased', x: x, y: y, button: 'left', clickCount: 1
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });
            }

            if (action.action === "TYPE") {
                await new Promise(r => setTimeout(r, 100));

                // Dispatch individual key events to properly trigger React/Vue synthetic events
                for (let i = 0; i < action.text.length; i++) {
                    const char = action.text[i];
                    await new Promise((resolve, reject) => {
                        chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', {
                            type: 'keyDown',
                            text: char,
                            unmodifiedText: char,
                            key: char
                        }, (result) => {
                            if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                            else resolve(result);
                        });
                    });

                    await new Promise((resolve, reject) => {
                        chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', {
                            type: 'keyUp',
                            key: char
                        }, (result) => {
                            if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                            else resolve(result);
                        });
                    });
                }
            } else if (action.action === "PASTE") {
                await new Promise(r => setTimeout(r, 100));

                // Select all via Ctrl+A / Cmd+A
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', {
                        type: 'keyDown',
                        modifiers: 2, // Ctrl (or Cmd on Mac)
                        key: 'a'
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', {
                        type: 'keyUp',
                        modifiers: 2,
                        key: 'a'
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });

                // Delete selection
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', {
                        type: 'keyDown',
                        key: 'Backspace'
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', {
                        type: 'keyUp',
                        key: 'Backspace'
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });

                // Direct value override and dispatch input event
                await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Runtime.evaluate', {
                        expression: `
                            (function() {
                                let el = document.activeElement;
                                if (!el) return;
                                let desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value") ||
                                           Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
                                if (desc && desc.set) {
                                    desc.set.call(el, ${JSON.stringify(action.text)});
                                } else {
                                    el.value = ${JSON.stringify(action.text)};
                                }
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            })();
                        `,
                        returnByValue: true
                    }, (result) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(result);
                    });
                });
            }

        } finally {
            chrome.debugger.detach({ tabId: tab.id }, () => {
                const err = chrome.runtime.lastError;
            });
        }
        return { success: true };
    } else if (action.action === "EXECUTE_JS") {
        sendTelemetryLog(`Executing JS in ISOLATED world via CDP...`);
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

            // Create an isolated world
            const isolatedWorldResult = await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Page.createIsolatedWorld', {
                    frameId: tab.id.toString(), // Usually works, or omit and rely on main frame implicitly if we could, but let's just use default frame by enabling Page first
                    worldName: "ROMY_ISOLATED"
                }, (result) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(result);
                });
            }).catch(async (e) => {
                // If frameId fails, try enabling page and getting frame tree
                await new Promise((resolve) => chrome.debugger.sendCommand({ tabId: tab.id }, 'Page.enable', {}, resolve));
                const frameTree = await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Page.getFrameTree', {}, (res) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(res);
                    });
                });
                return await new Promise((resolve, reject) => {
                    chrome.debugger.sendCommand({ tabId: tab.id }, 'Page.createIsolatedWorld', {
                        frameId: frameTree.frameTree.frame.id,
                        worldName: "ROMY_ISOLATED"
                    }, (res) => {
                        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                        else resolve(res);
                    });
                });
            });

            const contextId = isolatedWorldResult.executionContextId;

            const evaluateResult = await new Promise((resolve, reject) => {
                chrome.debugger.sendCommand({ tabId: tab.id }, 'Runtime.evaluate', {
                    expression: action.code,
                    contextId: contextId,
                    returnByValue: true
                }, (result) => {
                    if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
                    else resolve(result);
                });
            });

            let resultValue = null;
            if (evaluateResult && evaluateResult.result) {
                if (evaluateResult.result.type === 'object' || evaluateResult.result.type === 'string' || evaluateResult.result.type === 'number' || evaluateResult.result.type === 'boolean') {
                    resultValue = evaluateResult.result.value;
                } else if (evaluateResult.result.unserializableValue) {
                    resultValue = evaluateResult.result.unserializableValue;
                } else if (evaluateResult.result.subtype === 'error') {
                    resultValue = evaluateResult.result.description;
                }
            }

            return { success: true, result: resultValue };
        } catch (jsErr) {
            sendTelemetryLog(`Failed to execute JS via CDP: ${jsErr.message}`);
            return { success: false, error: jsErr.message };
        } finally {
            chrome.debugger.detach({ tabId: tab.id }, () => {
                const err = chrome.runtime.lastError;
            });
        }
    } else {
        // SCROLL, PRESS_KEY, WAIT_FOR, REPLY fall back to content script
        return await new Promise((resolve, reject) => {
            chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.EXECUTE_ACTION, payload: action }, (res) => {
                if (chrome.runtime.lastError) resolve({error: chrome.runtime.lastError.message});
                else if (res && res.error) reject(new Error(res.error));
                else resolve(res);
            });
        });
    }
}
