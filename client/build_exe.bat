@echo off
echo Building ROMY AI Agent Desktop Client...

:: Navigate to client directory
cd /d "%~dp0"

:: Install PyInstaller if not already installed
pip install pyinstaller

:: Clean up previous builds
rmdir /s /q build
rmdir /s /q dist

:: Build the executable
:: --noconfirm: Overwrite output directory without confirming
:: --windowed: Run as a windowless application (no console)
:: --icon: Apply the custom placeholder icon
:: --add-data: Include the icon file and any other necessary assets in the build
:: --onefile: Build as a single standalone executable file

pyinstaller --noconfirm ^
            --onefile ^
            --windowed ^
            --icon=icon.ico ^
            --add-data="icon.ico;." ^
            --name="ROMY Agent" ^
            main.py

echo Build Complete! The executable is located in the client/dist folder.
pause
