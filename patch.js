class CDPLifecycleManager {
    constructor() {
        this.attachedTabs = new Set();
        chrome.debugger.onDetach.addListener((source, reason) => {
            if (source.tabId) {
                this.attachedTabs.delete(source.tabId);
                sendTelemetryLog(`[CDP] Session detached for tab ${source.tabId}. Reason: ${reason}`);
            }
        });
    }

    async attach(tabId) {
        if (this.attachedTabs.has(tabId)) {
            return;
        }
        return new Promise((resolve, reject) => {
            chrome.debugger.attach({ tabId: tabId }, "1.3", () => {
                const err = chrome.runtime.lastError;
                if (err && !err.message.includes("Cannot attach to this target")) {
                    reject(new Error(err.message));
                } else {
                    this.attachedTabs.add(tabId);
                    resolve();
                }
            });
        });
    }

    async detach(tabId) {
        if (!this.attachedTabs.has(tabId)) {
            return;
        }
        return new Promise((resolve) => {
            chrome.debugger.detach({ tabId: tabId }, () => {
                const err = chrome.runtime.lastError; // Ignore errors
                this.attachedTabs.delete(tabId);
                resolve();
            });
        });
    }

    async sendCommand(tabId, method, params = {}) {
        if (!this.attachedTabs.has(tabId)) {
            throw new Error(`[CDP] Cannot send command ${method} to unattached tab ${tabId}`);
        }
        return new Promise((resolve, reject) => {
            chrome.debugger.sendCommand({ tabId: tabId }, method, params, (result) => {
                const err = chrome.runtime.lastError;
                if (err) {
                    // Check if it's a detachment error during the call
                    if (err.message.includes("Session with given id not found") || err.message.includes("Cannot send command to a detached session")) {
                         this.attachedTabs.delete(tabId);
                         reject(new Error(`[CDP] Session detached while sending ${method}: ${err.message}`));
                    } else {
                         reject(new Error(`[CDP Error] ${method}: ${err.message}`));
                    }
                } else {
                    resolve(result);
                }
            });
        });
    }
}
const cdpManager = new CDPLifecycleManager();
