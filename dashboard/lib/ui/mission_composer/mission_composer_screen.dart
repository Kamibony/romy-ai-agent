import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/mission_models.dart';
import '../../providers/mission_provider.dart';
import '../memory_manager/memory_manager_screen.dart'; // To reuse memoryRulesProvider

class MissionComposerScreen extends ConsumerStatefulWidget {
  const MissionComposerScreen({super.key});

  @override
  ConsumerState<MissionComposerScreen> createState() => _MissionComposerScreenState();
}

class _MissionComposerScreenState extends ConsumerState<MissionComposerScreen> {
  final TextEditingController _nameController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _nameController.text = ref.read(missionBuilderProvider).name;
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final missionGraph = ref.watch(missionBuilderProvider);
    final notifier = ref.read(missionBuilderProvider.notifier);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Mission Composer'),
        actions: [
          ElevatedButton.icon(
            onPressed: missionGraph.executionOrder.isEmpty ? null : () async {
              final success = await notifier.executeMission();
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(success ? 'Mission execution started!' : 'Failed to execute mission.'),
                    backgroundColor: success ? Colors.green : Colors.red,
                  ),
                );
              }
            },
            icon: const Icon(Icons.play_arrow),
            label: const Text('Execute'),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.green.shade600,
              foregroundColor: Colors.white,
            ),
          ),
          const SizedBox(width: 16),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _nameController,
              decoration: const InputDecoration(
                labelText: 'Mission Name',
                border: OutlineInputBorder(),
              ),
              onChanged: notifier.updateMissionName,
            ),
            const SizedBox(height: 24),
            Expanded(
              child: missionGraph.executionOrder.isEmpty
                  ? const Center(
                      child: Text(
                        'No blocks added yet. Click the + button to add one.',
                        style: TextStyle(color: Colors.grey),
                      ),
                    )
                  : ReorderableListView.builder(
                      itemCount: missionGraph.executionOrder.length,
                      onReorder: notifier.reorderBlocks,
                      itemBuilder: (context, index) {
                        final blockId = missionGraph.executionOrder[index];
                        final block = missionGraph.blocks.firstWhere((b) => b.blockId == blockId);
                        return _MissionBlockWidget(
                          key: ValueKey(blockId),
                          block: block,
                          index: index,
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () {
          showModalBottomSheet(
            context: context,
            builder: (context) => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ListTile(
                  leading: const Icon(Icons.smart_toy),
                  title: const Text('Automation Block (SOP)'),
                  onTap: () {
                    Navigator.pop(context);
                    notifier.addBlock(BlockType.automation);
                  },
                ),
                ListTile(
                  leading: const Icon(Icons.psychology),
                  title: const Text('AI Logic Block'),
                  onTap: () {
                    Navigator.pop(context);
                    notifier.addBlock(BlockType.aiLogic);
                  },
                ),
              ],
            ),
          );
        },
        child: const Icon(Icons.add),
      ),
    );
  }
}

class _MissionBlockWidget extends ConsumerStatefulWidget {
  final MissionBlock block;
  final int index;

  const _MissionBlockWidget({super.key, required this.block, required this.index});

  @override
  ConsumerState<_MissionBlockWidget> createState() => _MissionBlockWidgetState();
}

class _MissionBlockWidgetState extends ConsumerState<_MissionBlockWidget> {
  final TextEditingController _instructionController = TextEditingController();
  final TextEditingController _inputKeyController = TextEditingController();
  final TextEditingController _inputValueController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _instructionController.text = widget.block.instruction ?? '';
  }

  @override
  void didUpdateWidget(covariant _MissionBlockWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.block.instruction != oldWidget.block.instruction) {
      _instructionController.text = widget.block.instruction ?? '';
    }
  }

  @override
  void dispose() {
    _instructionController.dispose();
    _inputKeyController.dispose();
    _inputValueController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final notifier = ref.read(missionBuilderProvider.notifier);
    final isAutomation = widget.block.type == BlockType.automation;

    return Card(
      margin: const EdgeInsets.only(bottom: 16.0),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(isAutomation ? Icons.smart_toy : Icons.psychology, color: Colors.blue),
                const SizedBox(width: 8),
                Text(
                  '${widget.index + 1}. ${isAutomation ? 'Automation' : 'AI Logic'}',
                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.delete, color: Colors.red),
                  onPressed: () => notifier.removeBlock(widget.block.blockId),
                ),
                const Icon(Icons.drag_handle),
              ],
            ),
            const SizedBox(height: 16),
            if (isAutomation) _buildAutomationConfig(notifier) else _buildAiLogicConfig(notifier),
            const SizedBox(height: 16),
            const Text('Inputs:', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            ...widget.block.inputs.entries.map((e) => Padding(
                  padding: const EdgeInsets.only(bottom: 8.0),
                  child: Row(
                    children: [
                      Expanded(child: Text('${e.key}: ${e.value}')),
                      IconButton(
                        icon: const Icon(Icons.remove_circle, color: Colors.red),
                        onPressed: () {
                          final newInputs = Map<String, String>.from(widget.block.inputs);
                          newInputs.remove(e.key);
                          notifier.updateBlock(MissionBlock(
                            blockId: widget.block.blockId,
                            type: widget.block.type,
                            sopReferenceId: widget.block.sopReferenceId,
                            instruction: widget.block.instruction,
                            inputs: newInputs,
                            outputs: widget.block.outputs,
                          ));
                        },
                      )
                    ],
                  ),
                )),
            Row(
              children: [
                Expanded(
                  flex: 1,
                  child: TextField(
                    controller: _inputKeyController,
                    decoration: const InputDecoration(labelText: 'Key (e.g. url)', isDense: true),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  flex: 2,
                  child: TextField(
                    controller: _inputValueController,
                    decoration: const InputDecoration(labelText: 'Value (e.g. {{b_001.output}})', isDense: true),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.add_circle, color: Colors.green),
                  onPressed: () {
                    if (_inputKeyController.text.isNotEmpty && _inputValueController.text.isNotEmpty) {
                      final newInputs = Map<String, String>.from(widget.block.inputs);
                      newInputs[_inputKeyController.text] = _inputValueController.text;
                      notifier.updateBlock(MissionBlock(
                        blockId: widget.block.blockId,
                        type: widget.block.type,
                        sopReferenceId: widget.block.sopReferenceId,
                        instruction: widget.block.instruction,
                        inputs: newInputs,
                        outputs: widget.block.outputs,
                      ));
                      _inputKeyController.clear();
                      _inputValueController.clear();
                    }
                  },
                )
              ],
            )
          ],
        ),
      ),
    );
  }

  Widget _buildAutomationConfig(MissionBuilderNotifier notifier) {
    final rulesAsyncValue = ref.watch(memoryRulesProvider);

    return rulesAsyncValue.when(
      loading: () => const CircularProgressIndicator(),
      error: (e, s) => Text('Error loading SOPs: $e'),
      data: (rules) {
        final sopItems = rules.map((r) {
          final docId = r['id'] ?? r['doc_id'] ?? '';
          final goal = r['goal'] ?? 'Unknown';
          return DropdownMenuItem<String>(
            value: docId,
            child: Text(goal),
          );
        }).toList();

        return DropdownButtonFormField<String>(
          initialValue: widget.block.sopReferenceId == '' ? null : widget.block.sopReferenceId,
          hint: const Text('Select an SOP'),
          items: sopItems,
          onChanged: (val) {
            if (val != null) {
              notifier.updateBlock(MissionBlock(
                blockId: widget.block.blockId,
                type: widget.block.type,
                sopReferenceId: val,
                instruction: widget.block.instruction,
                inputs: widget.block.inputs,
                outputs: widget.block.outputs,
              ));
            }
          },
        );
      },
    );
  }

  Widget _buildAiLogicConfig(MissionBuilderNotifier notifier) {
    return TextField(
      controller: _instructionController,
      decoration: const InputDecoration(
        labelText: 'AI Instruction',
        border: OutlineInputBorder(),
      ),
      maxLines: 3,
      onChanged: (val) {
        notifier.updateBlock(MissionBlock(
          blockId: widget.block.blockId,
          type: widget.block.type,
          sopReferenceId: widget.block.sopReferenceId,
          instruction: val,
          inputs: widget.block.inputs,
          outputs: widget.block.outputs,
        ));
      },
    );
  }
}
