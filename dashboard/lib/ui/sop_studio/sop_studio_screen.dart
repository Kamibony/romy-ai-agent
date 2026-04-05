import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers/agent_provider.dart';

class SopStudioScreen extends ConsumerStatefulWidget {
  const SopStudioScreen({super.key});

  @override
  ConsumerState<SopStudioScreen> createState() => _SopStudioScreenState();
}

class _SopStudioScreenState extends ConsumerState<SopStudioScreen> {
  final _goalController = TextEditingController();
  final _rulesController = TextEditingController();
  bool _isSubmitting = false;

  @override
  void dispose() {
    _goalController.dispose();
    _rulesController.dispose();
    super.dispose();
  }

  Future<void> _submitSOP() async {
    if (_goalController.text.trim().isEmpty || _rulesController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please fill out both goal and rules.')),
      );
      return;
    }

    setState(() {
      _isSubmitting = true;
    });

    final baseUrl = ref.read(telemetryUrlProvider);
    final url = Uri.parse('$baseUrl/api/v1/memory/inject_sop');

    try {
      final response = await http.post(
        url,
        headers: {
          'Content-Type': 'application/json',
          // Usually a Firebase token would be required here per backend/main.py.
          // For MVP and given we are using a local dashboard, we might bypass or need a dummy token if auth is disabled locally.
          'Authorization': 'Bearer local-dev-token',
        },
        body: json.encode({
          'goal': _goalController.text.trim(),
          'rules': _rulesController.text.trim().split('\n').where((s) => s.isNotEmpty).toList(),
          // B2B clients might use a client_id
          'client_id': 'default'
        }),
      );

      if (!mounted) return;

      if (response.statusCode == 200 || response.statusCode == 201) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('SOP successfully injected into Agent Memory.'), backgroundColor: Colors.green),
        );
        _goalController.clear();
        _rulesController.clear();
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
          Text(
            'SOP Studio',
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 8),
          const Text(
            'Inject manual standard operating procedures (SOPs) into the dual-write memory system using natural language. The Gemini compiler will translate this into agent-friendly rules.',
            style: TextStyle(color: Colors.grey),
          ),
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
            child: TextField(
              controller: _rulesController,
              maxLines: null,
              expands: true,
              textAlignVertical: TextAlignVertical.top,
              decoration: const InputDecoration(
                labelText: 'Standard Operating Procedure (Natural Language)',
                hintText: 'Enter instructions, one per line.\ne.g.\n1. Always dismiss the GDPR banner first.\n2. Wait for the page to fully load before clicking search.',
                border: OutlineInputBorder(),
                alignLabelWithHint: true,
              ),
            ),
          ),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            height: 50,
            child: ElevatedButton.icon(
              onPressed: _isSubmitting ? null : _submitSOP,
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
