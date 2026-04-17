import 'dart:io';

void main() {
  var file = File('dashboard/lib/ui/memory_manager/memory_manager_screen.dart');
  var content = file.readAsStringSync();

  content = content.replaceFirst(
    "Text(\n            'Memory Manager',",
    "Text(\n            'Znalosti',"
  );

  file.writeAsStringSync(content);
}
