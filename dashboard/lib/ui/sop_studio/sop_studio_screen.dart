import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers/sop_studio_provider.dart';
import '../../models/sop_models.dart';

class SopStudioScreen extends ConsumerStatefulWidget {
  const SopStudioScreen({super.key});

  @override
  ConsumerState<SopStudioScreen> createState() => _SopStudioScreenState();
}

class _SopStudioScreenState extends ConsumerState<SopStudioScreen> {
  final _domainController = TextEditingController();
  final _goalController = TextEditingController();

  @override
  void initState() {
    super.initState();
    final state = ref.read(sopStudioProvider);
    _domainController.text = state.domain;
    _goalController.text = state.goal;
  }

  @override
  void dispose() {
    _domainController.dispose();
    _goalController.dispose();
    super.dispose();
  }

  void _onSaveSOP() async {
    final notifier = ref.read(sopStudioProvider.notifier);

    // Explicitly call validateSequence as requested
    if (!notifier.validateSequence()) {
      final state = ref.read(sopStudioProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(state.errorMessage ?? 'Validation failed.'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    // Validation passed, proceed to submit
    final success = await notifier.submitSop();

    if (!mounted) return;

    final finalState = ref.read(sopStudioProvider);

    if (success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('SOP saved successfully!'),
          backgroundColor: Colors.green,
        ),
      );
      notifier.initializeDraft('', '');
      _domainController.clear();
      _goalController.clear();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            finalState.errorMessage ??
                'Unknown error occurred while saving SOP.',
          ),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(sopStudioProvider);
    final notifier = ref.read(sopStudioProvider.notifier);

    return Scaffold(
      appBar: AppBar(title: const Text('SOP Studio')),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'SOP Setup',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _domainController,
                      decoration: const InputDecoration(
                        labelText: 'Domain',
                        hintText: 'e.g., example.com',
                        border: OutlineInputBorder(),
                      ),
                      onChanged: (val) => notifier.setDomain(val),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _goalController,
                      decoration: const InputDecoration(
                        labelText: 'Target Goal / Intent',
                        hintText: 'e.g., Navigate to search results on alza.cz',
                        border: OutlineInputBorder(),
                      ),
                      onChanged: (val) => notifier.setGoal(val),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: SopActionType.values.map((type) {
                  return Padding(
                    padding: const EdgeInsets.only(right: 8.0),
                    child: ActionChip(
                      label: Text('Add ${type.agentValue}'),
                      avatar: const Icon(Icons.add, size: 16),
                      onPressed: () {
                        notifier.addStep(
                          type,
                          description: 'New ${type.agentValue} action',
                        );
                      },
                    ),
                  );
                }).toList(),
              ),
            ),
            const SizedBox(height: 16),
            Expanded(
              child: state.steps.isEmpty
                  ? const Center(
                      child: Text(
                        'No steps added yet. Use the buttons above to build the sequence.',
                        style: TextStyle(color: Colors.grey),
                      ),
                    )
                  : ReorderableListView.builder(
                      itemCount: state.steps.length,
                      onReorder: (oldIndex, newIndex) {
                        notifier.reorderSteps(oldIndex, newIndex);
                      },
                      itemBuilder: (context, index) {
                        final step = state.steps[index];
                        return _SopStepCard(
                          key: ValueKey(step.id),
                          step: step,
                          index: index,
                        );
                      },
                    ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              height: 50,
              child: ElevatedButton.icon(
                onPressed: state.isSubmitting ? null : _onSaveSOP,
                icon: state.isSubmitting
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.save),
                label: Text(state.isSubmitting ? 'Saving...' : 'Save SOP'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Theme.of(context).primaryColor,
                  foregroundColor: Colors.white,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SopStepCard extends ConsumerStatefulWidget {
  final SopStep step;
  final int index;

  const _SopStepCard({
    required super.key,
    required this.step,
    required this.index,
  });

  @override
  ConsumerState<_SopStepCard> createState() => _SopStepCardState();
}

class _SopStepCardState extends ConsumerState<_SopStepCard> {
  late TextEditingController _descriptionController;
  late TextEditingController _targetNameController;
  late TextEditingController _targetIdController;
  late TextEditingController _textController;
  late TextEditingController _urlController;
  late TextEditingController _durationMsController;
  late TextEditingController _xController;
  late TextEditingController _yController;

  @override
  void initState() {
    super.initState();
    _descriptionController = TextEditingController(
      text: widget.step.description,
    );
    _targetNameController = TextEditingController(text: widget.step.targetName);
    _targetIdController = TextEditingController(text: widget.step.targetId);
    _textController = TextEditingController(text: widget.step.text);
    _urlController = TextEditingController(text: widget.step.url);
    _durationMsController = TextEditingController(
      text: widget.step.durationMs?.toString(),
    );
    _xController = TextEditingController(text: widget.step.x?.toString());
    _yController = TextEditingController(text: widget.step.y?.toString());
  }

  @override
  void didUpdateWidget(covariant _SopStepCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    // When the provider reorders or updates from an external source, keep controllers in sync.
    // However, only update them if the value actually changed to prevent cursor jumping.
    if (widget.step.description != _descriptionController.text) {
      _descriptionController.text = widget.step.description ?? '';
    }
    if (widget.step.targetName != _targetNameController.text) {
      _targetNameController.text = widget.step.targetName ?? '';
    }
    if (widget.step.targetId != _targetIdController.text) {
      _targetIdController.text = widget.step.targetId ?? '';
    }
    if (widget.step.text != _textController.text) {
      _textController.text = widget.step.text ?? '';
    }
    if (widget.step.url != _urlController.text) {
      _urlController.text = widget.step.url ?? '';
    }
    final durationStr = widget.step.durationMs?.toString() ?? '';
    if (durationStr != _durationMsController.text) {
      _durationMsController.text = durationStr;
    }
    final xStr = widget.step.x?.toString() ?? '';
    if (xStr != _xController.text) {
      _xController.text = xStr;
    }
    final yStr = widget.step.y?.toString() ?? '';
    if (yStr != _yController.text) {
      _yController.text = yStr;
    }
  }

  @override
  void dispose() {
    _descriptionController.dispose();
    _targetNameController.dispose();
    _targetIdController.dispose();
    _textController.dispose();
    _urlController.dispose();
    _durationMsController.dispose();
    _xController.dispose();
    _yController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final notifier = ref.read(sopStudioProvider.notifier);

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: ExpansionTile(
        initiallyExpanded: true,
        leading: CircleAvatar(
          backgroundColor: Theme.of(context).primaryColor,
          foregroundColor: Colors.white,
          child: Text('${widget.index + 1}'),
        ),
        title: Text('${widget.step.actionType.agentValue} Action'),
        trailing: IconButton(
          icon: const Icon(Icons.delete, color: Colors.red),
          onPressed: () => notifier.removeStep(widget.step.id),
        ),
        children: [
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  decoration: const InputDecoration(labelText: 'Description'),
                  controller: _descriptionController,
                  onChanged: (val) => notifier.updateStep(
                    widget.step.id,
                    widget.step.copyWith(description: val),
                  ),
                ),
                if (widget.step.actionType == SopActionType.click ||
                    widget.step.actionType == SopActionType.hover) ...[
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Target Name (optional)',
                    ),
                    controller: _targetNameController,
                    onChanged: (val) => notifier.updateStep(
                      widget.step.id,
                      widget.step.copyWith(targetName: val),
                    ),
                  ),
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Target ID (optional)',
                    ),
                    controller: _targetIdController,
                    onChanged: (val) => notifier.updateStep(
                      widget.step.id,
                      widget.step.copyWith(targetId: val),
                    ),
                  ),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          decoration: const InputDecoration(
                            labelText: 'X Coordinate (optional)',
                          ),
                          keyboardType: TextInputType.number,
                          controller: _xController,
                          onChanged: (val) => notifier.updateStep(
                            widget.step.id,
                            widget.step.copyWith(x: int.tryParse(val)),
                          ),
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: TextField(
                          decoration: const InputDecoration(
                            labelText: 'Y Coordinate (optional)',
                          ),
                          keyboardType: TextInputType.number,
                          controller: _yController,
                          onChanged: (val) => notifier.updateStep(
                            widget.step.id,
                            widget.step.copyWith(y: int.tryParse(val)),
                          ),
                        ),
                      ),
                    ],
                  ),
                ] else if (widget.step.actionType == SopActionType.type) ...[
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Target Name (optional)',
                    ),
                    controller: _targetNameController,
                    onChanged: (val) => notifier.updateStep(
                      widget.step.id,
                      widget.step.copyWith(targetName: val),
                    ),
                  ),
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Text (required)',
                    ),
                    controller: _textController,
                    onChanged: (val) => notifier.updateStep(
                      widget.step.id,
                      widget.step.copyWith(text: val),
                    ),
                  ),
                ] else if (widget.step.actionType ==
                    SopActionType.navigate) ...[
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'URL (required)',
                    ),
                    controller: _urlController,
                    onChanged: (val) => notifier.updateStep(
                      widget.step.id,
                      widget.step.copyWith(url: val),
                    ),
                  ),
                ] else if (widget.step.actionType == SopActionType.wait ||
                    widget.step.actionType == SopActionType.waitFor) ...[
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Duration in ms (required for WAIT)',
                    ),
                    keyboardType: TextInputType.number,
                    controller: _durationMsController,
                    onChanged: (val) => notifier.updateStep(
                      widget.step.id,
                      widget.step.copyWith(durationMs: int.tryParse(val)),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
