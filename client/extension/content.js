// content.js
let ws = null;
let elementMap = new Map(); // str_id -> Element
let nextElementId = 1;

function connectWebSocket() {
    ws = new WebSocket('ws://localhost:8765');

    ws.onopen = () => {
        console.log("Connected to Romy AI Agent WebSocket.");
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.action === "SCAN") {
                const ui_elements = scanDOM();
                ws.send(JSON.stringify({ type: "SCAN_RESULT", ui_elements: ui_elements }));
            } else if (data.action === "CLICK") {
                executeClick(data.target_id);
            } else if (data.action === "TYPE") {
                executeType(data.target_id, data.text);
            } else if (data.action === "SCROLL") {
                executeScroll(data.direction);
            }
        } catch (e) {
            console.error("Error processing message:", e);
        }
    };

    ws.onclose = () => {
        console.log("Disconnected from Romy AI Agent WebSocket. Reconnecting in 3s...");
        setTimeout(() => {
            if (document.visibilityState === 'visible') {
                connectWebSocket();
            }
        }, 3000);
    };

    ws.onerror = (error) => {
        console.error("WebSocket Error:", error);
    };
}

function scanDOM() {
    elementMap.clear();
    nextElementId = 1;
    const ui_elements = [];

    const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
    const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);

    const elements = document.querySelectorAll('button, a, input, select, textarea, [role="button"], [role="link"], [onclick], .btn, .button, [class*="btn"]');

    elements.forEach(el => {
        // Check visibility
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0 || rect.top >= vh || rect.left >= vw || rect.bottom <= 0 || rect.right <= 0) {
            return;
        }

        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            return;
        }

        const tag_name = el.tagName.toLowerCase();
        let text = el.innerText ? el.innerText.trim() : "";
        if (!text) {
            text = el.value || el.name || el.id || "";
        }

        const center_x = Math.round(rect.left + rect.width / 2);
        const center_y = Math.round(rect.top + rect.height / 2);

        // Viewport pruning (only within viewport)
        if (center_x >= 0 && center_x <= vw && center_y >= 0 && center_y <= vh) {
            const element_str_id = String(nextElementId++);
            elementMap.set(element_str_id, el);
            ui_elements.push({
                "id": element_str_id,
                "type": tag_name,
                "name": text,
                "x": center_x,
                "y": center_y
            });
        }
    });

    return ui_elements;
}

function executeClick(target_id) {
    const el = elementMap.get(target_id);
    if (el) {
        console.log(`Clicking element ${target_id}`);
        el.click();
        ws.send(JSON.stringify({ type: "ACTION_RESULT", status: "success", action: "CLICK" }));
    } else {
        console.error(`Element ${target_id} not found for click`);
        ws.send(JSON.stringify({ type: "ACTION_RESULT", status: "error", message: `Element ${target_id} not found` }));
    }
}

function executeType(target_id, text) {
    const el = elementMap.get(target_id);
    if (el) {
        console.log(`Typing into element ${target_id}: ${text}`);
        el.focus();
        // Clear value first if input/textarea
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
            const setter = el.tagName === 'INPUT' ? nativeInputValueSetter : nativeTextAreaValueSetter;

            if (setter) {
                setter.call(el, text);
            } else {
                el.value = text;
            }

            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
            // For other contenteditable elements
            el.innerText = text;
        }
        ws.send(JSON.stringify({ type: "ACTION_RESULT", status: "success", action: "TYPE" }));
    } else {
        console.error(`Element ${target_id} not found for type`);
        ws.send(JSON.stringify({ type: "ACTION_RESULT", status: "error", message: `Element ${target_id} not found` }));
    }
}

function executeScroll(direction) {
    console.log(`Scrolling ${direction}`);
    const amount = direction === "down" ? 500 : -500;
    window.scrollBy({ top: amount, left: 0, behavior: 'smooth' });
    ws.send(JSON.stringify({ type: "ACTION_RESULT", status: "success", action: "SCROLL" }));
}

// Ensure it only runs if the document is visible to avoid hidden background tabs
if (document.visibilityState === 'visible') {
    connectWebSocket();
} else {
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && !ws) {
            connectWebSocket();
        }
    });
}
