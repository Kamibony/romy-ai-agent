// MESSAGE_TYPES is available globally via window.MESSAGE_TYPES loaded from manifest.json
console.log("Romy Content Script loaded.");

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    switch (request.type) {
        case window.MESSAGE_TYPES.REQUEST_DOM_MAP:
            handleRequestDomMap(sendResponse);
            return true; // async
        case window.MESSAGE_TYPES.EXECUTE_ACTION:
            handleExecuteAction(request.payload, sendResponse);
            return true; // async
    }
});

async function handleRequestDomMap(sendResponse) {
    await waitForDomStability(1000, 5000);
    try {
        const elements = window.RomyDomMapper.extractUIElements();
        sendResponse({ elements });
    } catch (error) {
        sendResponse({ error: error.message });
    }
}

/**
 * Returns a Promise that resolves when the DOM is considered "stable".
 * Stability is defined as no new DOM mutations for `debounceMs` milliseconds.
 * If stability isn't reached within `timeoutMs`, the Promise resolves anyway as a fallback.
 */
function waitForDomStability(debounceMs = 1000, timeoutMs = 5000) {
    return new Promise((resolve) => {
        let debounceTimer;
        let timeoutTimer;
        let observer;

        const cleanup = () => {
            if (observer) observer.disconnect();
            if (debounceTimer) clearTimeout(debounceTimer);
            if (timeoutTimer) clearTimeout(timeoutTimer);
        };

        const onStable = () => {
            cleanup();
            console.log("DOM considered stable (mutations ceased).");
            resolve();
        };

        const onTimeout = () => {
            cleanup();
            console.log("DOM stability check timed out. Proceeding as 'ready enough'.");
            resolve();
        };

        timeoutTimer = setTimeout(onTimeout, timeoutMs);

        debounceTimer = setTimeout(onStable, debounceMs);

        observer = new MutationObserver(() => {
            if (debounceTimer) clearTimeout(debounceTimer);
            debounceTimer = setTimeout(onStable, debounceMs);
        });

        observer.observe(document.body || document.documentElement, {
            childList: true,
            subtree: true,
            attributes: true
        });
    });
}

function handleExecuteAction(action, sendResponse) {
    console.log("Executing Action:", action);

    function getElementByXPath(xpath) {
        try {
            return document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        } catch (e) {
            return null;
        }
    }

    function findElement(action) {
        let el = null;
        if (action.coordinates && Array.isArray(action.coordinates) && action.coordinates.length === 2) {
            const x = Math.round(action.coordinates[0]);
            const y = Math.round(action.coordinates[1]);
            el = document.elementFromPoint(x, y);
            if (el) {
                console.log(`Element found using coordinates (${x}, ${y})`);
                return el;
            }
        }
        if (action.target_id) {
            el = document.querySelector(`[data-romy-id="${action.target_id}"]`);
            if (el) return el;
        }
        if (action.xpath) {
            console.log(`Falling back to XPath: ${action.xpath}`);
            el = getElementByXPath(action.xpath);
        }
        return el;
    }

    try {
        switch (action.action) {
            case "CLICK":
                const clickTarget = findElement(action);
                if (!clickTarget) throw new Error(`Target not found for action using coordinates, ID, or XPath.`);
                clickTarget.click();
                break;
            case "TYPE":
                const typeTarget = findElement(action);
                if (!typeTarget) throw new Error(`Target not found for action using coordinates, ID, or XPath.`);

                typeTarget.focus();

                // Set the value natively bypassing React/Vue's value tracking
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype,
                    "value"
                );
                const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype,
                    "value"
                );

                if (nativeInputValueSetter && nativeInputValueSetter.set && typeTarget instanceof HTMLInputElement) {
                    nativeInputValueSetter.set.call(typeTarget, action.text);
                } else if (nativeTextAreaValueSetter && nativeTextAreaValueSetter.set && typeTarget instanceof HTMLTextAreaElement) {
                    nativeTextAreaValueSetter.set.call(typeTarget, action.text);
                } else {
                    typeTarget.value = action.text;
                }

                // Dispatch events to trigger React/Angular bindings
                typeTarget.dispatchEvent(new Event("input", { bubbles: true }));
                typeTarget.dispatchEvent(new Event("change", { bubbles: true }));
                break;
            case "SCROLL":
                // Standard scroll fallback
                window.scrollBy({ top: action.direction === 'down' ? window.innerHeight : -window.innerHeight, behavior: 'smooth' });
                break;
            case "PRESS_KEY":
                const targetElem = document.activeElement || document.body;
                targetElem.dispatchEvent(new KeyboardEvent('keydown', { key: action.key, bubbles: true }));
                targetElem.dispatchEvent(new KeyboardEvent('keypress', { key: action.key, bubbles: true }));
                targetElem.dispatchEvent(new KeyboardEvent('keyup', { key: action.key, bubbles: true }));
                break;
            case "HOVER":
                const hoverTarget = findElement(action);
                if (!hoverTarget) throw new Error(`Target not found for action using coordinates, ID, or XPath.`);
                hoverTarget.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                hoverTarget.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                break;
            case "WAIT_FOR":
                if (!action.selector) throw new Error(`WAIT_FOR requires a selector.`);
                const maxWaitMs = (action.max_wait_seconds || 5) * 1000;

                let isDone = false;
                const checkExist = setInterval(() => {
                    if (document.querySelector(action.selector) && !isDone) {
                        isDone = true;
                        clearInterval(checkExist);
                        sendResponse({ success: true });
                    }
                }, 500); // Check every 500ms

                setTimeout(() => {
                    if (!isDone) {
                        isDone = true;
                        clearInterval(checkExist);
                        sendResponse({ success: true }); // We still return success and just continue after timeout
                    }
                }, maxWaitMs);
                return; // Return here to avoid immediate sendResponse below
            case "REPLY":
                // Basic implementation (or system toast fallback logic)
                alert(`Agent says: ${action.text}`);
                break;
            case "ASK_HUMAN":
                // Pass back to background worker or popup
                console.warn("Human intervention required:", action.reason);
                alert(`Agent asks: ${action.reason}`);
                break;
            default:
                throw new Error(`Unknown action type: ${action.action}`);
        }
        sendResponse({ success: true });
    } catch (error) {
        console.error("Execution error:", error);
        sendResponse({ error: error.message });
    }
}
