import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dashboard/providers/agent_provider.dart';
import 'dart:convert';

class MissionControlScreen extends ConsumerWidget {
  const MissionControlScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final agentState = ref.watch(agentStateProvider);
    final notifier = ref.read(agentStateProvider.notifier);

    return Padding(
      padding: const EdgeInsets.all(16.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                'Mission Control',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              ElevatedButton.icon(
                onPressed: () => _confirmAbort(context, notifier),
                icon: const Icon(Icons.warning, color: Colors.white),
                label: const Text(
                  'Emergency Abort',
                  style: TextStyle(color: Colors.white),
                ),
                style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Row(
            children: [
              _buildStatusCard('Status', agentState.status, context),
              const SizedBox(width: 16),
              _buildStatusCard('Intent', agentState.intent ?? 'N/A', context),
            ],
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Current Action',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    agentState.currentAction ?? 'Waiting for instructions...',
                    style: const TextStyle(fontFamily: 'monospace'),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          if (agentState.helpReason != null) ...[
            Card(
              color: Colors.amber.shade100,
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.info_outline, color: Colors.orange),
                        SizedBox(width: 8),
                        Text(
                          'Human Help Required',
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: Colors.orange,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(agentState.helpReason!),
                    const SizedBox(height: 8),
                    const Text(
                      'Click directly on the Live Preview below to guide the agent.',
                      style: TextStyle(fontStyle: FontStyle.italic),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
          ],
          Expanded(
            child: Card(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Padding(
                    padding: EdgeInsets.all(16.0),
                    child: Text(
                      'Live Preview',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                  ),
                  Expanded(
                    child: agentState.base64Image != null
                        ? LayoutBuilder(
                            builder: (context, constraints) {
                              return GestureDetector(
                                onTapDown: (details) {
                                  if (agentState.originalWidth == null ||
                                      agentState.originalHeight == null)
                                    return;

                                  final double widgetWidth =
                                      constraints.maxWidth;
                                  final double widgetHeight =
                                      constraints.maxHeight;
                                  final double imageWidth = agentState
                                      .originalWidth!
                                      .toDouble();
                                  final double imageHeight = agentState
                                      .originalHeight!
                                      .toDouble();

                                  // Calculate aspect ratios
                                  final double widgetAspect =
                                      widgetWidth / widgetHeight;
                                  final double imageAspect =
                                      imageWidth / imageHeight;

                                  double scale;
                                  double dx = 0.0;
                                  double dy = 0.0;

                                  // Image is wider than the widget -> Letterboxing (black bars on top/bottom)
                                  if (imageAspect > widgetAspect) {
                                    scale = widgetWidth / imageWidth;
                                    double scaledImageHeight =
                                        imageHeight * scale;
                                    dy =
                                        (widgetHeight - scaledImageHeight) /
                                        2.0; // Top offset
                                  }
                                  // Image is taller than the widget -> Pillarboxing (black bars on left/right)
                                  else {
                                    scale = widgetHeight / imageHeight;
                                    double scaledImageWidth =
                                        imageWidth * scale;
                                    dx =
                                        (widgetWidth - scaledImageWidth) /
                                        2.0; // Left offset
                                  }

                                  // Local tap coordinate
                                  final double localX =
                                      details.localPosition.dx;
                                  final double localY =
                                      details.localPosition.dy;

                                  // Remove offset and scale back to original resolution
                                  final double rawX = (localX - dx) / scale;
                                  final double rawY = (localY - dy) / scale;

                                  // Clamp to image bounds
                                  final double clampedX = rawX.clamp(
                                    0.0,
                                    imageWidth,
                                  );
                                  final double clampedY = rawY.clamp(
                                    0.0,
                                    imageHeight,
                                  );

                                  notifier.sendHumanGuidance(
                                    clampedX,
                                    clampedY,
                                  );
                                },
                                child: RepaintBoundary(
                                  child: Image.memory(
                                    base64Decode(agentState.base64Image!),
                                    fit: BoxFit.contain,
                                    gaplessPlayback: true,
                                  ),
                                ),
                              );
                            },
                          )
                        : const Center(
                            child: Text(
                              'No preview available',
                              style: TextStyle(color: Colors.grey),
                            ),
                          ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusCard(String title, String value, BuildContext context) {
    return Expanded(
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text(
                value.toUpperCase(),
                style: TextStyle(
                  fontSize: 18,
                  color: value == 'offline'
                      ? Colors.red
                      : Theme.of(context).primaryColor,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _confirmAbort(BuildContext context, AgentStateNotifier notifier) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Confirm Emergency Abort'),
        content: const Text(
          'Are you sure you want to hard reset the agent execution loop? This will drop the current state.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              notifier.emergencyAbort();
              Navigator.of(context).pop();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('ABORT', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }
}
