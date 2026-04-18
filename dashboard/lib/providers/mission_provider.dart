import 'dart:convert';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../models/mission_models.dart';
import 'api_client_provider.dart';

final missionBuilderProvider = NotifierProvider<MissionBuilderNotifier, MissionGraph>(
  MissionBuilderNotifier.new,
);

class MissionBuilderNotifier extends Notifier<MissionGraph> {
  final _uuid = const Uuid();

  @override
  MissionGraph build() {
    return MissionGraph(
      missionId: 'm_${_uuid.v4()}',
      name: 'New Mission Workflow',
      blocks: [],
      executionOrder: [],
    );
  }

  void addBlock(BlockType type) {
    final blockId = 'b_${_uuid.v4().substring(0, 8)}';
    final newBlock = MissionBlock(
      blockId: blockId,
      type: type,
      inputs: {},
      outputs: type == BlockType.automation ? ['extracted_text'] : ['result'],
      sopReferenceId: type == BlockType.automation ? '' : null,
      instruction: type == BlockType.aiLogic ? '' : null,
    );

    state = MissionGraph(
      missionId: state.missionId,
      name: state.name,
      blocks: [...state.blocks, newBlock],
      executionOrder: [...state.executionOrder, blockId],
    );
  }

  void updateBlock(MissionBlock updatedBlock) {
    final updatedBlocks = state.blocks.map((b) => b.blockId == updatedBlock.blockId ? updatedBlock : b).toList();
    state = MissionGraph(
      missionId: state.missionId,
      name: state.name,
      blocks: updatedBlocks,
      executionOrder: state.executionOrder,
    );
  }

  void removeBlock(String blockId) {
    final updatedBlocks = state.blocks.where((b) => b.blockId != blockId).toList();
    final updatedOrder = state.executionOrder.where((id) => id != blockId).toList();

    state = MissionGraph(
      missionId: state.missionId,
      name: state.name,
      blocks: updatedBlocks,
      executionOrder: updatedOrder,
    );
  }

  void reorderBlocks(int oldIndex, int newIndex) {
    if (oldIndex < newIndex) {
      newIndex -= 1;
    }
    final List<String> updatedOrder = List.from(state.executionOrder);
    final String item = updatedOrder.removeAt(oldIndex);
    updatedOrder.insert(newIndex, item);

    state = MissionGraph(
      missionId: state.missionId,
      name: state.name,
      blocks: state.blocks,
      executionOrder: updatedOrder,
    );
  }

  void updateMissionName(String newName) {
    state = MissionGraph(
      missionId: state.missionId,
      name: newName,
      blocks: state.blocks,
      executionOrder: state.executionOrder,
    );
  }

  Future<bool> executeMission() async {
    try {
      final apiClient = ref.read(apiClientProvider);
      final response = await apiClient.post(
        '/api/v1/mission/execute',
        body: json.encode(state.toJson()),
      );
      return response.statusCode == 200 || response.statusCode == 202;
    } catch (e) {
      return false;
    }
  }
}
