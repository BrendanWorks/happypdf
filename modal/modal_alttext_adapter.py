"""
Alt text generation adapter using a lightweight vision model.

Simple end-to-end endpoint that generates alt text from images
with an accessibility-focused prompt.

To run local test:
    modal run modal_alttext_adapter.py --image-path /path/to/image.png

To deploy:
    modal deploy modal_alttext_adapter.py
"""

import base64
import json
import subprocess
import tempfile
from pathlib import Path
from io import BytesIO

import modal
from PIL import Image

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "Pillow",
        "torch>=2.0",
        "torchvision>=0.17.0",
        "transformers>=4.40.0",
        "accelerate",
        "bitsandbytes",
    )
)

app = modal.App("pdfaccess-alttext", image=image)


@app.function(gpu="H100", timeout=300, memory=20480)
def generate_alt_text(
    image_b64: str,
    context: str = None,
    max_tokens: int = 150,
) -> dict:
    """
    Generate alt text from base64 image using Qwen2.5-VL.

    Args:
        image_b64: Base64-encoded image
        context: Optional document context
        max_tokens: Max tokens to generate

    Returns:
        {
            "alt_text": str,
            "requires_long_desc": bool,
            "confidence": float,
            "success": bool,
            "error": str (if failed)
        }
    """
    try:
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
        import torch

        print("[AltText] Decoding image...")
        image_data = base64.b64decode(image_b64)
        image = Image.open(BytesIO(image_data)).convert("RGB")

        # Resize if needed
        if image.width > 896:
            scale = 896 / image.width
            image = image.resize(
                (896, max(1, int(image.height * scale))), Image.LANCZOS
            )

        # Build prompt
        base_prompt = (
            "Describe this image for use as HTML alt text for a screen reader user. "
            "Be specific and concise. If this is a chart, graph, map, or data visualization, "
            "say so explicitly and note that a longer description is needed."
        )

        if context:
            full_prompt = f"{base_prompt}\n\nContext: {context[:150]}\n\nAlt text:"
        else:
            full_prompt = f"{base_prompt}\n\nAlt text:"

        print("[AltText] Loading Qwen2.5-VL...")
        processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-7B-Instruct")
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            "Qwen/Qwen2-VL-7B-Instruct",
            torch_dtype=torch.float16,
            device_map="auto",
        )
        model.eval()

        print("[AltText] Processing image...")
        text = processor.apply_chat_template(
            [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": full_prompt}]}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = processor(text=[text], images=[image], return_tensors="pt")

        # Move inputs to GPU
        device = "cuda" if torch.cuda.is_available() else "cpu"
        inputs = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in inputs.items()}

        print("[AltText] Generating alt text...")
        with torch.inference_mode():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
            )

        alt_text = processor.batch_decode(
            output_ids[:, inputs["input_ids"].shape[1] :],
            skip_special_tokens=True,
        )[0].strip()

        print(f"[AltText] ✓ Generated {len(alt_text)} chars")

        # Check for long description keywords
        keywords = [
            "longer description",
            "detailed description",
            "diagram",
            "chart",
            "graph",
            "map",
            "table",
            "data visualization",
        ]
        requires_long_desc = any(kw in alt_text.lower() for kw in keywords)

        return {
            "alt_text": alt_text,
            "requires_long_desc": requires_long_desc,
            "confidence": 0.85,
            "success": True,
        }

    except Exception as e:
        import traceback
        error = f"{type(e).__name__}: {e}"
        print(f"[AltText] ✗ ERROR: {error}")
        print(traceback.format_exc())
        return {
            "alt_text": "",
            "requires_long_desc": False,
            "confidence": 0.0,
            "success": False,
            "error": str(e),
        }


@app.local_entrypoint()
def main(image_path: str):
    """Test endpoint — reads local image and generates alt text."""
    print(f"[Local] Loading image from {image_path}...")
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    print("[Local] Calling generate_alt_text via Modal...")
    result = generate_alt_text.remote(image_b64, context="Document image")

    print(f"\n{'='*70}")
    print("ALT TEXT GENERATION RESULT:")
    print(f"{'='*70}")
    print(json.dumps(result, indent=2))
    print(f"{'='*70}\n")
