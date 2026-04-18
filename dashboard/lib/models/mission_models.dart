

enum BlockType { automation, aiLogic }

class MissionBlock {
  final String blockId;
  final BlockType type;
  final String? sopReferenceId; // for automation
  final String? instruction; // for aiLogic
  final Map<String, String> inputs;
  final List<String> outputs;

  MissionBlock({
    required this.blockId,
    required this.type,
    this.sopReferenceId,
    this.instruction,
    required this.inputs,
    required this.outputs,
  });

  Map<String, dynamic> toJson() {
    return {
      'block_id': blockId,
      'type': type == BlockType.automation ? 'AUTOMATION' : 'AI_LOGIC',
      if (sopReferenceId != null) 'sop_reference_id': sopReferenceId,
      if (instruction != null) 'instruction': instruction,
      'inputs': inputs,
      'outputs': outputs,
    };
  }
}

class MissionGraph {
  final String missionId;
  final String name;
  final List<MissionBlock> blocks;
  final List<String> executionOrder;

  MissionGraph({
    required this.missionId,
    required this.name,
    required this.blocks,
    required this.executionOrder,
  });

  Map<String, dynamic> toJson() {
    return {
      'mission_id': missionId,
      'name': name,
      'blocks': blocks.map((b) => b.toJson()).toList(),
      'execution_order': executionOrder,
    };
  }
}
