import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, kIsWeb, TargetPlatform;

/// Default [FirebaseOptions] for use with your Firebase apps.
///
/// Example:
/// ```dart
/// import 'firebase_options.dart';
/// // ...
/// await Firebase.initializeApp(
///   options: DefaultFirebaseOptions.currentPlatform,
/// );
/// ```
class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    if (kIsWeb) {
      return web;
    }
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return android;
      case TargetPlatform.iOS:
        return ios;
      case TargetPlatform.macOS:
        return macos;
      case TargetPlatform.windows:
        return windows;
      case TargetPlatform.linux:
        throw UnsupportedError(
          'DefaultFirebaseOptions have not been configured for linux - '
          'you can reconfigure this by running the FlutterFire CLI again.',
        );
      default:
        throw UnsupportedError(
          'DefaultFirebaseOptions are not supported for this platform.',
        );
    }
  }

  static const FirebaseOptions web = FirebaseOptions(
    apiKey: String.fromEnvironment('FIREBASE_API_KEY', defaultValue: 'dummy-api-key'),
    appId: String.fromEnvironment('FIREBASE_APP_ID', defaultValue: '1:1234567890:web:1234567890abcdef'),
    messagingSenderId: String.fromEnvironment('FIREBASE_MESSAGING_SENDER_ID', defaultValue: '1234567890'),
    projectId: String.fromEnvironment('FIREBASE_PROJECT_ID', defaultValue: 'dummy-project-id'),
    authDomain: String.fromEnvironment('FIREBASE_AUTH_DOMAIN', defaultValue: 'dummy-project-id.firebaseapp.com'),
    storageBucket: String.fromEnvironment('FIREBASE_STORAGE_BUCKET', defaultValue: 'dummy-project-id.appspot.com'),
  );

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: String.fromEnvironment('FIREBASE_API_KEY', defaultValue: 'dummy-api-key'),
    appId: String.fromEnvironment('FIREBASE_APP_ID', defaultValue: '1:1234567890:android:1234567890abcdef'),
    messagingSenderId: String.fromEnvironment('FIREBASE_MESSAGING_SENDER_ID', defaultValue: '1234567890'),
    projectId: String.fromEnvironment('FIREBASE_PROJECT_ID', defaultValue: 'dummy-project-id'),
    storageBucket: String.fromEnvironment('FIREBASE_STORAGE_BUCKET', defaultValue: 'dummy-project-id.appspot.com'),
  );

  static const FirebaseOptions ios = FirebaseOptions(
    apiKey: String.fromEnvironment('FIREBASE_API_KEY', defaultValue: 'dummy-api-key'),
    appId: String.fromEnvironment('FIREBASE_APP_ID', defaultValue: '1:1234567890:ios:1234567890abcdef'),
    messagingSenderId: String.fromEnvironment('FIREBASE_MESSAGING_SENDER_ID', defaultValue: '1234567890'),
    projectId: String.fromEnvironment('FIREBASE_PROJECT_ID', defaultValue: 'dummy-project-id'),
    storageBucket: String.fromEnvironment('FIREBASE_STORAGE_BUCKET', defaultValue: 'dummy-project-id.appspot.com'),
    iosBundleId: String.fromEnvironment('FIREBASE_IOS_BUNDLE_ID', defaultValue: 'com.example.dashboard'),
  );

  static const FirebaseOptions macos = FirebaseOptions(
    apiKey: String.fromEnvironment('FIREBASE_API_KEY', defaultValue: 'dummy-api-key'),
    appId: String.fromEnvironment('FIREBASE_APP_ID', defaultValue: '1:1234567890:ios:1234567890abcdef'),
    messagingSenderId: String.fromEnvironment('FIREBASE_MESSAGING_SENDER_ID', defaultValue: '1234567890'),
    projectId: String.fromEnvironment('FIREBASE_PROJECT_ID', defaultValue: 'dummy-project-id'),
    storageBucket: String.fromEnvironment('FIREBASE_STORAGE_BUCKET', defaultValue: 'dummy-project-id.appspot.com'),
    iosBundleId: String.fromEnvironment('FIREBASE_IOS_BUNDLE_ID', defaultValue: 'com.example.dashboard'),
  );

  static const FirebaseOptions windows = FirebaseOptions(
    apiKey: String.fromEnvironment('FIREBASE_API_KEY', defaultValue: 'dummy-api-key'),
    appId: String.fromEnvironment('FIREBASE_APP_ID', defaultValue: '1:1234567890:web:1234567890abcdef'),
    messagingSenderId: String.fromEnvironment('FIREBASE_MESSAGING_SENDER_ID', defaultValue: '1234567890'),
    projectId: String.fromEnvironment('FIREBASE_PROJECT_ID', defaultValue: 'dummy-project-id'),
    authDomain: String.fromEnvironment('FIREBASE_AUTH_DOMAIN', defaultValue: 'dummy-project-id.firebaseapp.com'),
    storageBucket: String.fromEnvironment('FIREBASE_STORAGE_BUCKET', defaultValue: 'dummy-project-id.appspot.com'),
  );
}
