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
    try {
        switch (action.action) {
            case "CLICK":
                const clickTarget = document.querySelector(`[data-romy-id="${action.target_id}"]`);
                if (!clickTarget) throw new Error(`Target ID ${action.target_id} not found.`);
                clickTarget.click();
                break;
            case "TYPE":
                const typeTarget = document.querySelector(`[data-romy-id="${action.target_id}"]`);
                if (!typeTarget) throw new Error(`Target ID ${action.target_id} not found.`);

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