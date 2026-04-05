import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../main.dart'; // import provider

class MemoryManagerScreen extends ConsumerWidget {
  const MemoryManagerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final firebaseInitState = ref.watch(firebaseInitProvider);

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
            child: firebaseInitState.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, stack) => Center(child: Text('Error initializing Firebase: $error')),
              data: (isInitialized) {
                if (!isInitialized) {
                  return const Center(
                    child: Text('Firebase is not initialized. Cannot load memory rules.'),
                  );
                }

                final CollectionReference memoryRules = FirebaseFirestore.instance.collection('memory_rules');
                return StreamBuilder<QuerySnapshot>(
                  stream: memoryRules.snapshots(),
                  builder: (context, snapshot) {
                    if (snapshot.hasError) {
                      return const Center(child: Text('Error loading memory rules. Make sure Firebase is properly configured for the current tenant.'));
                    }

                if (snapshot.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator());
                }

                final docs = snapshot.data?.docs ?? [];

                if (docs.isEmpty) {
                  return const Center(child: Text('No memory rules found. Use the SOP Studio to inject new behaviors.', style: TextStyle(color: Colors.grey)));
                }

                return ListView.builder(
                  itemCount: docs.length,
                  itemBuilder: (context, index) {
                    final data = docs[index].data() as Map<String, dynamic>;
                    final docId = docs[index].id;
                    final goal = data['goal'] ?? 'Unknown Goal';
                    final rules = List<String>.from(data['rules'] ?? []);
                    final isActive = data['active'] ?? true;

                    return Card(
                      margin: const EdgeInsets.only(bottom: 16.0),
                      child: ExpansionTile(
                        title: Text(goal, style: const TextStyle(fontWeight: FontWeight.bold)),
                        subtitle: Text('ID: $docId | Status: ${isActive ? 'Active' : 'Inactive'}'),
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
                                memoryRules.doc(docId).update({'active': value});
                              },
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete, color: Colors.red),
                              onPressed: () => _confirmDelete(context, memoryRules, docId),
                            ),
                          ],
                        ),
                        children: [
                          Padding(
                            padding: const EdgeInsets.all(16.0),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text('Active Rules:', style: TextStyle(fontWeight: FontWeight.bold)),
                                const SizedBox(height: 8),
                                ...rules.map((rule) => Padding(
                                  padding: const EdgeInsets.only(bottom: 4.0),
                                  child: Row(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      const Text('• '),
                                      Expanded(child: Text(rule)),
                                    ],
                                  ),
                                )),
                              ],
                            ),
                          ),
                        ],
                      ),
                    );
                  },
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

  void _confirmDelete(BuildContext context, CollectionReference ref, String docId) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Confirm Deletion'),
        content: const Text('Are you sure you want to permanently delete this memory rule? The agent will forget this behavior.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              ref.doc(docId).delete();
              Navigator.of(context).pop();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Delete', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }
}
