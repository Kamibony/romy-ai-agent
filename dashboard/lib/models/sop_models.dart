// Enum defining the supported action types, strictly mirroring the Agent's ontology.
enum SopActionType {
  click('CLICK'),
  type('TYPE'),
  wait('WAIT'),
  waitFor('WAIT_FOR'),
  navigate('NAVIGATE'),
  hover('HOVER');

  final String agentValue;
  const SopActionType(this.agentValue);
}

// Represents a single step in the SOP sequence.
class SopStep {
  final String id; // Unique ID for reordering/UI mapping
  SopActionType actionType;

  // Optional depending on actionType
  String? targetName; // e.g., "Submit Button"
  String? targetId; // CDP target ID or CSS selector if known
  String? text; // Used for TYPE actions
  String? url; // Used for NAVIGATE actions
  int? durationMs; // Used for WAIT actions
  String? description; // Human-readable description/intent
  int? x; // Spatial fallback X coordinate
  int? y; // Spatial fallback Y coordinate

  SopStep({
    required this.id,
    required this.actionType,
    this.targetName,
    this.targetId,
    this.text,
    this.url,
    this.durationMs,
    this.description,
    this.x,
    this.y,
  });

  Map<String, dynamic> toJson() {
    return {
      'action_type': actionType.agentValue,
      if (targetName != null) 'target_name': targetName,
      if (targetId != null) 'target_id': targetId,
      if (text != null) 'text': text,
      if (url != null) 'url': url,
      if (durationMs != null) 'duration_ms': durationMs,
      if (description != null) 'description': description,
      if (x != null) 'x': x,
      if (y != null) 'y': y,
    };
  }

  SopStep copyWith({
    String? id,
    SopActionType? actionType,
    String? targetName,
    String? targetId,
    String? text,
    String? url,
    int? durationMs,
    String? description,
    int? x,
    int? y,
  }) {
    return SopStep(
      id: id ?? this.id,
      actionType: actionType ?? this.actionType,
      targetName: targetName ?? this.targetName,
      targetId: targetId ?? this.targetId,
      text: text ?? this.text,
      url: url ?? this.url,
      durationMs: durationMs ?? this.durationMs,
      description: description ?? this.description,
      x: x ?? this.x,
      y: y ?? this.y,
    );
  }
}

// Represents the full payload sent to the backend.
class SopPayload {
  final String domain;
  final String goal;
  final String? clientId;
  final List<SopStep> recordedSteps;

  SopPayload({
    required this.domain,
    required this.goal,
    this.clientId,
    required this.recordedSteps,
  });

  Map<String, dynamic> toJson() {
    return {
      'domain': domain,
      'goal': goal,
      if (clientId != null) 'client_id': clientId,
      'recorded_steps': recordedSteps.map((step) => step.toJson()).toList(),
    };
  }
}
