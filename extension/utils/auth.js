export const AUTH_KEYS = {
    TOKEN: 'firebaseToken',
    EXPIRATION: 'tokenExpiration'
};

export async function getToken() {
    return new Promise((resolve) => {
        chrome.storage.local.get([AUTH_KEYS.TOKEN], (result) => {
            resolve(result[AUTH_KEYS.TOKEN] || null);
        });
    });
}

export async function setToken(token, expiresInSecs) {
    const expiration = Date.now() + (expiresInSecs * 1000);
    return new Promise((resolve) => {
        chrome.storage.local.set({
            [AUTH_KEYS.TOKEN]: token,
            [AUTH_KEYS.EXPIRATION]: expiration
        }, () => resolve());
    });
}