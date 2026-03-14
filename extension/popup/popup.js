import { MESSAGE_TYPES } from '../utils/message_types.js';
import { getAuthToken, login, logout, getCurrentUser } from '../utils/auth.js';
import { db, doc, getDoc } from '../utils/firebase-init.js';

let isRecording = false;
let userRole = null;

document.addEventListener('DOMContentLoaded', async () => {
    const btnRecord = document.getElementById('btn-record');
    const btnSubmit = document.getElementById('btn-submit');
    const textInput = document.getElementById('text-input');
    const statusText = document.getElementById('status-text');
    const telemetryLog = document.getElementById('telemetry-log');

    const loginContainer = document.getElementById('login-container');
    const controlsContainer = document.getElementById('controls-container');
    const btnLogin = document.getElementById('btn-login');
    const btnLogout = document.getElementById('btn-logout');
    const loginEmail = document.getElementById('login-email');
    const loginPassword = document.getElementById('login-password');
    const loginError = document.getElementById('login-error');

    async function checkAuthState() {
        const token = await getAuthToken();
        if (token) {
            loginContainer.style.display = 'none';
            controlsContainer.style.display = 'flex';
            statusText.innerText = "Ready to assist";

            // Check user role for telemetry visibility
            const user = await getCurrentUser();
            if (user) {
                try {
                    const userDoc = await getDoc(doc(db, "users", user.uid));
                    if (userDoc.exists()) {
                        userRole = userDoc.data().role;
                    }
                } catch (e) {
                    console.log("Could not fetch user role", e);
                }
            }

            // Sync state from background script
            chrome.runtime.sendMessage({ type: MESSAGE_TYPES.GET_STATE }, (response) => {
                if (response) {
                    isRecording = response.isRecording;
                    if (isRecording) {
                        btnRecord.classList.add('recording');
                        btnRecord.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-square"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>';
                        statusText.innerText = "Listening...";
                    } else if (response.isProcessing) {
                        statusText.innerText = "Processing...";
                        btnRecord.disabled = true;
                        btnSubmit.disabled = true;
                        textInput.disabled = true;
                    }
                }
            });

        } else {
            loginContainer.style.display = 'block';
            controlsContainer.style.display = 'none';
            statusText.innerText = "Please log in";
            userRole = null;
        }
    }

    await checkAuthState();

    btnLogin.addEventListener('click', async () => {
        const email = loginEmail.value.trim();
        const password = loginPassword.value;
        if (!email || !password) {
            loginError.innerText = "Please enter email and password.";
            loginError.style.display = 'block';
            return;
        }

        btnLogin.disabled = true;
        btnLogin.innerText = "Logging in...";
        loginError.style.display = 'none';

        try {
            await login(email, password);
            loginEmail.value = '';
            loginPassword.value = '';
            await checkAuthState();
        } catch (error) {
            loginError.innerText = error.message || "Login failed.";
            loginError.style.display = 'block';
        } finally {
            btnLogin.disabled = false;
            btnLogin.innerText = "Login";
        }
    });

    btnLogout.addEventListener('click', async () => {
        await logout();
        await checkAuthState();
    });

    btnRecord.addEventListener('click', async () => {
        if (!isRecording) {
            await startRecording();
        } else {
            await stopRecordingAndSend();
        }
    });

    btnSubmit.addEventListener('click', () => {
        const text = textInput.value.trim();
        if (text) {
            statusText.innerText = "Processing...";
            sendCommand({ audioBase64: "", commandText: text });
            textInput.value = "";
        }
    });

    async function startRecording() {
        try {
            // Check microphone permission before proceeding
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                stream.getTracks().forEach(track => track.stop());
            } catch (e) {
                console.warn("Microphone access denied. Opening setup page.");
                chrome.tabs.create({ url: chrome.runtime.getURL("setup/setup.html") });
                statusText.innerText = "Please grant mic access.";
                return;
            }

            const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.REQUEST_START_RECORDING });
            if (response && response.error) {
                throw new Error(response.error);
            }
            isRecording = true;
            btnRecord.classList.add('recording');
            btnRecord.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-square"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>';
            statusText.innerText = "Listening...";
        } catch (err) {
            console.error("Microphone access denied or error:", err);
            statusText.innerText = "Microphone error. Check permissions.";
        }
    }

    async function stopRecordingAndSend() {
        if (isRecording) {
            isRecording = false;
            btnRecord.classList.remove('recording');
            btnRecord.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-mic"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>';
            statusText.innerText = "Processing...";

            try {
                const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.REQUEST_STOP_RECORDING });
                if (response && response.error) {
                    throw new Error(response.error);
                }
                const base64Audio = response.audioBase64;
                if (!base64Audio) {
                    statusText.innerText = "No audio captured.";
                }
                // Processing is now handled autonomously by the background script when audio is captured.
            } catch (err) {
                console.error("Error stopping recording:", err);
                statusText.innerText = "Error capturing audio.";
            }
        }
    }

    function appendTelemetry(message) {
        if (telemetryLog && (userRole === 'Admin' || userRole === 'Partner')) {
            telemetryLog.style.display = 'block';
            const entry = document.createElement('div');
            entry.textContent = `> ${message}`;
            telemetryLog.appendChild(entry);
            telemetryLog.scrollTop = telemetryLog.scrollHeight;
        }
    }

    chrome.runtime.onMessage.addListener((message) => {
        if (message.type === MESSAGE_TYPES.TELEMETRY_LOG) {
            appendTelemetry(message.payload);
        } else if (message.type === MESSAGE_TYPES.EXECUTION_COMPLETE) {
            if (message.result && message.result.helpNeeded) {
                statusText.innerText = "Awaiting human input on mobile.";
            } else {
                statusText.innerText = "Ready to assist";
            }
            btnRecord.disabled = false;
            btnSubmit.disabled = false;
            textInput.disabled = false;
        }
    });

    function sendCommand(payload) {
        btnRecord.disabled = true;
        btnSubmit.disabled = true;
        textInput.disabled = true;

        if (telemetryLog) {
            telemetryLog.innerHTML = '';
            telemetryLog.style.display = 'none';
        }

        chrome.runtime.sendMessage({ type: MESSAGE_TYPES.PROCESS_COMMAND, payload }, (response) => {
            btnRecord.disabled = false;
            btnSubmit.disabled = false;
            textInput.disabled = false;

            if (chrome.runtime.lastError) {
                console.error(chrome.runtime.lastError);
                statusText.innerText = "Connection error.";
            } else if (response && response.error) {
                statusText.innerText = "Execution error.";
            } else if (response && response.helpNeeded) {
                statusText.innerText = "Awaiting human input on mobile.";
            } else if (response && response.actionsExecuted !== undefined) {
                statusText.innerText = `Success. Actions executed: ${response.actionsExecuted}`;
            } else {
                statusText.innerText = "Ready to assist";
            }
        });
    }

});