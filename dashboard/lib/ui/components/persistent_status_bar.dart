import 'package:flutter/material.dart';

class PersistentStatusBar extends StatelessWidget {
  const PersistentStatusBar({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.blue.shade100,
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
      child: const Row(
        children: [
          Icon(Icons.info_outline, color: Colors.blue),
          SizedBox(width: 8.0),
          Text('Status: Ready'),
        ],
      ),
    );
  }
}
