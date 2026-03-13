import { signInWithEmailAndPassword, signOut, onAuthStateChanged, getIdToken } from './firebase-auth.js';
import { app, auth } from './firebase-init.js';

export { app, auth };

export async function login(email, password) {
    try {
        const userCredential = await signInWithEmailAndPassword(auth, email, password);
        return userCredential.user;
    } catch (error) {
        console.error("Firebase login error:", error);
        throw error;
    }
}

export async function logout() {
    try {
        await signOut(auth);
    } catch (error) {
        console.error("Firebase logout error:", error);
        throw error;
    }
}

export async function getAuthToken() {
    return new Promise((resolve) => {
        const unsubscribe = onAuthStateChanged(auth, async (user) => {
            unsubscribe(); // we only want the current state
            if (user) {
                try {
                    // Force refresh if needed, otherwise returns cached valid token
                    const token = await getIdToken(user);
                    resolve(token);
                } catch (error) {
                    console.error("Error getting ID token:", error);
                    resolve(null);
                }
            } else {
                resolve(null);
            }
        });
    });
}

export async function getCurrentUser() {
    return new Promise((resolve) => {
        const unsubscribe = onAuthStateChanged(auth, async (user) => {
            unsubscribe();
            resolve(user);
        });
    });
}
