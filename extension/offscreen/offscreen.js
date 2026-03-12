import { MESSAGE_TYPES } from '../utils/message_types.js';

let mediaRecorder = null;
let audioChunks = [];
let mediaStream = null;

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === MESSAGE_TYPES.START_RECORDING) {
        startRecording().then(() => {
            sendResponse({ success: true });
        }).catch((err) => {
            console.error("Failed to start recording:", err);
            sendResponse({ error: err.message });
        });
        return true;
    } else if (request.type === MESSAGE_TYPES.STOP_RECORDING) {
        stopRecording().then((base64Audio) => {
            sendResponse({ audioBase64: base64Audio });
        }).catch((err) => {
            console.error("Failed to stop recording:", err);
            sendResponse({ error: err.message });
        });
        return true;
    }
});

async function startRecording() {
    if (mediaRecorder && mediaRecorder.state === "recording") {
        throw new Error("Already recording");
    }

    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(mediaStream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };

        mediaRecorder.start();
    } catch (err) {
        console.error("Microphone access error in offscreen document:", err);
        throw err;
    }
}

async function stopRecording() {
    if (!mediaRecorder || mediaRecorder.state !== "recording") {
        throw new Error("Not recording");
    }

    return new Promise((resolve, reject) => {
        mediaRecorder.onstop = async () => {
            try {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                const base64Audio = await blobToBase64(audioBlob);

                // Cleanup
                audioChunks = [];
                if (mediaStream) {
                    mediaStream.getTracks().forEach(track => track.stop());
                    mediaStream = null;
                }

                resolve(base64Audio);
            } catch (err) {
                reject(err);
            }
        };
        mediaRecorder.stop();
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
