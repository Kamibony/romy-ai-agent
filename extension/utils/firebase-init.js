import { initializeApp } from './firebase-app.js';
import { getAuth } from './firebase-auth.js';
import { getFirestore, collection, query, where, onSnapshot, doc, updateDoc } from './firebase-firestore.js';
import { firebaseConfig } from './firebase-config.js';

// Centralized Firebase initialization
export const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);

// Re-export firestore utilities for service worker to use
export { collection, query, where, onSnapshot, doc, updateDoc };

// Export instances to be used across the extension
export default {
    app,
    auth,
    db
};
