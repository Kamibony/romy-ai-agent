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

function handleRequestDomMap(sendResponse) {
    try {
        const elements = window.RomyDomMapper.extractUIElements();
        sendResponse({ elements });
    } catch (error) {
        sendResponse({ error: error.message });
    }
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
                // Natively set the value
                typeTarget.value = action.text;
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