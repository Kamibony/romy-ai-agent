import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:firebase_auth/firebase_auth.dart';

import '../main.dart';

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(ref);
});

class ApiClient {

  String get _baseUrl {
    const backendPort = String.fromEnvironment('BACKEND_PORT', defaultValue: '8000');
    return 'http://127.0.0.1:$backendPort';
  }

  final Ref _ref;
  final http.Client _client = http.Client();

  ApiClient(this._ref);

  Future<Map<String, String>> _getHeaders() async {
    final headers = <String, String>{'Content-Type': 'application/json'};

    // Fetch token dynamically to handle refresh and user changes
    try {
      final isFirebaseInit = await _ref.read(firebaseInitProvider.future);
      if (isFirebaseInit) {
        final user = FirebaseAuth.instance.currentUser;
        if (user != null) {
          final token = await user.getIdToken();
          headers['Authorization'] = 'Bearer $token';
        } else {
          headers['Authorization'] = 'Bearer local-dev-token';
        }
      } else {
        headers['Authorization'] = 'Bearer local-dev-token';
      }
    } catch (e) {
      headers['Authorization'] = 'Bearer local-dev-token';
    }

    return headers;
  }

  Future<http.Response> get(String path) async {
    final baseUrl = _baseUrl;
    final headers = await _getHeaders();
    return _client.get(Uri.parse('$baseUrl$path'), headers: headers);
  }

  Future<http.Response> post(String path, {Object? body}) async {
    final baseUrl = _baseUrl;
    final headers = await _getHeaders();
    return _client.post(
      Uri.parse('$baseUrl$path'),
      headers: headers,
      body: body,
    );
  }

  Future<http.Response> delete(String path) async {
    final baseUrl = _baseUrl;
    final headers = await _getHeaders();
    return _client.delete(Uri.parse('$baseUrl$path'), headers: headers);
  }
}
