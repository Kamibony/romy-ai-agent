import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dashboard/models/sop_models.dart';
import 'package:dashboard/providers/sop_studio_provider.dart';

void main() {
  group('SopStudioNotifier', () {
    late ProviderContainer container;

    setUp(() {
      container = ProviderContainer();
    });

    tearDown(() {
      container.dispose();
    });

    test('initial state is correct', () {
      final state = container.read(sopStudioProvider);
      expect(state.domain, '');
      expect(state.goal, '');
      expect(state.clientId, isNull);
      expect(state.steps, isEmpty);
      expect(state.isSubmitting, isFalse);
      expect(state.errorMessage, isNull);
    });

    test('initializeDraft updates domain and goal', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.initializeDraft('example.com', 'Test Goal', clientId: '123');

      final state = container.read(sopStudioProvider);
      expect(state.domain, 'example.com');
      expect(state.goal, 'Test Goal');
      expect(state.clientId, '123');
      expect(state.steps, isEmpty);
    });

    test('addStep adds a step with correct type', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.addStep(SopActionType.click, description: 'Click button');

      final state = container.read(sopStudioProvider);
      expect(state.steps.length, 1);
      expect(state.steps.first.actionType, SopActionType.click);
      expect(state.steps.first.description, 'Click button');
      expect(state.steps.first.id, isNotEmpty);
    });

    test('updateStep updates an existing step', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.addStep(SopActionType.type);

      var state = container.read(sopStudioProvider);
      final stepId = state.steps.first.id;
      final updatedStep = state.steps.first.copyWith(text: 'Hello');

      notifier.updateStep(stepId, updatedStep);

      state = container.read(sopStudioProvider);
      expect(state.steps.first.text, 'Hello');
    });

    test('removeStep removes the correct step', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.addStep(SopActionType.click);
      notifier.addStep(SopActionType.wait);

      var state = container.read(sopStudioProvider);
      expect(state.steps.length, 2);
      final idToRemove = state.steps.first.id;

      notifier.removeStep(idToRemove);

      state = container.read(sopStudioProvider);
      expect(state.steps.length, 1);
      expect(state.steps.first.actionType, SopActionType.wait);
    });

    test('reorderSteps moves step correctly', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.addStep(SopActionType.click); // 0
      notifier.addStep(SopActionType.type);  // 1
      notifier.addStep(SopActionType.wait);  // 2

      var state = container.read(sopStudioProvider);
      final firstStepId = state.steps[0].id;

      // Move click from index 0 to index 3 (end)
      notifier.reorderSteps(0, 3);

      state = container.read(sopStudioProvider);
      expect(state.steps.length, 3);
      expect(state.steps[2].id, firstStepId);
      expect(state.steps[0].actionType, SopActionType.type);
    });

    test('validateSequence fails if sequence is empty', () {
      final notifier = container.read(sopStudioProvider.notifier);
      final isValid = notifier.validateSequence();

      final state = container.read(sopStudioProvider);
      expect(isValid, isFalse);
      expect(state.errorMessage, 'Sequence must have at least one step.');
    });

    test('validateSequence fails if TYPE action is missing text', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.addStep(SopActionType.type);

      final isValid = notifier.validateSequence();

      final state = container.read(sopStudioProvider);
      expect(isValid, isFalse);
      expect(state.errorMessage, 'TYPE action must have text.');
    });

    test('validateSequence succeeds if TYPE action has text', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.addStep(SopActionType.type);

      var state = container.read(sopStudioProvider);
      final stepId = state.steps.first.id;
      final updatedStep = state.steps.first.copyWith(text: 'some text');
      notifier.updateStep(stepId, updatedStep);

      final isValid = notifier.validateSequence();

      state = container.read(sopStudioProvider);
      expect(isValid, isTrue);
      expect(state.errorMessage, isNull);
    });

    test('validateSequence fails if NAVIGATE action is missing url', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.addStep(SopActionType.navigate);

      final isValid = notifier.validateSequence();

      final state = container.read(sopStudioProvider);
      expect(isValid, isFalse);
      expect(state.errorMessage, 'NAVIGATE action must have a url.');
    });

    test('validateSequence succeeds if NAVIGATE action has url', () {
      final notifier = container.read(sopStudioProvider.notifier);
      notifier.addStep(SopActionType.navigate);

      var state = container.read(sopStudioProvider);
      final stepId = state.steps.first.id;
      final updatedStep = state.steps.first.copyWith(url: 'https://example.com');
      notifier.updateStep(stepId, updatedStep);

      final isValid = notifier.validateSequence();

      state = container.read(sopStudioProvider);
      expect(isValid, isTrue);
      expect(state.errorMessage, isNull);
    });
  });
}
