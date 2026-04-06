import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../main.dart'; // To get the firebaseInitProvider

final authStateProvider = StreamProvider<User?>((ref) {
  // We only start listening if Firebase is initialized.
  final isFirebaseInit = ref.watch(firebaseInitProvider).value ?? false;
  if (!isFirebaseInit) {
    return const Stream.empty();
  }
  return FirebaseAuth.instance.authStateChanges();
});

final authTokenProvider = FutureProvider<String?>((ref) async {
  // Directly fetch the token to ensure we always try to get the latest without relying on the stream's first emission.
  // Wait for Firebase init first.
  final isFirebaseInit = await ref.watch(firebaseInitProvider.future);
  if (!isFirebaseInit) return null;

  final user = FirebaseAuth.instance.currentUser;
  if (user != null) {
    return await user.getIdToken();
  }
  return null;
});
