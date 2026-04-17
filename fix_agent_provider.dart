import 'dart:io';

void main() {
  var file = File('dashboard/lib/providers/agent_provider.dart');
  var content = file.readAsStringSync();

  // Remove the methods from AgentStatus class
  final regex = RegExp(r'  Future<void> startExecution.*?}\n}\n\n', dotAll: true);
  content = content.replaceFirst(regex, '\n}\n\n');

  // Add the methods to AgentStateNotifier class
  final methodsToAdd = '''
  Future<void> startExecution(String intent) async {
    try {
      final baseUrl = ref.read(telemetryUrlProvider);
      final payload = json.encode({
        "doc_id": "active",
        "command_text": intent,
        "client_context": "Dashboard Triggered"
      });
      await http.post(
        Uri.parse('\$baseUrl/api/run_command'),
        headers: {'Content-Type': 'application/json'},
        body: payload,
      );
      debugPrint('Sent start execution for intent: \$intent');
    } catch (e) {
      debugPrint('Failed to start execution: \$e');
    }
  }

  Future<void> startRecording() async {
    try {
      final baseUrl = ref.read(telemetryUrlProvider);
      await http.post(Uri.parse('\$baseUrl/api/recording/start'));
      debugPrint('Started recording');
    } catch (e) {
      debugPrint('Failed to start recording: \$e');
    }
  }

  Future<void> stopRecording() async {
    try {
      final baseUrl = ref.read(telemetryUrlProvider);
      await http.post(Uri.parse('\$baseUrl/api/recording/stop'));
      debugPrint('Stopped recording');
    } catch (e) {
      debugPrint('Failed to stop recording: \$e');
    }
  }
}
''';

  content = content.replaceFirst(
    '''
  Future<void> sendHumanGuidance(double x, double y) async {
    try {
      final baseUrl = ref.read(telemetryUrlProvider);
      final payload = json.encode({"type": "CLICK", "x": x, "y": y});
      await http.post(
        Uri.parse('\$baseUrl/api/human_guidance'),
        headers: {'Content-Type': 'application/json'},
        body: payload,
      );
      debugPrint('Sent human guidance: \$x, \$y');
    } catch (e) {
      debugPrint('Failed to send human guidance: \$e');
    }
  }
}
''',
    '''
  Future<void> sendHumanGuidance(double x, double y) async {
    try {
      final baseUrl = ref.read(telemetryUrlProvider);
      final payload = json.encode({"type": "CLICK", "x": x, "y": y});
      await http.post(
        Uri.parse('\$baseUrl/api/human_guidance'),
        headers: {'Content-Type': 'application/json'},
        body: payload,
      );
      debugPrint('Sent human guidance: \$x, \$y');
    } catch (e) {
      debugPrint('Failed to send human guidance: \$e');
    }
  }

$methodsToAdd
'''
  );

  file.writeAsStringSync(content);
}
