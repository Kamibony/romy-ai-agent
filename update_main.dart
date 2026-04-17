import 'dart:io';

void main() {
  var file = File('dashboard/lib/main.dart');
  var content = file.readAsStringSync();

  content = content.replaceAll(
    "title: const Text('Romy Dashboard'),",
    "title: const Text('Romy AI'),"
  );
  content = content.replaceAll(
    "label: Text('Mission Control'),",
    "label: Text('Moje procesy'),"
  );
  content = content.replaceAll(
    "label: Text('SOP Studio'),",
    "label: Text('Trénink Romy'),"
  );
  content = content.replaceAll(
    "label: Text('Memory Manager'),",
    "label: Text('Znalosti'),"
  );

  file.writeAsStringSync(content);
}
