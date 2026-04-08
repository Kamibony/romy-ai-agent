// extension/content/network_tracker.js

// Initialize global variables to track active requests and the timestamp of the last request
window.__romyActiveRequests = window.__romyActiveRequests || 0;
window.__romyLastRequestTime = window.__romyLastRequestTime || Date.now();

// Utility functions to update tracking
function incrementRequestCount() {
    window.__romyActiveRequests++;
    window.__romyLastRequestTime = Date.now();
    // Broadcast state to ISOLATED world (e.g. content_script.js)
    window.dispatchEvent(new CustomEvent('RomyNetworkStatusUpdate', { detail: { activeRequests: window.__romyActiveRequests } }));
}

function decrementRequestCount() {
    window.__romyActiveRequests = Math.max(0, window.__romyActiveRequests - 1);
    window.__romyLastRequestTime = Date.now();
    // Broadcast state to ISOLATED world (e.g. content_script.js)
    window.dispatchEvent(new CustomEvent('RomyNetworkStatusUpdate', { detail: { activeRequests: window.__romyActiveRequests } }));
}

// Intercept XMLHttpRequest
const originalXhrOpen = window.XMLHttpRequest.prototype.open;
const originalXhrSend = window.XMLHttpRequest.prototype.send;

window.XMLHttpRequest.prototype.open = function() {
    this._romyTracked = true;
    this._romyDecremented = false; // Flag to prevent double-decrementing
    return originalXhrOpen.apply(this, arguments);
};

window.XMLHttpRequest.prototype.send = function() {
    if (this._romyTracked) {
        incrementRequestCount();

        const handleCompletion = () => {
            if (!this._romyDecremented) {
                this._romyDecremented = true;
                decrementRequestCount();
            }
        };

        // Attach event listeners to decrement on completion.
        // loadend fires after load, error, or abort.
        this.addEventListener('loadend', handleCompletion, false);
        this.addEventListener('error', handleCompletion, false);
        this.addEventListener('abort', handleCompletion, false);
        this.addEventListener('timeout', handleCompletion, false);
    }
    return originalXhrSend.apply(this, arguments);
};

// Intercept Fetch API
const originalFetch = window.fetch;

window.fetch = async function(...args) {
    incrementRequestCount();

    try {
        const response = await originalFetch.apply(this, args);
        // Note: This only tracks until the response headers are received.
        // Reading the actual response body (e.g. via response.json() or response.text())
        // is not tracked by this mechanism. For extremely large payloads,
        // the page might be considered "stable" before the payload is fully parsed.
        return response;
    } finally {
        decrementRequestCount();
    }
};

console.log("Romy Network Tracker initialized. Intercepting XHR and Fetch.");

