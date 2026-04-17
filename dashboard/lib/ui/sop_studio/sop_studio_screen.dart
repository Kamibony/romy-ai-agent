import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers/sop_studio_provider.dart';
import '../../providers/agent_provider.dart';

class SopStudioScreen extends ConsumerStatefulWidget {
  const SopStudioScreen({super.key});

  @override
  ConsumerState<SopStudioScreen> createState() => _SopStudioScreenState();
}

class _SopStudioScreenState extends ConsumerState<SopStudioScreen> {
  int _currentStep = 0;
  final _domainController = TextEditingController();
  final _goalController = TextEditingController();

  @override
  void dispose() {
    _domainController.dispose();
    _goalController.dispose();
    super.dispose();
  }

  void _onStepContinue() {
    if (_currentStep == 0) {
      if (_domainController.text.isEmpty || _goalController.text.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Prosím vyplňte obě pole.')),
        );
        return;
      }
      ref.read(sopStudioProvider.notifier).setDomain(_domainController.text);
      ref.read(sopStudioProvider.notifier).setGoal(_goalController.text);

      // Start recording when moving to step 1
      ref.read(agentStateProvider.notifier).startRecording();
    }

    if (_currentStep < 2) {
      setState(() {
        _currentStep += 1;
      });
    }
  }

  void _onStepCancel() {
    if (_currentStep > 0) {
      if (_currentStep == 1) {
        // Stop recording if going back from step 1
        ref.read(agentStateProvider.notifier).stopRecording();
      }
      setState(() {
        _currentStep -= 1;
      });
    }
  }

  Future<void> _submitSop() async {
    // Stop recording first
    ref.read(agentStateProvider.notifier).stopRecording();

    final success = await ref.read(sopStudioProvider.notifier).submitSop();
    if (success && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Výborně! Romy si proces zapamatovala.'),
          backgroundColor: Colors.green,
        ),
      );
      setState(() {
        _currentStep = 0;
        _domainController.clear();
        _goalController.clear();
      });
      ref.read(sopStudioProvider.notifier).initializeDraft('', '');
    } else if (mounted) {
      final state = ref.read(sopStudioProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(state.errorMessage ?? 'Chyba při ukládání.'),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(sopStudioProvider);
    final agentState = ref.watch(agentStateProvider);
    final isRecording = agentState.agentState.toLowerCase().contains('recording');

    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Trénink Romy',
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 8),
          const Text(
            'Naučte Romy nový proces pomocí průvodce.',
            style: TextStyle(color: Colors.grey),
          ),
          const SizedBox(height: 24),
          Expanded(
            child: Stepper(
              currentStep: _currentStep,
              onStepContinue: _currentStep == 2 ? _submitSop : _onStepContinue,
              onStepCancel: _onStepCancel,
              controlsBuilder: (BuildContext context, ControlsDetails details) {
                return Padding(
                  padding: const EdgeInsets.only(top: 20.0),
                  child: Row(
                    children: <Widget>[
                      ElevatedButton(
                        onPressed: state.isSaving ? null : details.onStepContinue,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Theme.of(context).primaryColor,
                          foregroundColor: Colors.white,
                        ),
                        child: state.isSaving
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : Text(_currentStep == 2 ? 'Dokončit a uložit' : 'Pokračovat'),
                      ),
                      const SizedBox(width: 12),
                      if (_currentStep > 0)
                        TextButton(
                          onPressed: state.isSaving ? null : details.onStepCancel,
                          child: const Text('Zpět'),
                        ),
                    ],
                  ),
                );
              },
              steps: [
                Step(
                  title: const Text('Základní informace'),
                  content: Column(
                    children: [
                      TextField(
                        controller: _domainController,
                        decoration: const InputDecoration(
                          labelText: 'Doména (např. účetnictví)',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: _goalController,
                        decoration: const InputDecoration(
                          labelText: 'Název procesu (např. Stáhnout fakturu)',
                          border: OutlineInputBorder(),
                        ),
                      ),
                    ],
                  ),
                  isActive: _currentStep >= 0,
                  state: _currentStep > 0 ? StepState.complete : StepState.indexed,
                ),
                Step(
                  title: const Text('Nahrávání akcí'),
                  content: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Nyní přejděte do prohlížeče a proveďte všechny potřebné kroky.',
                        style: TextStyle(fontSize: 16),
                      ),
                      const SizedBox(height: 16),
                      Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: isRecording ? Colors.red.shade50 : Colors.grey.shade100,
                          border: Border.all(
                            color: isRecording ? Colors.red : Colors.grey.shade300,
                          ),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Row(
                          children: [
                            Icon(
                              isRecording ? Icons.fiber_manual_record : Icons.pause_circle_filled,
                              color: isRecording ? Colors.red : Colors.grey,
                              size: 32,
                            ),
                            const SizedBox(width: 16),
                            Expanded(
                              child: Text(
                                isRecording
                                  ? 'Nahrávání běží... (Provádějte akce v prohlížeči)'
                                  : 'Nahrávání je pozastaveno.',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: isRecording ? Colors.red.shade700 : Colors.grey.shade700,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                      Text('Zatím nahráno kroků: ${state.steps.length}'),
                    ],
                  ),
                  isActive: _currentStep >= 1,
                  state: _currentStep > 1 ? StepState.complete : StepState.indexed,
                ),
                Step(
                  title: const Text('Uložení'),
                  content: const Text(
                    'Vše je připraveno! Kliknutím na "Dokončit a uložit" Romy tento proces naučíte.',
                    style: TextStyle(fontSize: 16),
                  ),
                  isActive: _currentStep >= 2,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
