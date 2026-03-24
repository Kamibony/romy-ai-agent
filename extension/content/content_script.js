// MESSAGE_TYPES is available globally via window.MESSAGE_TYPES loaded from manifest.json
console.log("Romy Content Script loaded.");

// Teleoperation: Listen for physical human clicks
document.addEventListener('click', (e) => {
    if (!e.isTrusted) return; // Only intercept genuine human physical clicks

    // Ignore clicks on our own Set-of-Mark chips if any
    if (e.target && e.target.classList && e.target.classList.contains('romy-som-label')) {
        return;
    }

    // MANDATORY FIX: strictly ignore clicks on localhost or firebaseapp.com dashboards
    const hostname = window.location.hostname;
    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname.endsWith('firebaseapp.com')) {
        return;
    }

    try {
        const xpath = getXPathForElement(e.target);
        if (xpath) {
            console.log("Ghost Click Intercepted:", xpath);
            const dpr = window.devicePixelRatio || 1;
            // Send to background script which passes it to orchestrator
            chrome.runtime.sendMessage({
                type: window.MESSAGE_TYPES.HUMAN_CLICK_INTERCEPTED,
                payload: {
                    type: "CLICK",
                    xpath: xpath,
                    x: e.clientX,
                    y: e.clientY,
                    dpr: dpr
                }
            }).catch(err => {
                console.warn("Failed to send ghost click to background (maybe disconnected):", err);
            });
        }
    } catch (err) {
        console.error("Error computing XPath for ghost click:", err);
    }
}, true); // use capture phase so we get it before frameworks might eat it

function getXPathForElement(element) {
    if (element.id !== '')
        return 'id("' + element.id + '")';
    if (element === document.body)
        return element.tagName.toLowerCase();

    var ix = 0;
    var siblings = element.parentNode ? element.parentNode.childNodes : [];
    for (var i = 0; i < siblings.length; i++) {
        var sibling = siblings[i];
        if (sibling === element)
            return getXPathForElement(element.parentNode) + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
        if (sibling.nodeType === 1 && sibling.tagName === element.tagName)
            ix++;
    }
    return null;
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    switch (request.type) {
        case window.MESSAGE_TYPES.REQUEST_DOM_MAP:
            handleRequestDomMap(sendResponse);
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
