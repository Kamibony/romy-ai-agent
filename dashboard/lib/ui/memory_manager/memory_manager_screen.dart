import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'dart:convert';

import '../../providers/api_client_provider.dart';

final memoryRulesProvider = FutureProvider.autoDispose<List<dynamic>>((
  ref,
) async {
  final apiClient = ref.watch(apiClientProvider);
  final response = await apiClient.get('/api/v1/memory/sops?client_id=default');

  if (response.statusCode == 200) {
    final jsonResponse = json.decode(response.body);
    return jsonResponse['sops'] as List<dynamic>;
  } else {
    throw Exception('Failed to load memory rules');
  }
});

class MemoryManagerScreen extends ConsumerWidget {
  const MemoryManagerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rulesAsyncValue = ref.watch(memoryRulesProvider);

    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Memory Manager',
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 8),
          const Text(
            'Real-time view of the agent\'s learned behaviors and SOPs from Firestore.',
            style: TextStyle(color: Colors.grey),
          ),
          const SizedBox(height: 24),
          Expanded(
            child: rulesAsyncValue.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, stack) =>
                  Center(child: Text('Error loading memory rules: $error')),
              data: (rules) {
                if (rules.isEmpty) {
                  return const Center(
                    child: Text(
                      'No memory rules found. Use the SOP Studio to inject new behaviors.',
                      style: TextStyle(color: Colors.grey),
                    ),
                  );
                }

                return ListView.builder(
                  itemCount: rules.length,
                  itemBuilder: (context, index) {
                    final data = rules[index] as Map<String, dynamic>;
                    final docId = data['id'] ?? data['doc_id'] ?? 'unknown_id';
                    final goal = data['goal'] ?? 'Unknown Goal';
                    final ruleItems = List<String>.from(data['rules'] ?? []);
                    final isActive = data['active'] ?? true;

                    return Card(
                      margin: const EdgeInsets.only(bottom: 16.0),
                      child: ExpansionTile(
                        title: Text(
                          goal,
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        subtitle: Text(
                          'ID: $docId | Status: ${isActive ? 'Active' : 'Inactive'}',
                        ),
                        leading: Icon(
                          isActive ? Icons.memory : Icons.memory_outlined,
                          color: isActive ? Colors.green : Colors.grey,
                        ),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Switch(
                              value: isActive,
                              onChanged: (value) {
                                // Currently active toggle is not supported by backend out of the box, might require new endpoint
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                    content: Text(
                                      'Toggle active state is not yet supported by API.',
                                    ),
                                  ),
                                );
                              },
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete, color: Colors.red),
                              onPressed: () =>
                                  _confirmDelete(context, ref, docId),
                            ),
                          ],
                        ),
                        children: [
                          Padding(
                            padding: const EdgeInsets.all(16.0),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text(
                                  'Active Rules:',
                                  style: TextStyle(fontWeight: FontWeight.bold),
                                ),
                                const SizedBox(height: 8),
                                ...ruleItems.map(
                                  (rule) => Padding(
                                    padding: const EdgeInsets.only(bottom: 4.0),
                                    child: Row(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        const Text('• '),
                                        Expanded(child: Text(rule)),
                                      ],
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
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

  void _confirmDelete(BuildContext context, WidgetRef ref, String docId) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Confirm Deletion'),
        content: const Text(
          'Are you sure you want to permanently delete this memory rule? The agent will forget this behavior.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () async {
              Navigator.of(context).pop();
              final apiClient = ref.read(apiClientProvider);
              try {
                final response = await apiClient.delete(
                  '/api/v1/memory/sops/$docId?client_id=default',
                );
                if (response.statusCode == 200) {
                  ref.invalidate(memoryRulesProvider);
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Rule deleted successfully.')),
                  );
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('Failed to delete rule: ${response.body}'),
                    ),
                  );
                }
              } catch (e) {
                ScaffoldMessenger.of(
                  context,
                ).showSnackBar(SnackBar(content: Text('Error: $e')));
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Delete', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }
}
