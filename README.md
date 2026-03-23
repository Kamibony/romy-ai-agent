# romy-ai-agent

## Packaging the Desktop Client

To package the Python desktop client into a standalone, windowless executable (`.exe`), you can use the provided build scripts.

1. Navigate to the `client/` directory.
2. Ensure you have installed the required dependencies, including PyInstaller.
3. Run one of the build scripts:
   - **Windows:** Double-click `build_exe.bat` or run it from the command prompt: `build_exe.bat`
   - **Cross-platform/Python:** Run `python build_exe.py`

This will generate a `dist/` directory inside `client/` containing the standalone `ROMY Agent.exe` executable file, configured to run silently with a system tray interface.

## Alternative Deployment (Restricted Environments)

If the `.exe` file is blocked by IT policies (e.g., SmartScreen, Managed Apps) in corporate or university environments, users can run the client directly from source using a standard Python installation. This avoids `.exe` execution restrictions.

Please refer to the non-technical setup guide located at `client/SETUP_GUIDE.md` for instructions on how to set this up using the provided `run_romy.bat` script.