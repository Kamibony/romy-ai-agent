document.addEventListener('DOMContentLoaded', () => {
    const btnRequest = document.getElementById('btn-request');
    const statusText = document.getElementById('status');

    btnRequest.addEventListener('click', async () => {
        try {
            // Request microphone access
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            // Stop tracks immediately to release the microphone device
            stream.getTracks().forEach(track => track.stop());

            statusText.textContent = "Permission granted! You can close this tab and return to the Romy Agent popup.";
            statusText.className = "success";
            btnRequest.style.display = 'none';
        } catch (error) {
            console.error("Microphone access denied or error:", error);
            statusText.textContent = "Permission denied. Please ensure you allow microphone access in your browser settings.";
            statusText.className = "error";
        }
    });
});