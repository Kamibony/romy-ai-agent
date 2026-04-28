// MESSAGE_TYPES is available globally via window.MESSAGE_TYPES loaded from manifest.json
console.log("Romy Content Script loaded.");

// Track active network requests across the ISOLATED world boundary
let currentActiveRequests = 0;
window.addEventListener('RomyNetworkStatusUpdate', (e) => {
    if (e.detail && typeof e.detail.activeRequests === 'number') {
        currentActiveRequests = e.detail.activeRequests;
    }
});

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
        const dpr = window.devicePixelRatio || 1;

        let xpath = "Unknown element";
        try {
            if (e.target) {
                let text = e.target.innerText || e.target.value || e.target.getAttribute('aria-label') || "";
                if (text && text.length > 50) text = text.substring(0, 50) + "...";
                let tag = e.target.tagName ? e.target.tagName.toLowerCase() : "";
                if (tag) {
                     xpath = tag + (text ? ` with text "${text.trim()}"` : "");

                     // Semantic ID logic for ghost clicks
                     let id = e.target.id;
                     if (id && id.length <= 20 && !/\d{4,}/.test(id) && !/[a-z0-9]{8}-[a-z0-9]{4}/i.test(id)) {
                         xpath += ` (id: #${id})`;
                     } else if (e.target.hasAttribute('data-testid')) {
                         xpath += ` (data-testid: ${e.target.getAttribute('data-testid')})`;
                     } else if (e.target.hasAttribute('role')) {
                         xpath += ` (role: ${e.target.getAttribute('role')})`;
                     } else if (e.target.hasAttribute('aria-label') && !text.includes(e.target.getAttribute('aria-label'))) {
                         xpath += ` (aria-label: ${e.target.getAttribute('aria-label')})`;
                     }
                }
            }
        } catch (xpathErr) {
            console.error("Error getting simple xpath:", xpathErr);
        }

        console.log("Ghost Click Intercepted at", e.clientX, e.clientY, "Element:", xpath);
        // Send to background script which passes it to orchestrator
        chrome.runtime.sendMessage({
            type: window.MESSAGE_TYPES.HUMAN_CLICK_INTERCEPTED,
            payload: {
                type: "CLICK",
                x: e.clientX,
                y: e.clientY,
                xpath: xpath,
                dpr: dpr
            }
        }).catch(err => {
            console.error("Failed to send ghost click to background (maybe disconnected):", err);
        });
    } catch (err) {
        console.error("Error computing coordinates for ghost click:", err);
    }
}, true); // use capture phase so we get it before frameworks might eat it

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    switch (request.type) {
        case window.MESSAGE_TYPES.REQUEST_DOM_MAP:
            handleRequestDomMap(sendResponse);
            return true; // async
        case 'WAIT_FOR_STABILITY':
            handleWaitForStability(request, sendResponse);
            return true; // async
    }
});

async function handleWaitForStability(request, sendResponse) {
    await waitForDomStability(request.debounceMs || 500, request.timeoutMs || 2500);
    sendResponse({ success: true });
}

async function handleRequestDomMap(sendResponse) {
    await waitForDomStability(500, 2500);
    try {
        const elements = window.RomyDomMapper.extractUIElements();
        sendResponse({ elements });
    } catch (error) {
        sendResponse({ error: error.message });
    }
}

/**
 * Returns a Promise that resolves when the DOM and Network are considered "stable".
 * Stability is defined as no new DOM mutations AND zero active network requests for `debounceMs`.
 * If stability isn't reached within `timeoutMs`, the Promise resolves anyway as a fallback.
 */
function waitForDomStability(debounceMs = 500, timeoutMs = 2500) {
    return new Promise((resolve) => {
        let debounceTimer;
        let timeoutTimer;
        let intervalTimer;
        let observer;

        const cleanup = () => {
            if (observer) observer.disconnect();
            if (debounceTimer) clearTimeout(debounceTimer);
            if (timeoutTimer) clearTimeout(timeoutTimer);
            if (intervalTimer) clearInterval(intervalTimer);
        };

        const checkStability = () => {
            if (currentActiveRequests === 0) {
                cleanup();
                console.log("DOM and Network considered stable.");
                resolve();
            } else {
                if (debounceTimer) clearTimeout(debounceTimer);
                debounceTimer = setTimeout(checkStability, debounceMs);
            }
        };

        const onTimeout = () => {
            cleanup();
            console.log("Stability check timed out. Proceeding as 'ready enough'.");
            resolve();
        };

        timeoutTimer = setTimeout(onTimeout, timeoutMs);

        debounceTimer = setTimeout(checkStability, debounceMs);

        observer = new MutationObserver(() => {
            if (debounceTimer) clearTimeout(debounceTimer);
            debounceTimer = setTimeout(checkStability, debounceMs);
        });

        observer.observe(document.body || document.documentElement, {
            childList: true,
            subtree: true,
            attributes: true
        });

        intervalTimer = setInterval(() => {
            if (currentActiveRequests !== 0) {
                if (debounceTimer) clearTimeout(debounceTimer);
                debounceTimer = setTimeout(checkStability, debounceMs);
            }
        }, 100);
    });
}
