import re

with open('extension/background/service_worker.js', 'r') as f:
    content = f.read()

# Modify the command handler in localBridgeWs.onmessage
old_handler = """                    let result;
                    try {
                        if (cmd.action_type === 'GET_STATE') {
                            result = await handleGetState(cmd);
                        } else if (cmd.action_type === 'EXECUTE_ACTION') {
                            result = await handleExecuteNativeAction(cmd);
                        } else {
                            result = { success: false, error: "Unknown action_type." };
                        }
                    } catch (err) {
                        console.error("Error processing command internally:", err);
                        result = { success: false, error: err.message || String(err) };
                    }

                    // Send result back
                    await sendChunkedMessage(localBridgeWs, 'result', result);"""

new_handler = """                    let result;
                    try {
                        if (cmd.action_type === 'GET_STATE') {
                            result = await handleGetState(cmd);
                            // Send via HTTP POST
                            try {
                                const response = await fetch('http://127.0.0.1:8766/api/state', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify(result)
                                });
                                if (!response.ok) {
                                    throw new Error(`HTTP Error: ${response.status}`);
                                }
                            } catch (httpErr) {
                                console.error("HTTP State Transfer failed, falling back to WebSocket chunking:", httpErr);
                                await sendChunkedMessage(localBridgeWs, 'result', result);
                            }
                        } else if (cmd.action_type === 'EXECUTE_ACTION') {
                            result = await handleExecuteNativeAction(cmd);
                            await sendChunkedMessage(localBridgeWs, 'result', result);
                        } else {
                            result = { success: false, error: "Unknown action_type." };
                            await sendChunkedMessage(localBridgeWs, 'result', result);
                        }
                    } catch (err) {
                        console.error("Error processing command internally:", err);
                        result = { success: false, error: err.message || String(err) };
                        // Even if it failed, we must return the result via WebSocket or HTTP so Python doesn't hang
                        if (cmd.action_type === 'GET_STATE') {
                             try {
                                await fetch('http://127.0.0.1:8766/api/state', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify(result)
                                });
                             } catch(e) {
                                await sendChunkedMessage(localBridgeWs, 'result', result);
                             }
                        } else {
                            await sendChunkedMessage(localBridgeWs, 'result', result);
                        }
                    }"""

content = content.replace(old_handler, new_handler)

with open('extension/background/service_worker.js', 'w') as f:
    f.write(content)
