import typer
import yaml
import json
import requests
import os
from pathlib import Path

app = typer.Typer(help="Romy AI Developer CLI")

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
DUMMY_UID = "dummy_cli_user" # Normally we'd need a real Firebase token if auth is strict, but for local dev we can bypass or mock if configured.
# NOTE: If the backend strictly enforces verify_firebase_token, we might need a test token or to disable it in local dev.
# For now, we will send a request and let it fail if auth is strict, which can be fixed in a local dev mode override.

@app.command()
def trigger(instruction: str, url: str = "https://example.com"):
    """Trigger a one-off mission task."""
    payload = {
        "mission_id": "cli_test_mission",
        "name": "CLI Triggered Mission",
        "blocks": [
            {
                "block_id": "b1",
                "type": "AUTOMATION",
                "instruction": instruction,
                "inputs": {"url": url},
                "outputs": []
            }
        ],
        "execution_order": ["b1"]
    }

    headers = {"Authorization": f"Bearer {DUMMY_UID}"}

    try:
        response = requests.post(f"{BACKEND_URL}/api/v1/mission/execute", json=payload, headers=headers)
        if response.status_code == 200:
            typer.echo(f"Mission started successfully: {response.json()}")
        else:
            typer.echo(f"Failed to start mission. Status: {response.status_code}, Detail: {response.text}")
    except requests.exceptions.ConnectionError:
        typer.echo("Error: Could not connect to the backend. Is it running?")

@app.command()
def run_scenario(scenario_file: Path):
    """Run a complex scenario from a YAML/JSON fixture."""
    if not scenario_file.exists():
        typer.echo(f"Error: File {scenario_file} not found.")
        raise typer.Exit(code=1)

    try:
        if scenario_file.suffix in ['.yaml', '.yml']:
            with open(scenario_file, 'r') as f:
                payload = yaml.safe_load(f)
        elif scenario_file.suffix == '.json':
            with open(scenario_file, 'r') as f:
                payload = json.load(f)
        else:
            typer.echo("Unsupported file format. Please provide a .yaml or .json file.")
            raise typer.Exit(code=1)

        headers = {"Authorization": f"Bearer {DUMMY_UID}"}
        response = requests.post(f"{BACKEND_URL}/api/v1/mission/execute", json=payload, headers=headers)

        if response.status_code == 200:
            typer.echo(f"Scenario started successfully: {response.json()}")
        else:
            typer.echo(f"Failed to start scenario. Status: {response.status_code}, Detail: {response.text}")

    except Exception as e:
        typer.echo(f"Error processing scenario: {e}")

if __name__ == "__main__":
    app()
