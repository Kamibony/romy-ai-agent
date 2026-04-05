import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dashboard/providers/agent_provider.dart';
import 'dart:convert';

class MissionControlScreen extends ConsumerWidget {
  const MissionControlScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final agentState = ref.watch(agentStateProvider);
    final notifier = ref.read(agentStateProvider.notifier);

    return Padding(
      padding: const EdgeInsets.all(16.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                'Mission Control',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              ElevatedButton.icon(
                onPressed: () => _confirmAbort(context, notifier),
                icon: const Icon(Icons.warning, color: Colors.white),
                label: const Text('Emergency Abort', style: TextStyle(color: Colors.white)),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red,
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Row(
            children: [
              _buildStatusCard('Status', agentState.status, context),
              const SizedBox(width: 16),
              _buildStatusCard('Intent', agentState.intent ?? 'N/A', context),
            ],
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Current Action', style: TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  Text(agentState.currentAction ?? 'Waiting for instructions...', style: const TextStyle(fontFamily: 'monospace')),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Expanded(
            child: Card(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Padding(
                    padding: EdgeInsets.all(16.0),
                    child: Text('Live Preview', style: TextStyle(fontWeight: FontWeight.bold)),
                  ),
                  Expanded(
                    child: agentState.base64Image != null
                        ? RepaintBoundary(
                            child: Image.memory(
                              base64Decode(agentState.base64Image!),
                              fit: BoxFit.contain,
                              gaplessPlayback: true, // Prevents flickering on update
                            ),
                          )
                        : const Center(
                            child: Text('No preview available', style: TextStyle(color: Colors.grey)),
                          ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusCard(String title, String value, BuildContext context) {
    return Expanded(
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text(
                value.toUpperCase(),
                style: TextStyle(
                  fontSize: 18,
                  color: value == 'offline' ? Colors.red : Theme.of(context).primaryColor,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _confirmAbort(BuildContext context, AgentStateNotifier notifier) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Confirm Emergency Abort'),
        content: const Text('Are you sure you want to hard reset the agent execution loop? This will drop the current state.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              notifier.emergencyAbort();
              Navigator.of(context).pop();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('ABORT', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }
}
