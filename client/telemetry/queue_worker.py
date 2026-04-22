import asyncio
import logging
from typing import Dict, Any, Callable
from .masking import mask_dict_pii
from datetime import datetime, timezone
import json
import os

TELEMETRY_QUEUE = None

async def run_in_threadpool(func: Callable, *args: Any, **kwargs: Any) -> Any:
    """Mimics FastAPI's run_in_threadpool to comply with backend guidelines."""
    import functools
    loop = asyncio.get_running_loop()
    if kwargs:
        func = functools.partial(func, **kwargs)
    return await loop.run_in_executor(None, func, *args)

def emit_telemetry(payload: Dict[str, Any]):
    """Emits telemetry event by putting it into the async queue."""
    global TELEMETRY_QUEUE
    if TELEMETRY_QUEUE is None:
        try:
            TELEMETRY_QUEUE = asyncio.Queue()
        except RuntimeError:
            return # No event loop
    try:
        masked_payload = mask_dict_pii(payload)
        masked_payload['timestamp'] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        # Ensure thread safety if called from a different thread, though usually called from the main loop
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(TELEMETRY_QUEUE.put_nowait, masked_payload)
        except RuntimeError:
            pass # No running event loop
    except Exception as e:
        logging.error(f"Failed to emit telemetry: {e}")

async def telemetry_worker_loop(firestore_update_fn):
    """Async worker loop that continuously drains the queue and writes to Firestore."""
    logging.info("Starting Async Telemetry Worker Loop...")
    global TELEMETRY_QUEUE
    if TELEMETRY_QUEUE is None:
        TELEMETRY_QUEUE = asyncio.Queue()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = os.path.join(local_app_data, "RomyAgentBrowserData")
    else:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "RomyAgentBrowserData"))

    log_dir = os.path.join(base_dir, "telemetry_logs")
    os.makedirs(log_dir, exist_ok=True)

    while True:
        try:
            item = await TELEMETRY_QUEUE.get()
            try:
                # Following backend guidelines: wrap synchronous Firebase writes in to_thread to prevent event loop starvation
                doc_id = f"log_{item['mission_id']}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                await run_in_threadpool(firestore_update_fn, "telemetry_logs", doc_id, item)

                # Local log file fallback
                log_file = os.path.join(log_dir, f"{datetime.now().strftime('%Y%m%d')}.jsonl")
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(item) + "\n")
            except Exception as e:
                logging.error(f"Error processing telemetry item: {e}")
            finally:
                TELEMETRY_QUEUE.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Telemetry worker loop error: {e}")
