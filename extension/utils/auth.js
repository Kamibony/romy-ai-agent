import { initializeApp } from './firebase-app.js';
import { getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged, getIdToken } from './firebase-auth.js';
import { firebaseConfig } from './firebase-config.js';

// Initialize Firebase App
const app = initializeApp(firebaseConfig);

// Initialize Firebase Auth
const auth = getAuth(app);

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
