"""
OLMo-2-1124-7B-Instruct WCAG Peer Reviewer — Modal Deployment

Deploys OLMo-2-1124-7B-Instruct for accessibility review of HTML content.
Returns structured JSON with identified WCAG violations.

Model: allenai/OLMo-2-1124-7B-Instruct (7B params, instruction-tuned)
GPU: A10G (24 GB VRAM)
Chat template: <|endoftext|><|user|>\n...\n<|assistant|>\n...<|endoftext|>

Inference time: ~3-5s per HTML chunk
"""

import modal
import base64
import json
from io import BytesIO
from typing import Optional
from pydantic import BaseModel

app = modal.App("olmo-wcag-reviewer")

# Base image with dependencies
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch",
        "torchvision",
        "transformers>=4.48.0",
        "accelerate",
        "Pillow",
        "fastapi",
        "uvicorn[standard]",
        "pydantic>=2.0",
        "python-multipart",
    )
)


class OLMoWCAGReviewer:
    """OLMo-2-1124-7B-Instruct for WCAG accessibility review."""

    def __init__(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print("[OLMoReviewer] Loading OLMo-2-1124-7B-Instruct...")

        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Load tokenizer and model
        self.tokenizer = AutoTokenizer.from_pretrained(
            "allenai/OLMo-2-1124-7B-Instruct",
            trust_remote_code=True,
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            "allenai/OLMo-2-1124-7B-Instruct",
            trust_remote_code=True,
            torch_dtype=torch.bfloat16 if self.device == "cuda" else torch.float32,
            device_map="auto" if self.device == "cuda" else self.device,
        )

        self.model.eval()
        print(f"[OLMoReviewer] Model loaded on {self.device}")

    def review_html(
        self,
        html_chunk: str,
        system_prompt: str,
        max_tokens: int = 1024
    ) -> str:
        """
        Review HTML chunk for WCAG violations.

        Args:
            html_chunk: HTML content to review
            system_prompt: System prompt for WCAG review task
            max_tokens: Max output tokens

        Returns:
            Raw model output (should be JSON)
        """
        import torch

        # Build conversation using OLMo chat template
        messages = [
            {
                "role": "user",
                "content": f"{system_prompt}\n\nHTML to review:\n{html_chunk}"
            }
        ]

        # Apply chat template
        formatted_prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        print(f"[OLMoReviewer] Generating review (max_tokens={max_tokens})...")
        print(f"[OLMoReviewer] Prompt length: {len(formatted_prompt)} chars")

        # Tokenize
        inputs = self.tokenizer(formatted_prompt, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        input_length = inputs["input_ids"].shape[1]

        # Generate
        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=0.3,
                top_p=0.95,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        # Extract generated text only (not prompt)
        generated_ids = output_ids[0, input_length:]
        generated_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)

        print(f"[OLMoReviewer] Generated {len(generated_text)} chars")

        return generated_text


# Global model instance
_model_instance = None


def get_model():
    global _model_instance
    if _model_instance is None:
        _model_instance = OLMoWCAGReviewer()
    return _model_instance


@app.function(
    image=image,
    gpu="A10G",
    timeout=600,
    env={"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
)
@modal.asgi_app()
def api():
    """FastAPI app for WCAG review."""
    from fastapi import FastAPI, HTTPException

    app = FastAPI(title="OLMo WCAG Reviewer")

    class ReviewRequest(BaseModel):
        html_chunk: str
        system_prompt: str
        max_tokens: int = 1024

    class ReviewResponse(BaseModel):
        raw_output: str
        success: bool
        error: Optional[str] = None

    @app.post("/review", response_model=ReviewResponse)
    async def review(req: ReviewRequest):
        """Review HTML for WCAG violations."""
        try:
            model = get_model()
            output = model.review_html(
                req.html_chunk,
                req.system_prompt,
                req.max_tokens
            )
            return ReviewResponse(raw_output=output, success=True)
        except Exception as e:
            return ReviewResponse(
                raw_output="",
                success=False,
                error=str(e)
            )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    import sys

    # Local testing
    reviewer = OLMoWCAGReviewer()

    if len(sys.argv) > 1:
        html_file = sys.argv[1]
        with open(html_file) as f:
            html_chunk = f.read()
    else:
        html_chunk = "<h1>Test</h1><p>This is a test paragraph</p>"

    system_prompt = (
        "You are a WCAG 2.2 accessibility expert. Review the HTML and identify "
        "accessibility violations. Return JSON: {violations: [{issue_id, wcag_criterion, "
        "element_id, issue, impact, confidence, suggested_fix, fix_type, requires_human_review}]}"
    )

    result = reviewer.review_html(html_chunk, system_prompt)
    print("\n" + "=" * 80)
    print("RAW OLMo OUTPUT:")
    print("=" * 80)
    print(result)
    print("=" * 80)
