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

import logging
import asyncio
import re
from firebase_admin import firestore
from db import update_task_session
from ai_service import get_gemini_client

async def execute_mission_orchestrator(mission_graph: MissionGraph, session_id: str):
    # Architectural Pattern: Pull/Listen via Firestore Task Queue
    # We write instructions to a session document and wait for the local client to execute and report back
    db = firestore.client()
    doc_ref = db.collection("task_sessions").document(session_id)

    context = {}

    try:
        # 1. Trigger Recording (Queue instruction for the client)
        logging.info(f"Triggering background recording for mission {session_id} via Firestore")
        update_task_session(session_id, {"status": "recording_start_requested"})

        # Wait for client to ack recording start
        async def wait_for_status(target_status: str, timeout: int = 10):
            import time
            start = time.time()
            while time.time() - start < timeout:
                doc = await asyncio.to_thread(doc_ref.get)
                if doc.exists and doc.to_dict().get("status") == target_status:
                    return True
                await asyncio.sleep(1)
            return False

        await wait_for_status("recording_started")

        # 2. Execute Semantic Mission Blocks
        logging.info(f"Executing semantic mission {mission_graph.name}...")

        blocks_dict = {b.block_id: b for b in mission_graph.blocks}
        for block_id in mission_graph.execution_order:
            block = blocks_dict.get(block_id)
            if not block:
                continue

            logging.info(f"Executing block: {block_id} of type: {block.type}")

            # Resolve template variables
            resolved_inputs = {}
            for k, v in block.inputs.items():
                if isinstance(v, str):
                    matches = re.findall(r"\{\{(.*?)\}\}", v)
                    for match in matches:
                        v = v.replace(f"{{{{{match}}}}}", str(context.get(match, "")))
                resolved_inputs[k] = v

            if block.type == "AUTOMATION":
                # Delegate to Client via Firestore
                update_task_session(session_id, {
                    "status": "executing_block",
                    "current_block": {
                        "block_id": block_id,
                        "instruction": resolved_inputs.get("instruction", ""),
                        "sop_reference_id": block.sop_reference_id,
                        "url": resolved_inputs.get("url", "")
                    }
                })

                # Wait for client to complete this block (we give it up to 600s)
                success = await wait_for_status("block_completed", timeout=600)
                if not success:
                    logging.warning(f"Timeout or failure executing block {block_id}")
                    break

                # Harvest block output context
                doc = await asyncio.to_thread(doc_ref.get)
                block_outputs = doc.to_dict().get("block_outputs", {})
                context.update(block_outputs.get(block_id, {}))

            elif block.type == "AI_LOGIC":
                instruction = block.instruction or ""
                raw_text = resolved_inputs.get("raw_text", "")
                prompt = f"{instruction}\n\nData:\n{raw_text}"

                try:
                    client = get_gemini_client()
                    if client:
                        def run_gemini():
                            import google.generativeai as genai
                            model = genai.GenerativeModel('gemini-2.5-flash')
                            return model.generate_content(prompt)

                        response = await asyncio.to_thread(run_gemini)
                        context[f"{block_id}.output"] = response.text.strip()
                    else:
                        logging.error("GEMINI_API_KEY not set for AI_LOGIC block")
                except Exception as e:
                    logging.error(f"Error in AI_LOGIC block {block_id}: {e}")
                    break

        # 3. Stop Recording
        logging.info("Triggering stop background recording...")
        update_task_session(session_id, {"status": "recording_stop_requested", "mission_context": context})
        await wait_for_status("completed", timeout=10)

    except Exception as e:
        logging.error(f"Error in execute_mission_orchestrator: {e}")
        update_task_session(session_id, {"status": "failed", "error": str(e)})
