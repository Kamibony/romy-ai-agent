import 'dart:io';

void main() {
  var file = File('dashboard/lib/main.dart');
  var content = file.readAsStringSync();

  content = content.replaceFirst(
    "import 'ui/memory_manager/memory_manager_screen.dart';",
    "import 'ui/memory_manager/memory_manager_screen.dart';\nimport 'ui/components/persistent_status_bar.dart';"
  );

  content = content.replaceFirst(
    '''
      body: Row(
        children: [
          NavigationRail(
''',
    '''
      body: Column(
        children: [
          const PersistentStatusBar(),
          Expanded(
            child: Row(
              children: [
                NavigationRail(
'''
  );

  content = content.replaceFirst(
    '''
          Expanded(child: _screens[_selectedIndex]),
        ],
      ),
''',
    '''
                Expanded(child: _screens[_selectedIndex]),
              ],
            ),
          ),
        ],
      ),
'''
  );

  file.writeAsStringSync(content);
}
