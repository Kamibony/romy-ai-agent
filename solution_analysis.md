# Analysis for Async Pipeline & High-Performance State Execution

## 1. Decoupled State Triggering

The primary problem is that `handleGetState` is executed synchronously via `await` inside the WebSocket `onmessage` listener of `service_worker.js`. If `handleGetState` takes over 30s (Chrome Extension max execution time limit for service worker event loop blocks or inactivity limits), the service worker is killed and Python times out.

**Solution:**
We must decouple the start of state extraction from its completion.
1. When Python sends a `GET_STATE` request, the Service Worker should immediately start `handleGetState` in the background (without `await`ing it inside the `onmessage` handler).
2. The Service Worker should send an immediate "ACK" back through the WebSocket so Python knows the process started.
3. Once `handleGetState` finishes, it will post the state payload directly to the REST API (`http://127.0.0.1:8764/api/state`) and optionally send a tiny "Ready" signal via WebSocket.

In Python (`client/agent.py`), the agent must be modified to wait asynchronously for the state to arrive at the REST API after receiving the initial ACK from the WebSocket. Currently, Python `bridge.delegate_command` waits up to 60s for the final result over the WebSocket or HTTP payload. We can adjust the bridge (in `client/local_bridge.py`) or the agent to block until `LATEST_STATE_PAYLOAD` is populated, ensuring we don't hold the websocket open for the entire extraction.

## 2. State "Push" vs. "Pull"

Python's `delegate_command` (in `client/local_bridge.py` and `client/agent.py`) currently waits for a WebSocket result.
We need a pure "Push" architecture from the extension:
- Python sends `{ "action_type": "GET_STATE" }` via WS.
- Extension WS `onmessage` synchronously returns `{ "type": "result", "payload": { "status": "started" } }`.
- Extension asynchronously executes `handleGetState`.
- Upon completion, Extension pushes massive JSON to `http://127.0.0.1:8764/api/state` via HTTP POST.
- Extension sends `{ "type": "result", "payload": { "success": true, "state_delivered_via_http": true } }` over WS.
- Python logic in `client/agent.py` already checks `LATEST_STATE_PAYLOAD` if it receives `state_delivered_via_http`.

We need to make sure the WebSocket `onmessage` handler doesn't block:

```javascript
// In service_worker.js
if (cmd.action_type === 'GET_STATE') {
    // 1. Send immediate ACK
    if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'ack',
            payload: { status: 'started' }
        }));
    }
    // 2. Start background process without awaiting
    handleGetState(cmd).then(async (result) => {
        try {
            const res = await fetch('http://127.0.0.1:8764/api/state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(result)
            });
            if (!res.ok) throw new Error(`Local API responded with ${res.status}`);
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'result',
                    payload: { success: true, state_delivered_via_http: true }
                }));
            }
        } catch (httpErr) {
            console.error("Failed to post state to local API:", httpErr);
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'result',
                    payload: { success: false, error: "Failed to post state via HTTP: " + httpErr.message }
                }));
            }
        }
    }).catch(err => {
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'result', payload: { success: false, error: err.message } }));
        }
    });
}
```

However, we also need to adjust `client/local_bridge.py` since it is expecting the `result` packet directly. If it receives an `ack`, it should wait for the `result`.

## 3. Performance Optimization (dom_mapper.js)

`dom_mapper.js` does a lot of work that takes time on complex DOMs like Yahoo Finance:
- `getAllNodes`: traverses every single node, checking computed styles, checking visibility, deduplicating.
- `window.getComputedStyle(node)` is extremely slow when called on thousands of nodes because it forces browser layout recalculation.
- The "Phase 1: Visibility Check" calls `getBoundingClientRect()` and `window.getComputedStyle(node)` on all elements sequentially.

**Optimization ideas:**
1. **IntersectionObserver**: For visibility checks, this is asynchronous and very fast, but harder to use synchronously inside `chrome.scripting.executeScript`.
2. **Batching**: Only run `getComputedStyle` on nodes that passed a basic fast check (like tag type or class name) instead of all nodes.
3. **Filter early**: Instead of `querySelectorAll('*')`, we should only select elements that match our interactive locators + information nodes, and skip SVGs/Paths/Head/Style/Script tags.
   - `querySelectorAll('a, button, input, select, textarea, p, h1, h2, h3, h4, h5, h6, td, th, li, dd, dt, [role], [onclick], [class*="btn"], [class*="button"]')`
   - This immediately prunes thousands of generic `div` and `span` elements from the layout-thrashing phase.

**Specific fix for `dom_mapper.js`:**
Replace `querySelectorAll('*')` in `getAllNodes` with a targeted `querySelectorAll` using a compiled list of selectors.
Also, we can avoid `getComputedStyle` in `isInteractive` if the element already matches the explicit locators. We can move the generic `cursor: pointer` check to be a last resort only for elements that aren't already explicitly interactive.

## 4. Tab Awareness (Duplicate tabs)

`service_worker.js` `handleGetState`:
```javascript
        if (!tab) {
            let [activeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
            if (!activeTab) {
                [activeTab] = await chrome.tabs.query({ active: true });
            }
            if (!activeTab) throw new Error("No active tab found");
            tab = activeTab;
            activeSessionTabId = tab.id;
        }
```
The "Recovery Loop" issue: If state extraction fails, the iteration count might reset to 0 in Python (because the agent crashes or fails the subtask and loops).
If `iteration === 0`, `service_worker.js` does:
```javascript
    if (iteration === 0) {
        // Start of a new session: always create a new tab
        const urlToOpen = targetUrl || 'https://www.google.com';
        // ... chrome.tabs.create ...
```
This is why duplicate tabs happen. We should check if `targetUrl` is ALREADY open in any tab, or if `activeSessionTabId` is STILL valid and matches the domain, before forcing a new tab.

**Tab duplication fix:**
If `iteration === 0` but we already have an `activeSessionTabId` and its URL matches `targetUrl`, we shouldn't open a new tab. Or better yet, we can query all tabs to see if `targetUrl` is already open, and just focus it.

Let's write a script to check `client/local_bridge.py` since we need to modify it.
