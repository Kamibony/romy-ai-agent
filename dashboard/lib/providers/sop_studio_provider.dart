import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import 'dart:convert';
import '../models/sop_models.dart';
import 'api_client_provider.dart';

class SopStudioState {
  final String domain;
  final String goal;
  final String? clientId;
  final List<SopStep> steps;
  final bool isSubmitting;
  final String? errorMessage;

  SopStudioState({
    this.domain = '',
    this.goal = '',
    this.clientId,
    this.steps = const [],
    this.isSubmitting = false,
    this.errorMessage,
  });

  SopStudioState copyWith({
    String? domain,
    String? goal,
    String? clientId,
    List<SopStep>? steps,
    bool? isSubmitting,
    String? errorMessage,
  }) {
    return SopStudioState(
      domain: domain ?? this.domain,
      goal: goal ?? this.goal,
      clientId: clientId ?? this.clientId,
      steps: steps ?? this.steps,
      isSubmitting: isSubmitting ?? this.isSubmitting,
      errorMessage: errorMessage ?? this.errorMessage,
    );
  }
}

class SopStudioNotifier extends Notifier<SopStudioState> {
  final _uuid = const Uuid();

  @override
  SopStudioState build() {
    return SopStudioState();
  }

  void initializeDraft(String domain, String goal, {String? clientId}) {
    state = SopStudioState(
      domain: domain,
      goal: goal,
      clientId: clientId,
      steps: [],
    );
  }

  void addStep(SopActionType type, {String? description}) {
    final newStep = SopStep(
      id: _uuid.v4(),
      actionType: type,
      description: description,
    );
    state = state.copyWith(steps: [...state.steps, newStep], errorMessage: null);
  }

  void updateStep(String stepId, SopStep updatedStep) {
    final updatedSteps = state.steps.map((step) {
      if (step.id == stepId) {
        return updatedStep;
      }
      return step;
    }).toList();
    state = state.copyWith(steps: updatedSteps, errorMessage: null);
  }

  void removeStep(String stepId) {
    final updatedSteps = state.steps.where((step) => step.id != stepId).toList();
    state = state.copyWith(steps: updatedSteps, errorMessage: null);
  }

  void reorderSteps(int oldIndex, int newIndex) {
    if (oldIndex < 0 || oldIndex >= state.steps.length || newIndex < 0 || newIndex > state.steps.length) {
      return;
    }
    final steps = List<SopStep>.from(state.steps);
    var actualNewIndex = newIndex;
    if (oldIndex < newIndex) {
      actualNewIndex -= 1;
    }
    final step = steps.removeAt(oldIndex);
    steps.insert(actualNewIndex, step);
    state = state.copyWith(steps: steps, errorMessage: null);
  }

  bool validateSequence() {
    if (state.steps.isEmpty) {
      state = state.copyWith(errorMessage: 'Sequence must have at least one step.');
      return false;
    }

    for (var step in state.steps) {
      if (step.actionType == SopActionType.type) {
        if (step.text == null || step.text!.isEmpty) {
          state = state.copyWith(errorMessage: 'TYPE action must have text.');
          return false;
        }
      } else if (step.actionType == SopActionType.navigate) {
        if (step.url == null || step.url!.isEmpty) {
          state = state.copyWith(errorMessage: 'NAVIGATE action must have a url.');
          return false;
        }
      }
    }

    state = state.copyWith(errorMessage: null);
    return true;
  }

  Future<bool> submitSop() async {
    if (!validateSequence()) {
      return false;
    }

    if (state.domain.isEmpty || state.goal.isEmpty) {
      state = state.copyWith(errorMessage: 'Domain and Goal must be provided.');
      return false;
    }

    state = state.copyWith(isSubmitting: true, errorMessage: null);

    try {
      final payload = SopPayload(
        domain: state.domain,
        goal: state.goal,
        clientId: state.clientId,
        recordedSteps: state.steps,
      );

      final apiClient = ref.read(apiClientProvider);
      final response = await apiClient.post(
        '/api/v1/memory/sops',
        body: jsonEncode(payload.toJson()),
      );

      if (response.statusCode == 200) {
        state = state.copyWith(isSubmitting: false);
        return true;
      } else {
        state = state.copyWith(
          isSubmitting: false,
          errorMessage: 'Failed to submit SOP: ${response.statusCode} - ${response.body}',
        );
        return false;
      }
    } catch (e) {
      state = state.copyWith(
        isSubmitting: false,
        errorMessage: 'An error occurred while submitting: $e',
      );
      return false;
    }
  }
}

final sopStudioProvider = NotifierProvider<SopStudioNotifier, SopStudioState>(() {
  return SopStudioNotifier();
});
