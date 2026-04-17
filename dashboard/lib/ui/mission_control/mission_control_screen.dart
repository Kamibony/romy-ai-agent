import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'dart:convert';
import '../../providers/api_client_provider.dart';
import '../../providers/agent_provider.dart';
import '../memory_manager/memory_manager_screen.dart'; // To reuse memoryRulesProvider

class MissionControlScreen extends ConsumerWidget {
  const MissionControlScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rulesAsyncValue = ref.watch(memoryRulesProvider);
    final agentState = ref.watch(agentStateProvider);
    final notifier = ref.read(agentStateProvider.notifier);

    final isExecuting = agentState.agentState.toLowerCase().contains('executing') ||
                        agentState.agentState.toLowerCase().contains('running') ||
                        agentState.agentState.toLowerCase().contains('working');

    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Moje procesy',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              if (isExecuting)
                ElevatedButton.icon(
                  onPressed: () => notifier.emergencyAbort(),
                  icon: const Icon(Icons.stop, color: Colors.white),
                  label: const Text(
                    'Zastavit',
                    style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                  ),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Vyberte proces, který chcete spustit.',
            style: TextStyle(color: Colors.grey),
          ),
          const SizedBox(height: 24),
          Expanded(
            child: rulesAsyncValue.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, stack) =>
                  Center(child: Text('Chyba při načítání procesů: $error')),
              data: (rules) {
                if (rules.isEmpty) {
                  return const Center(
                    child: Text(
                      'Žádné procesy nenalezeny. Přejděte do "Trénink Romy" a nějaký vytvořte.',
                      style: TextStyle(color: Colors.grey),
                    ),
                  );
                }

                return ListView.builder(
                  itemCount: rules.length,
                  itemBuilder: (context, index) {
                    final data = rules[index] as Map<String, dynamic>;
                    final goal = data['goal'] ?? 'Neznámý proces';

                    return Card(
                      margin: const EdgeInsets.only(bottom: 16.0),
                      child: ListTile(
                        contentPadding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 8.0),
                        title: Text(
                          goal,
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
                        ),
                        leading: const Icon(Icons.play_circle_outline, size: 40, color: Colors.blue),
                        trailing: ElevatedButton.icon(
                          onPressed: isExecuting ? null : () {
                            notifier.startExecution(goal);
                          },
                          icon: const Icon(Icons.play_arrow),
                          label: const Text('Spustit'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.green.shade600,
                            foregroundColor: Colors.white,
                          ),
                        ),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
