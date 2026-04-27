from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class MissionBlock(BaseModel):
    block_id: str
    type: str
    sop_reference_id: Optional[str] = None
    instruction: Optional[str] = None
    inputs: Dict[str, str] = Field(default_factory=dict)
    outputs: List[str] = Field(default_factory=list)

class MissionGraph(BaseModel):
    mission_id: str
    name: str
    blocks: List[MissionBlock]
    execution_order: List[str]

async def execute_mission_orchestrator(mission_graph: MissionGraph, doc_id: str):
    import logging
    import aiohttp

    TELEMETRY_PORT = 8764 # Usually 8764 for local agent
    start_url = f"http://127.0.0.1:{TELEMETRY_PORT}/api/recording/start"
    stop_url = f"http://127.0.0.1:{TELEMETRY_PORT}/api/recording/stop"

    try:
        async with aiohttp.ClientSession() as session:
            # 1. Trigger Recording
            logging.info(f"Triggering background recording for mission {doc_id}")
            try:
                async with session.post(start_url, timeout=5) as resp:
                    if resp.status == 200:
                        logging.info("Recording started successfully.")
                    else:
                        logging.warning(f"Failed to start recording: HTTP {resp.status}")
            except Exception as e:
                logging.error(f"Error starting recording: {e}")

            # 2. Execute the actual mission blocks (Semantic Mission)
            # In MVP, this relies on client's execute_mission which is synchronous or handled by AgentStateMachine
            # For demonstration, we simply parse it. Real execution is handled locally by the agent node.
            # We assume the agent node is actively processing this doc_id

            logging.info(f"Executing semantic mission {mission_graph.name}...")
            # We would wait for mission completion here, for MVP we just trigger.
            # In a full flow, you'd wait for completion status from Firebase or WebSocket

            # ... Wait for agent to finish (placeholder for actual await) ...
            import asyncio
            await asyncio.sleep(2) # minimal yield

            # 3. Stop Recording
            logging.info("Triggering stop background recording...")
            try:
                async with session.post(stop_url, timeout=5) as resp:
                    if resp.status == 200:
                        logging.info("Recording stopped successfully.")
                    else:
                        logging.warning(f"Failed to stop recording: HTTP {resp.status}")
            except Exception as e:
                logging.error(f"Error stopping recording: {e}")

    except Exception as e:
        logging.error(f"Error in execute_mission_orchestrator: {e}")
