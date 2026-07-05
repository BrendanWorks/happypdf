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
        import re
        import traceback

        print(f"[OLMoReviewer] === REVIEW START ===")
        print(f"[OLMoReviewer] HTML chunk length: {len(html_chunk)} chars")
        print(f"[OLMoReviewer] System prompt length: {len(system_prompt)} chars")

        # Build conversation with system role if OLMo supports it, else prepend
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": f"HTML to review:\n{html_chunk}"
            }
        ]

        # Apply chat template
        try:
            formatted_prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            print(f"[OLMoReviewer] Used system role path")
        except Exception as e:
            # Fallback: if system role fails, use original approach
            print(f"[OLMoReviewer] System role failed ({type(e).__name__}), using fallback")
            formatted_prompt = self.tokenizer.apply_chat_template(
                [{"role": "user", "content": f"{system_prompt}\n\nHTML to review:\n{html_chunk}"}],
                tokenize=False,
                add_generation_prompt=True
            )

        print(f"[OLMoReviewer] Formatted prompt length: {len(formatted_prompt)} chars (~{len(formatted_prompt)//4} tokens)")

        # Tokenize - explicitly handle device mapping
        try:
            inputs = self.tokenizer(formatted_prompt, return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            input_length = inputs["input_ids"].shape[1]
            print(f"[OLMoReviewer] Tokenized to {input_length} tokens")
        except Exception as e:
            print(f"[OLMoReviewer] TOKENIZATION ERROR: {type(e).__name__}: {str(e)}")
            print(traceback.format_exc())
            raise

        # Generate - use cleaner parameters (greedy decoding ignores temperature)
        print(f"[OLMoReviewer] Starting generation (max_new_tokens={max_tokens})...")
        try:
            with torch.no_grad():
                output_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    attention_mask=inputs.get("attention_mask"),
                    max_new_tokens=max_tokens,
                    do_sample=False,  # Greedy decoding
                    temperature=0.0,  # Explicit deterministic
                    pad_token_id=self.tokenizer.eos_token_id if self.tokenizer.eos_token_id is not None else 1,
                )
            print(f"[OLMoReviewer] Generation complete, output shape: {output_ids.shape}")
        except Exception as e:
            print(f"[OLMoReviewer] GENERATION ERROR: {type(e).__name__}: {str(e)}")
            print(f"[OLMoReviewer] Full traceback:")
            print(traceback.format_exc())
            raise

        # Extract generated text only (not prompt)
        try:
            generated_ids = output_ids[0, input_length:]
            generated_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
            print(f"[OLMoReviewer] Decoded {len(generated_text)} chars")
        except Exception as e:
            print(f"[OLMoReviewer] DECODE ERROR: {type(e).__name__}: {str(e)}")
            print(traceback.format_exc())
            raise

        # Post-process: if output doesn't start with JSON, try to extract it
        if generated_text and not generated_text.startswith(("{", "[")):
            print(f"[OLMoReviewer] Output doesn't start with JSON, attempting extraction...")
            print(f"[OLMoReviewer] First 100 chars: {generated_text[:100]}")
            json_match = re.search(r'\{.*\}|\[.*\]', generated_text, re.DOTALL)
            if json_match:
                generated_text = json_match.group(0)
                print(f"[OLMoReviewer] Extracted JSON ({len(generated_text)} chars)")
            else:
                print(f"[OLMoReviewer] No JSON found in output")

        print(f"[OLMoReviewer] === REVIEW COMPLETE ===")
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
            import traceback
            error_msg = str(e)
            tb = traceback.format_exc()
            print(f"\n[OLMo Endpoint] EXCEPTION CAUGHT")
            print(f"[OLMo Endpoint] Type: {type(e).__name__}")
            print(f"[OLMo Endpoint] Message: {error_msg}")
            print(f"[OLMo Endpoint] Traceback:\n{tb}\n")
            return ReviewResponse(
                raw_output="",
                success=False,
                error=f"{type(e).__name__}: {error_msg[:200]}"
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
