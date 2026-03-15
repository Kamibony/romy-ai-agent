import os
import subprocess
import shutil
import sys

def build():
    print("Building ROMY AI Agent Desktop Client...")

    # Ensure PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Get current directory and ensure we're in the client folder
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(current_dir)

    # Install project dependencies
    print("Installing project dependencies from requirements.txt...")
    req_path = os.path.join(current_dir, "requirements.txt")
    if os.path.exists(req_path):
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_path])
    else:
        print(f"Warning: {req_path} not found. Skipping dependency installation.")

    # Clean up previous builds
    for d in ['build', 'dist']:
        if os.path.exists(d):
            shutil.rmtree(d)

    # Determine OS-specific separator for --add-data
    sep = ';' if os.name == 'nt' else ':'

    # Build command
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--icon=icon.ico",
        f"--add-data=icon.ico{sep}.",
        "--name=ROMY Agent",
        "main.py"
    ]

    # Execute build
    print("Running PyInstaller:", " ".join(cmd))
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("Build Complete! The executable is located in the client/dist folder.")
    else:
        print("Build Failed.")

if __name__ == "__main__":
    build()
