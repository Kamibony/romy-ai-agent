import { MESSAGE_TYPES } from '../utils/message_types.js';
import { getAuthToken, login, logout } from '../utils/auth.js';

let mediaRecorder;
let audioChunks = [];
let isRecording = false;

document.addEventListener('DOMContentLoaded', async () => {
    const btnRecord = document.getElementById('btn-record');
    const btnSubmit = document.getElementById('btn-submit');
    const textInput = document.getElementById('text-input');
    const statusText = document.getElementById('status-text');

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
        } else {
            loginContainer.style.display = 'block';
            controlsContainer.style.display = 'none';
            statusText.innerText = "Please log in";
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

    btnRecord.addEventListener('mousedown', async () => {
        if (!isRecording) await startRecording();
    });

    btnRecord.addEventListener('mouseup', async () => {
        if (isRecording) await stopRecordingAndSend();
    });

    // Mobile fallback (touch events)
    btnRecord.addEventListener('touchstart', async (e) => {
        e.preventDefault();
        if (!isRecording) await startRecording();
    });

    btnRecord.addEventListener('touchend', async (e) => {
        e.preventDefault();
        if (isRecording) await stopRecordingAndSend();
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
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) audioChunks.push(event.data);
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                const base64Audio = await blobToBase64(audioBlob);
                audioChunks = []; // Reset

                // Keep stream tracks clean
                stream.getTracks().forEach(track => track.stop());

                sendCommand({ audioBase64: base64Audio, commandText: "" });
            };

            mediaRecorder.start();
            isRecording = true;
            btnRecord.classList.add('recording');
            btnRecord.innerText = "Recording...";
            statusText.innerText = "Listening...";

        } catch (err) {
            console.error("Microphone access denied or error:", err);
            statusText.innerText = "Microphone error. Check permissions.";
        }
    }

    async function stopRecordingAndSend() {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
            isRecording = false;
            btnRecord.classList.remove('recording');
            btnRecord.innerText = "Hold to Record";
            statusText.innerText = "Processing...";
        }
    }

    function sendCommand(payload) {
        btnRecord.disabled = true;
        btnSubmit.disabled = true;
        textInput.disabled = true;

        chrome.runtime.sendMessage({ type: MESSAGE_TYPES.PROCESS_COMMAND, payload }, (response) => {
            btnRecord.disabled = false;
            btnSubmit.disabled = false;
            textInput.disabled = false;

            if (chrome.runtime.lastError) {
                console.error(chrome.runtime.lastError);
                statusText.innerText = "Connection error.";
            } else if (response.error) {
                statusText.innerText = "Execution error.";
            } else {
                statusText.innerText = `Success. Actions executed: ${response.actionsExecuted}`;
            }
        });
    }

    function blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.readAsDataURL(blob);
            reader.onloadend = () => {
                const base64data = reader.result.split(',')[1];
                resolve(base64data);
            };
            reader.onerror = reject;
        });
    }
});