# Alternative Setup Guide for Restricted Environments (e.g. University/Corporate IT)

If the `.exe` file provided by the standard installer is being blocked by your IT policies (such as SmartScreen or Managed Apps policies), you can still run the ROMY Agent by following this non-technical setup guide.

This alternative method relies on running the source code directly using a standard Python installation, which is typically not blocked by such policies.

## Step 1: Install Python

1. Go to the official Python download page: https://www.python.org/downloads/
2. Click the yellow button to **Download Python** (the latest version is fine, e.g., 3.12+).
3. **IMPORTANT:** When you run the downloaded installer, look at the very bottom of the first screen. Make sure to **check the box** that says **"Add python.exe to PATH"**. This step is critical; without it, the runner script won't be able to find Python.
4. Click **"Install Now"** and follow the prompts.

## Step 2: Download the ROMY Agent Source

1. Obtain the `client` folder for the ROMY Agent. This may be provided to you as a `.zip` file.
2. If it's a `.zip` file, right-click it and select **"Extract All..."**. Choose a location like your Documents or Desktop folder.

## Step 3: Run the Agent

1. Open the extracted `client` folder.
2. Locate the file named **`run_romy.bat`** (it might just appear as `run_romy` depending on your Windows settings, but it will have a gear/batch file icon). Note that this script expects the source files to be inside an `app/` subdirectory in the same folder as the script, or alternatively in the same folder as the script itself.
3. Double-click **`run_romy.bat`**.

### What happens next?

- A black command prompt window will briefly appear.
- It will automatically install any required components (dependencies) the very first time you run it.
- Once finished, the command prompt will close automatically.
- The ROMY Agent is now running in the background! You should see its icon appear in your System Tray (the area in the bottom-right corner of your screen, near the clock).

## Troubleshooting

- **"Python is not installed or not added to your PATH" error:** You likely forgot to check the box in Step 1.3. Re-run the Python installer, select "Modify", and ensure "Add Python to environment variables" is checked.
- **"Failed to install dependencies":** Make sure you are connected to the internet. If you are on a very strict network, a firewall might be blocking the download of Python packages. Try connecting to a different network temporarily.