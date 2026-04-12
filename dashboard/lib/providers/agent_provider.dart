import 'dart:convert';
import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_riverpod/flutter_riverpod.dart';

// Provides the telemetry URL
final telemetryUrlProvider = Provider<String>((ref) => 'http://127.0.0.1:8764');

final agentStateProvider = NotifierProvider<AgentStateNotifier, AgentStatus>(
  AgentStateNotifier.new,
);

class AgentStatus {
  final String status;
  final String agentState;
  final String? intent;
  final String? currentAction;
  final String? currentUrl;
  final String? base64Image;
  final int? originalWidth;
  final int? originalHeight;
  final String? helpReason;
  final String? imageHash;

  AgentStatus({
    this.status = 'unknown',
    this.agentState = 'unknown',
    this.intent,
    this.currentAction,
    this.currentUrl,
    this.base64Image,
    this.originalWidth,
    this.originalHeight,
    this.helpReason,
    this.imageHash,
  });

  factory AgentStatus.fromJson(
    Map<String, dynamic> json, {
    String? existingImage,
  }) {
    return AgentStatus(
      status: json['status'] ?? 'unknown',
      agentState: json['agent_state'] ?? 'unknown',
      intent: json['intent'],
      currentAction: json['current_action'],
      currentUrl: json['current_url'],
      base64Image: json['screenshot'] ?? existingImage,
      originalWidth: json['original_width'],
      originalHeight: json['original_height'],
      helpReason: json['help_reason'],
      imageHash: json['image_hash'],
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
      String url = '$baseUrl/api/status/active';
      if (state.imageHash != null) {
        url += '?image_hash=${state.imageHash}';
      }
      final response = await http.get(Uri.parse(url));
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        state = AgentStatus.fromJson(data, existingImage: state.base64Image);
      }
    } catch (e) {
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

  Future<void> sendHumanGuidance(double x, double y) async {
    try {
      final baseUrl = ref.read(telemetryUrlProvider);
      final payload = json.encode({"type": "CLICK", "x": x, "y": y});
      await http.post(
        Uri.parse('$baseUrl/api/human_guidance'),
        headers: {'Content-Type': 'application/json'},
        body: payload,
      );
      debugPrint('Sent human guidance: $x, $y');
    } catch (e) {
      debugPrint('Failed to send human guidance: $e');
    }
  }
}
