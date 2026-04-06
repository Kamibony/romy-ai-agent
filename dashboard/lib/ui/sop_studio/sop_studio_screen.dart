import 'package:flutter/material.dart';
import 'dart:convert';
import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../../providers/api_client_provider.dart';

class SopStudioScreen extends ConsumerStatefulWidget {
  const SopStudioScreen({super.key});

  @override
  ConsumerState<SopStudioScreen> createState() => _SopStudioScreenState();
}

class _SopStudioScreenState extends ConsumerState<SopStudioScreen> {
  final _goalController = TextEditingController();
  bool _isSubmitting = false;
  bool _isRecording = false;
  List<Map<String, dynamic>> _recordedSteps = [];
  Timer? _pollingTimer;

  @override
  void dispose() {
    _goalController.dispose();
    _pollingTimer?.cancel();
    super.dispose();
  }

  Future<void> _startRecording() async {
    try {
      final response = await http.post(Uri.parse('http://127.0.0.1:8764/api/recording/start'));
      if (response.statusCode == 200) {
        setState(() {
          _isRecording = true;
          _recordedSteps = [];
        });
        _pollingTimer = Timer.periodic(const Duration(milliseconds: 500), (timer) {
          _pollSteps();
        });
      } else {
        _showError('Failed to start recording: ${response.body}');
      }
    } catch (e) {
      _showError('Network error starting recording: $e');
    }
  }

  Future<void> _stopRecording() async {
    _pollingTimer?.cancel();
    try {
      final response = await http.post(Uri.parse('http://127.0.0.1:8764/api/recording/stop'));
      if (response.statusCode == 200) {
        setState(() {
          _isRecording = false;
        });
        // One final poll
        await _pollSteps();
      } else {
        _showError('Failed to stop recording: ${response.body}');
      }
    } catch (e) {
      _showError('Network error stopping recording: $e');
      setState(() {
        _isRecording = false;
      });
    }
  }

  Future<void> _pollSteps() async {
    try {
      final response = await http.get(Uri.parse('http://127.0.0.1:8764/api/recording/steps'));
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (data['steps'] != null) {
          setState(() {
            _recordedSteps = List<Map<String, dynamic>>.from(data['steps']);
          });
        }
      }
    } catch (e) {
      // Silently ignore polling errors to not spam
    }
  }

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red),
    );
  }

  Future<void> _submitSOP() async {
    if (_goalController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please fill out the target goal.')),
      );
      return;
    }

    if (_recordedSteps.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please record some steps first.')),
      );
      return;
    }

    setState(() {
      _isSubmitting = true;
    });

    final apiClient = ref.read(apiClientProvider);

    try {
      // The backend /api/v1/memory/sops endpoint expects a SOPSaveRequest
      final response = await apiClient.post(
        '/api/v1/memory/sops',
        body: json.encode({
          'domain': 'default_domain',
          'goal': _goalController.text.trim(),
          'recorded_steps': _recordedSteps.map((s) => {'step': s['description']}).toList(),
          'client_id': 'default'
        }),
      );

      if (!mounted) return;

      if (response.statusCode == 200 || response.statusCode == 201) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('SOP successfully saved into Agent Memory.'), backgroundColor: Colors.green),
        );
        _goalController.clear();
        setState(() {
          _recordedSteps = [];
        });
      } else if (response.statusCode == 409) {
         showDialog(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Semantic Conflict Detected'),
            content: Text('The SOP conflicts with existing rules.\n\nDetails: ${response.body}'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))
            ],
          )
        );
      } else {
         ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: ${response.statusCode} - ${response.body}'), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Network error: $e'), backgroundColor: Colors.red),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'SOP Studio',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              ElevatedButton.icon(
                onPressed: _isRecording ? _stopRecording : _startRecording,
                icon: Icon(
                  _isRecording ? Icons.stop : Icons.fiber_manual_record,
                  color: _isRecording ? Colors.white : Colors.red,
                ),
                label: Text(_isRecording ? 'Stop Recording' : 'Start Recording'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: _isRecording ? Colors.red : Theme.of(context).cardColor,
                  foregroundColor: _isRecording ? Colors.white : Theme.of(context).textTheme.bodyLarge?.color,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Record visual actions (Ghost Clicks) directly from your browser to build resilient Playbook Rules.',
            style: TextStyle(color: Colors.grey),
          ),
          if (_isRecording) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.red.withOpacity(0.1),
                border: Border.all(color: Colors.red),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Row(
                children: [
                  SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.red),
                  ),
                  SizedBox(width: 16),
                  Text(
                    'Listening for Ghost Clicks from Chrome Extension...',
                    style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 24),
          TextField(
            controller: _goalController,
            decoration: const InputDecoration(
              labelText: 'Target Goal / Intent',
              hintText: 'e.g., Navigate to search results on alza.cz',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                border: Border.all(color: Colors.grey.withOpacity(0.5)),
                borderRadius: BorderRadius.circular(4),
              ),
              child: _recordedSteps.isEmpty
                  ? Center(
                      child: Text(
                        _isRecording
                            ? 'Perform actions in your browser to record steps.'
                            : 'Click "Start Recording" to begin capturing steps.',
                        style: const TextStyle(color: Colors.grey),
                      ),
                    )
                  : ListView.builder(
                      itemCount: _recordedSteps.length,
                      itemBuilder: (context, index) {
                        final step = _recordedSteps[index];
                        return Card(
                          margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                          child: ListTile(
                            leading: CircleAvatar(
                              backgroundColor: Theme.of(context).primaryColor,
                              foregroundColor: Colors.white,
                              child: Text('${index + 1}'),
                            ),
                            title: Text(step['description'] ?? 'Action'),
                            subtitle: Text('Timestamp: ${step['timestamp']}'),
                            trailing: const Icon(Icons.touch_app, color: Colors.grey),
                          ),
                        );
                      },
                    ),
            ),
          ),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            height: 50,
            child: ElevatedButton.icon(
              onPressed: (_isSubmitting || _recordedSteps.isEmpty || _isRecording) ? null : _submitSOP,
              icon: _isSubmitting ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.auto_awesome),
              label: Text(_isSubmitting ? 'Compiling SOP...' : 'Compile & Inject SOP'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Theme.of(context).primaryColor,
                foregroundColor: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
