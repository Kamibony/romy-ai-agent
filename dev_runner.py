import os
import sys
import subprocess
import asyncio
import platform
import argparse
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, RichLog, Static
from textual.color import Color

from textual.color import Color
from rich.text import Text
from aiohttp import web


# Paths
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
CLIENT_DIR = ROOT_DIR / "client"
DASHBOARD_DIR = ROOT_DIR / "dashboard"

BACKEND_VENV = BACKEND_DIR / "venv"
CLIENT_VENV = CLIENT_DIR / "venv"

# Commands
def get_python_cmd(venv_dir):
    if platform.system() == "Windows":
        return str(venv_dir / "Scripts" / "python.exe")
    return str(venv_dir / "bin" / "python")

def get_pip_cmd(venv_dir):
    if platform.system() == "Windows":
        return str(venv_dir / "Scripts" / "pip.exe")
    return str(venv_dir / "bin" / "pip")

def setup_venv(venv_dir, req_file):
    if not venv_dir.exists():
        print(f"[SETUP] Creating virtual environment at {venv_dir}...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    pip_cmd = get_pip_cmd(venv_dir)
    print(f"[SETUP] Installing requirements from {req_file}...")
    subprocess.run([pip_cmd, "install", "-r", str(req_file)], check=True)

def setup_all():
    print("=== Starting Setup ===")
    setup_venv(BACKEND_VENV, BACKEND_DIR / "requirements.txt")
    setup_venv(CLIENT_VENV, CLIENT_DIR / "requirements.txt")
    # Install dev dependencies to root env if running outside venv or provide instructions
    setup_venv(CLIENT_VENV, ROOT_DIR / "requirements_dev.txt")
    print("=== Setup Complete ===")

class ServicePane(Vertical):
    def __init__(self, name: str, title: str, color: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service_name = name
        self.title_text = title
        self.theme_color = color
        self.border_title = title
        self.styles.border = ("round", color)

    def compose(self) -> ComposeResult:
        self.log_widget = RichLog(highlight=True, markup=True)
        yield self.log_widget

    def write_log(self, text: str):
        # Apply the color to the [NAME] prefix or the whole line depending on preference
        styled_text = f"[{self.theme_color}][{self.service_name}][/] {text}"
        self.log_widget.write(styled_text)

    def write_raw(self, text: str):
        self.log_widget.write(text)

class MonorepoDashboardApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #main_container {
        layout: horizontal;
        height: 100%;
    }

    ServicePane {
        width: 1fr;
        height: 100%;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit")
    ]

    def __init__(self, run_setup=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_setup = run_setup
        self.processes = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main_container"):
            self.backend_pane = ServicePane("BACKEND", "FastAPI Backend", "cyan")
            self.client_pane = ServicePane("CLIENT", "Python Daemon", "green")
            self.dashboard_pane = ServicePane("DASHBOARD", "Flutter UI", "magenta")
            self.extension_pane = ServicePane("EXTENSION", "Chrome Ext", "yellow")

            yield self.backend_pane
            yield self.client_pane
            yield self.dashboard_pane
            yield self.extension_pane
        yield Footer()


    async def run_extension_log_server(self):
        async def handle_log(request):
            try:
                data = await request.json()
                log_type = data.get("type", "INFO")
                message = data.get("message", "")
                source = data.get("source", "EXT")
                self.extension_pane.write_log(f"[{source}] [{log_type}] {message}")
                return web.json_response({"status": "ok"})
            except Exception as e:
                return web.json_response({"status": "error", "message": str(e)}, status=400)

        app = web.Application()
        # Handle CORS for local extension testing
        async def cors_middleware(app, handler):
            async def middleware(request):
                if request.method == 'OPTIONS':
                    resp = web.Response()
                else:
                    resp = await handler(request)
                resp.headers['Access-Control-Allow-Origin'] = '*'
                resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
                resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
                return resp
            return middleware

        app.middlewares.append(cors_middleware)
        app.add_routes([web.post('/log', handle_log)])

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 8765)
        await site.start()
        self.extension_pane.write_log("[SYSTEM] Log server listening on port 8765")

        # Keep alive
        while True:
            await asyncio.sleep(3600)

    async def on_mount(self) -> None:

        if self.run_setup:
            self.backend_pane.write_log("Starting setup...")
            # Ideally setup_all would be async to not block the UI, but we can offload to a thread
            await asyncio.to_thread(setup_all)
            self.backend_pane.write_log("Setup complete.")

        os.environ["LOCAL_DEV"] = "True"
        os.environ["ROMY_TEST_MODE"] = "1"

        backend_python = get_python_cmd(BACKEND_VENV)
        client_python = get_python_cmd(CLIENT_VENV)

        backend_cmd = [backend_python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"]
        client_cmd = [client_python, "main.py"]

        is_windows = platform.system() == "Windows"
        flutter_cmd = ["flutter.bat"] if is_windows else ["flutter"]
        dashboard_cmd = flutter_cmd + ["run", "-d", "chrome", "--web-port", "3000", "--dart-define", "BACKEND_PORT=8000", "--dart-define", "TELEMETRY_PORT=8764"]


        # Start Extension Log Server
        asyncio.create_task(self.run_extension_log_server())

        # Start processes

        asyncio.create_task(self.run_service(self.backend_pane, backend_cmd, BACKEND_DIR))
        await asyncio.sleep(1) # slight stagger
        asyncio.create_task(self.run_service(self.client_pane, client_cmd, CLIENT_DIR))
        await asyncio.sleep(1)
        asyncio.create_task(self.run_service(self.dashboard_pane, dashboard_cmd, DASHBOARD_DIR))

    async def run_service(self, pane: ServicePane, cmd: list, cwd: Path):
        pane.write_log(f"Starting: {' '.join(cmd)}")
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=os.environ.copy()
            )
            self.processes.append((pane.service_name, process))

            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                decoded_line = line.decode('utf-8', errors='replace').rstrip()
                pane.write_raw(decoded_line)

            await process.wait()
            if process.returncode != 0 and process.returncode is not None and process.returncode > 0:
                pane.write_log(f"[bold red]Crashed with exit code {process.returncode}[/bold red]")

        except Exception as e:
            pane.write_log(f"[bold red]Error: {e}[/bold red]")

    async def on_unmount(self) -> None:
        # Graceful shutdown
        for name, p in self.processes:
            try:
                p.terminate()
            except ProcessLookupError:
                pass

        await asyncio.sleep(1)
        for name, p in self.processes:
            try:
                if p.returncode is None:
                    p.kill()
            except ProcessLookupError:
                pass

def main():
    parser = argparse.ArgumentParser(description="Monorepo E2E Local Dev Environment Runner")
    parser.add_argument("--setup-only", action="store_true", help="Only setup virtual environments and exit")
    args = parser.parse_args()

    if args.setup_only:
        setup_all()
        print("Setup complete. Exiting.")
        return

    app = MonorepoDashboardApp(run_setup=False)
    app.run()

if __name__ == "__main__":
    main()
