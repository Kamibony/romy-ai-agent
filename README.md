# romy-ai-agent

## Packaging the Desktop Client

To package the Python desktop client into a standalone, windowless executable (`.exe`), you can use the provided build scripts.

1. Navigate to the `client/` directory.
2. Ensure you have installed the required dependencies, including PyInstaller.
3. Run one of the build scripts:
   - **Windows:** Double-click `build_exe.bat` or run it from the command prompt: `build_exe.bat`
   - **Cross-platform/Python:** Run `python build_exe.py`

This will generate a `dist/` directory inside `client/` containing the standalone `ROMY Agent.exe` executable file, configured to run silently with a system tray interface.