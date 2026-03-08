import os
import json
import base64
import io
import re
from typing import Dict, Any, Optional, Tuple

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


# Initialize clients globally if possible
gemini_client = None
anthropic_client = None

if genai is not None:
    try:
        gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    except Exception as e:
        print(f"Failed to initialize Gemini client: {e}")

if Anthropic is not None:
    try:
        anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    except Exception as e:
        print(f"Failed to initialize Anthropic client: {e}")

# Initialize Florence-2 globally
florence_model = None
florence_processor = None

def init_florence():
    global florence_model, florence_processor
    if florence_model is not None and florence_processor is not None:
        return

    try:
        import torch
        from PIL import Image
        from unittest.mock import patch
        from transformers.dynamic_module_utils import get_imports

        # Patch flash_attn import check
        def custom_get_imports(filename):
            if not isinstance(filename, (str, os.PathLike)):
                return get_imports(filename)
            imports = get_imports(filename)
            return [imp for imp in imports if imp != "flash_attn"]

        with patch("transformers.dynamic_module_utils.get_imports", custom_get_imports):
            from transformers import AutoProcessor, AutoModelForCausalLM
            model_id = "microsoft/Florence-2-base-ft"
            florence_processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
            florence_model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)
            print("Florence-2 initialized successfully!")
    except Exception as e:
        print(f"Failed to initialize Florence-2: {e}")


def process_with_gemini(image_b64: str, audio_b64: Optional[str] = None, command_text: Optional[str] = None) -> str:
    """
    Uses Gemini 2.5 Flash to transcribe the audio command (or process textual command) and describe the state of the UI.
    """
    if gemini_client is None:
        print("Gemini client not initialized.")
        return "Error: Gemini client not initialized."

    try:
        client = gemini_client

        contents = []
        if image_b64:
            contents.append(
                types.Part.from_bytes(
                    data=base64.b64decode(image_b64),
                    mime_type="image/png"
                )
            )

        if audio_b64:
            contents.append(
                types.Part.from_bytes(
                    data=base64.b64decode(audio_b64),
                    mime_type="audio/wav"  # Defaulting to wav as client captures wav
                )
            )

        prompt = "Please transcribe the audio command (if any) and briefly describe the state of the UI shown in the image."
        if command_text:
            prompt += f"\nAdditionally, the user provided this text command: '{command_text}'. Treat this as the primary instruction if provided."
        contents.append(prompt)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents
        )

        return response.text
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return f"Error analyzing context with Gemini: {e}"


def detect_ui_elements(image_b64: str) -> Tuple[str, Dict[str, Dict[str, float]]]:
    """
    Passes the raw screenshot to Florence-2 to detect UI elements and draw bounding boxes.
    Returns a base64 encoded image with annotated bounding boxes, and an ID mapping.
    """
    init_florence()
    if florence_model is None or florence_processor is None:
        print("Florence-2 not available.")
        return image_b64, {}

    try:
        from PIL import Image, ImageDraw, ImageFont
        image_bytes = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        task_prompt = "<OD>"
        inputs = florence_processor(text=task_prompt, images=img, return_tensors="pt")

        generated_ids = florence_model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=1024,
            early_stopping=False,
            do_sample=False,
            num_beams=3,
        )
        generated_text = florence_processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed_answer = florence_processor.post_process_generation(
            generated_text,
            task=task_prompt,
            image_size=(img.width, img.height)
        )

        bboxes = parsed_answer.get('<OD>', {}).get('bboxes', [])

        id_map = {}
        draw = ImageDraw.Draw(img)

        for idx, bbox in enumerate(bboxes):
            obj_id = str(idx + 1)
            x1, y1, x2, y2 = bbox
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            id_map[obj_id] = {"x": center_x, "y": center_y}

            draw.rectangle([x1, y1, x2, y2], outline="red", width=2)
            draw.rectangle([x1, y1, x1 + 20, y1 + 20], fill="red")
            draw.text((x1 + 2, y1 + 2), obj_id, fill="white")

        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        annotated_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        return annotated_b64, id_map

    except Exception as e:
        print(f"Error in detect_ui_elements: {e}")
        return image_b64, {}

def get_action_from_claude(image_b64: str, context_text: str) -> Dict[str, Any]:
    """
    Uses Claude 3.5 Sonnet to determine the next logical action based on the Gemini context and annotated screen image.
    Extracts the target_id from the JSON response and maps it to X,Y coordinates.
    """
    if anthropic_client is None:
        print("Anthropic client not initialized.")
        return {"action": "API_ERROR", "error": "Anthropic client not initialized"}

    try:
        from firebase_admin import firestore
        db = firestore.client()
        global_prompt = ""
        try:
            settings_ref = db.collection("settings").document("global_prompt")
            settings_doc = settings_ref.get()
            if settings_doc.exists:
                global_prompt = settings_doc.to_dict().get("prompt", "")
        except Exception as e:
            print(f"Error reading global prompt from Firestore: {e}")

        # Process Set-of-Marks
        annotated_b64, id_map = detect_ui_elements(image_b64)
        if not id_map:
            print("No UI elements detected or Set-of-Marks failed.")
            return {"action": "PARSE_ERROR", "error": "No UI elements detected"}

        client = anthropic_client

        system_prompt = (
            "You are a UI automation agent. An image with numbered bounding boxes is provided. "
            "Based on the user's command and the context, identify the correct target element and return ONLY a JSON block: "
            '{"action": "CLICK", "target_id": "<the_number>"}.\n'
        )
        if global_prompt:
            system_prompt += f"Global Instructions:\n{global_prompt}\n\n"

        user_content = [
            {
                "type": "text",
                "text": f"Context from previous perception layer:\n{context_text}\n\nBased on this context and the annotated screen image, determine the correct target element."
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": annotated_b64
                }
            }
        ]

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content}
            ],
            extra_headers={"anthropic-beta": "computer-use-2024-10-22"}
        )

        response_text = ""
        for block in response.content:
            if block.type == "text":
                response_text += block.text

        match = re.search(r'\{[^{}]*\}', response_text)
        if match:
            try:
                action_data = json.loads(match.group(0))
                if action_data.get("action") == "CLICK" and "target_id" in action_data:
                    target_id = str(action_data["target_id"])
                    if target_id in id_map:
                        coords = id_map[target_id]
                        return {
                            "action": "CLICK",
                            "x": int(coords["x"]),
                            "y": int(coords["y"])
                        }
                    else:
                        return {"action": "PARSE_ERROR", "error": f"target_id {target_id} not found in id_map"}
            except json.JSONDecodeError:
                pass

        return {"action": "PARSE_ERROR", "raw_response": str(response.content)}

    except Exception as e:
        print(f"Error calling Claude: {e}")
        return {"action": "API_ERROR", "error": str(e)}
