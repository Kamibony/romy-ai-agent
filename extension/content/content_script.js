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
        case window.MESSAGE_TYPES.INJECT_SOM:
            handleInjectSom(sendResponse);
            return true;
        case window.MESSAGE_TYPES.REMOVE_SOM:
            handleRemoveSom(sendResponse);
            return true;
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

    function findElement(target_id, xpath) {
        let el = document.querySelector(`[data-romy-id="${target_id}"]`);
        if (!el && xpath) {
            console.log(`Target ID ${target_id} not found, falling back to XPath: ${xpath}`);
            el = getElementByXPath(xpath);
        }
        return el;
    }

    try {
        switch (action.action) {
            case "CLICK":
                const clickTarget = findElement(action.target_id, action.xpath);
                if (!clickTarget) throw new Error(`Target ID ${action.target_id} (and XPath ${action.xpath || 'N/A'}) not found.`);
                clickTarget.click();
                break;
            case "TYPE":
                const typeTarget = findElement(action.target_id, action.xpath);
                if (!typeTarget) throw new Error(`Target ID ${action.target_id} (and XPath ${action.xpath || 'N/A'}) not found.`);

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
                const hoverTarget = findElement(action.target_id, action.xpath);
                if (!hoverTarget) throw new Error(`Target ID ${action.target_id} (and XPath ${action.xpath || 'N/A'}) not found.`);
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
// --- Set-of-Mark (SoM) Logic ---
function handleInjectSom(sendResponse, payload) {
    try {
        // Remove existing overlay if present
        handleRemoveSom(() => {});

        // Use native elements passed from background worker, or fallback to JS mapper
        const elements = payload && payload.elements ? payload.elements : window.RomyDomMapper.extractUIElements();

        const overlayContainer = document.createElement('div');
        overlayContainer.id = 'romy-som-overlay-container';
        // Make sure it sits on top of everything but doesn't block interactions
        Object.assign(overlayContainer.style, {
            all: 'initial',
            position: 'fixed',
            top: '0',
            left: '0',
            width: '100vw',
            height: '100vh',
            pointerEvents: 'none',
            zIndex: '2147483647', // Max z-index
            margin: '0',
            padding: '0',
            border: 'none',
            overflow: 'visible'
        });

        elements.forEach(el => {
            let viewportTop, viewportLeft, width, height;

            if (el.bounds) {
                // CDP bounds and dom_mapper bounds are absolute page coordinates
                viewportTop = el.bounds.y - window.scrollY;
                viewportLeft = el.bounds.x - window.scrollX;
                width = el.bounds.width;
                height = el.bounds.height;
            } else {
                const target = document.querySelector(`[data-romy-id="${el.id}"]`);
                if (!target) return;

                const rect = target.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0 || rect.bottom <= 0 || rect.top >= window.innerHeight || rect.right <= 0 || rect.left >= window.innerWidth) {
                    return;
                }

                const computedStyle = window.getComputedStyle(target);
                if (computedStyle.visibility === 'hidden' || computedStyle.display === 'none' || computedStyle.opacity === '0') {
                    return;
                }

                viewportTop = rect.top;
                viewportLeft = rect.left;
                width = rect.width;
                height = rect.height;
            }

            // Only draw if it's within or partially within the viewport
            if (width === 0 || height === 0 || viewportTop >= window.innerHeight || viewportLeft >= window.innerWidth || (viewportTop + height) <= 0 || (viewportLeft + width) <= 0) {
                return;
            }

            const tag = document.createElement('div');
            tag.textContent = el.id;
            Object.assign(tag.style, {
                position: 'absolute',
                top: `${viewportTop}px`,
                left: `${viewportLeft}px`,
                backgroundColor: 'red',
                color: 'white',
                padding: '1px 3px',
                fontSize: '10px',
                fontWeight: 'bold',
                borderRadius: '3px',
                border: '1px solid white',
                pointerEvents: 'none',
                boxShadow: '0 0 2px black',
                zIndex: '2147483647',
                // Add slight offset so it doesn't cover the exact corner completely if needed
                transform: 'translate(-50%, -50%)',
                fontFamily: 'sans-serif'
            });

            // Optional: Draw a bounding box frame
            const box = document.createElement('div');
            Object.assign(box.style, {
                position: 'absolute',
                top: `${viewportTop}px`,
                left: `${viewportLeft}px`,
                width: `${width}px`,
                height: `${height}px`,
                border: '1px dashed red',
                pointerEvents: 'none',
                zIndex: '2147483646',
                boxSizing: 'border-box',
                backgroundColor: 'rgba(255, 0, 0, 0.05)'
            });

            overlayContainer.appendChild(box);
            overlayContainer.appendChild(tag);
        });

        (document.documentElement || document.body).appendChild(overlayContainer);
        sendResponse({ success: true, count: elements.length });
    } catch (error) {
        console.error("Failed to inject SoM overlay:", error);
        sendResponse({ error: error.message });
    }
}

function handleRemoveSom(sendResponse) {
    try {
        const overlay = document.getElementById('romy-som-overlay-container');
        if (overlay) {
            overlay.remove();
        }
        sendResponse({ success: true });
    } catch (error) {
        console.error("Failed to remove SoM overlay:", error);
        sendResponse({ error: error.message });
    }
}
