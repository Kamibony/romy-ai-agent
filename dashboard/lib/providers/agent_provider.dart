import 'dart:convert';
import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_riverpod/flutter_riverpod.dart';

// Provides the telemetry URL
final telemetryUrlProvider = Provider<String>((ref) => 'http://127.0.0.1:8764');

final agentStateProvider = NotifierProvider<AgentStateNotifier, AgentStatus>(AgentStateNotifier.new);

class AgentStatus {
  final String status;
  final String? intent;
  final String? currentAction;
  final String? currentUrl;
  final String? base64Image;

  AgentStatus({
    this.status = 'unknown',
    this.intent,
    this.currentAction,
    this.currentUrl,
    this.base64Image,
  });

  factory AgentStatus.fromJson(Map<String, dynamic> json) {
    return AgentStatus(
      status: json['status'] ?? 'unknown',
      intent: json['agent_state']?['intent'],
      currentAction: json['agent_state']?['current_action'],
      currentUrl: json['agent_state']?['current_url'],
      // We might receive the image here, or via another endpoint/socket.
      // Usually, the screenshot might be omitted from standard status endpoint.
      base64Image: json['agent_state']?['screenshot'],
    );
  }
}

class AgentStateNotifier extends Notifier<AgentStatus> {
  Timer? _timer;

  @override
  AgentStatus build() {
    ref.onDispose(() {
      _timer?.cancel();
    });
    _startPolling();
    return AgentStatus();
  }

  void _startPolling() {
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      _fetchStatus();
    });
  }

  Future<void> _fetchStatus() async {
    try {
      final baseUrl = ref.read(telemetryUrlProvider);
      // Typically, telemetry provides a /api/status endpoint
      // We might use a generic ID or omit if the API supports generic status
      final response = await http.get(Uri.parse('$baseUrl/api/status/active'));
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        state = AgentStatus.fromJson(data);
      }
    } catch (e) {
      // Silent error or update state to indicate connection issue
      if (state.status != 'offline') {
         state = AgentStatus(status: 'offline');
      }
    }
  }

  Future<void> emergencyAbort() async {
    try {
      final baseUrl = ref.read(telemetryUrlProvider);
      await http.post(Uri.parse('$baseUrl/api/reset'));
      state = AgentStatus(status: 'reset_sent');
    } catch (e) {
      debugPrint('Failed to send emergency abort: $e');
    }
  }

  // Note: For Notifiers, cleanup can be done in ref.onDispose
  // However, build is where we should probably put onDispose
}
