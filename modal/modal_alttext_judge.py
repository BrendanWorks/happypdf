"""
Alt-text quality judge — allenai/Molmo-7B-D-0924 (4-bit NF4) as an
INDEPENDENT second opinion on the Qwen2-VL alt text this pipeline generates.

PointCheck Phase 2 (see docs/POINTCHECK_INTEGRATION.md). The generator
(Qwen2-VL) never grades itself: a different vision model looks at each image
plus the proposed alt text and returns a 1-5 adequacy score, a one-line
critique, and an independent opinion on whether the image needs a long
description (charts/graphs/diagrams). Results are REPORT-ONLY — they land in
the job record's alt_text_review block and never change the generated HTML.

The model wrapper is ported from PointCheck's MolmoQAAnalyzer
(backend/app/models/molmo2.py, same author) INCLUDING its Transformers 5.x
compat patches. Do not remove the patches — removal breaks inference silently
(repetition loops) or loudly (AttributeError/TypeError). Weights are baked
into the image at build time (no runtime HuggingFace dependency), matching
modal/modal_olmocr_v2.py's discipline.

Deploy:      modal deploy modal/modal_alttext_judge.py     (app "alttext-judge")
Smoke test:  modal run modal/modal_alttext_judge.py --image-path img.png --alt-text "a chart"
"""

import base64
import re

import modal

MODEL_NAME = "allenai/Molmo-7B-D-0924"
APP_NAME = "alttext-judge"

# Pinned to the version this app was smoke-tested against (July 16 2026).
# The generation path is version-independent (manual decode loop — see
# _MolmoJudge.query), but the LOAD path still relies on the compat patches
# below, so don't let the version float. If you bump this, re-run the
# calibration smoke test in docs/POINTCHECK_INTEGRATION.md Phase 2 first.
TRANSFORMERS_PIN = "transformers==5.14.1"


def _download_weights():
    from huggingface_hub import snapshot_download

    snapshot_download(MODEL_NAME)
    print(f"[build] {MODEL_NAME} weights baked into image")


image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch>=2.9.0",
        "torchvision",
        TRANSFORMERS_PIN,
        "accelerate",
        "bitsandbytes",
        "Pillow",
        "einops",
        "numpy",
        "huggingface_hub",
        "tensorflow-cpu",  # required by Molmo-7B-D-0924 processor remote code
    )
    .env({"HF_HOME": "/models"})
    .run_function(_download_weights)
)

app = modal.App(APP_NAME)

# Container-level model cache — persists across .remote() calls while the
# container stays warm (scaledown_window below).
_judge = None


# ---------------------------------------------------------------------------
# Response parsing (pure Python — unit-tested locally without a GPU)
# ---------------------------------------------------------------------------

def parse_judge_response(text: str) -> dict:
    """Parse Molmo's free-text response into {score, critique, long_desc_opinion}.

    The prompt asks for SCORE:/CRITIQUE:/LONG_DESC: lines, but a 7B model
    doesn't always comply — fall back to looser patterns, and to None when a
    field genuinely isn't recoverable (callers treat None as 'unavailable',
    never as a bad score).
    """
    text = (text or "").strip()

    score = None
    m = re.search(r"SCORE\s*[:=]?\s*([1-5])\b", text, re.I)
    if not m:
        m = re.search(r"\b([1-5])\s*(?:/|out of)\s*5\b", text, re.I)
    if m:
        score = int(m.group(1))

    critique = ""
    m = re.search(r"CRITIQUE\s*[:=]?\s*(.+?)(?:\n\s*LONG_DESC|\n\s*SCORE|$)", text, re.I | re.S)
    if m:
        critique = m.group(1).strip()
    elif text:
        # No labeled critique — keep the raw response as the critique so the
        # reviewer's reasoning isn't lost.
        critique = text
    critique = re.sub(r"\s+", " ", critique)[:300]

    long_desc = None
    m = re.search(r"LONG_DESC\s*[:=]?\s*(yes|no|true|false)\b", text, re.I)
    if m:
        long_desc = m.group(1).lower() in ("yes", "true")

    return {"score": score, "critique": critique, "long_desc_opinion": long_desc}


def build_judge_prompt(alt_text: str, context: str = "") -> str:
    ctx = f"\nText near the image in the document: {context[:150]}" if context else ""
    return (
        "You are an accessibility reviewer. The image is from a PDF converted to HTML. "
        f'This alt text was written for it: "{alt_text[:400]}"{ctx}\n\n'
        "Judge whether the alt text accurately and sufficiently describes the image "
        "for a screen reader user. Answer in exactly this format:\n"
        "SCORE: <1-5>\n"
        "CRITIQUE: <one sentence>\n"
        "LONG_DESC: <yes or no>\n\n"
        "Scoring: 5 = accurate and sufficient; 3 = partially accurate or missing key "
        "content; 1 = wrong, vacuous, or just a filename. LONG_DESC is yes only if the "
        "image is a chart, graph, diagram, map, or data visualization whose information "
        "cannot fit in short alt text."
    )


# ---------------------------------------------------------------------------
# Model wrapper — ported from PointCheck MolmoQAAnalyzer with all compat patches
# ---------------------------------------------------------------------------

class _MolmoJudge:
    """allenai/Molmo-7B-D-0924 in 4-bit NF4 (~4 GB VRAM on A10G)."""

    def __init__(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor, BitsAndBytesConfig

        print(f"[judge] Loading {MODEL_NAME} (4-bit NF4)...")

        # ── Compat patches for Molmo-7B-D-0924 on Transformers 5.x ─────────
        # (ported verbatim in behavior from PointCheck molmo2.py — see that
        # file for the full forensic notes on each patch)
        import inspect as _inspect
        import sys as _sys

        import transformers as _tf

        # Patch 1: all_tied_weights_keys must exist and act dict-like.
        if not hasattr(_tf.PreTrainedModel, "all_tied_weights_keys"):
            _tf.PreTrainedModel.all_tied_weights_keys = property(lambda self: {})

        self.processor = AutoProcessor.from_pretrained(
            MODEL_NAME, trust_remote_code=True, padding_side="left"
        )

        # Patch 2: Molmo's tie_weights(self) takes no kwargs; 5.x passes some.
        # The modeling module only exists in sys.modules after from_pretrained
        # starts, so: attempt → catch TypeError → patch → retry.
        def _patch_tie_weights():
            n = 0
            for mod in list(_sys.modules.values()):
                if mod is None or "molmo" not in (getattr(mod, "__name__", "") or "").lower():
                    continue
                for attr in list(vars(mod).keys()):
                    cls = getattr(mod, attr, None)
                    if not isinstance(cls, type):
                        continue
                    own = cls.__dict__.get("tie_weights")
                    if own is None:
                        continue
                    try:
                        sig = _inspect.signature(own)
                        if "missing_keys" not in sig.parameters and "**" not in str(sig):
                            def _mk(o):
                                def _safe(self, **kw):
                                    return o(self)
                                return _safe
                            cls.tie_weights = _mk(own)
                            n += 1
                            print(f"[judge] tie_weights patch applied to {cls.__name__}")
                    except Exception:
                        pass
            return n

        model_kwargs = {
            "trust_remote_code": True,
            "quantization_config": BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            ),
            "device_map": {"": 0},
        }
        try:
            self.model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, **model_kwargs)
        except TypeError as te:
            if "tie_weights" not in str(te) or "missing_keys" not in str(te):
                raise
            import gc

            gc.collect()
            torch.cuda.empty_cache()
            n = _patch_tie_weights()
            print(f"[judge] Patched {n} class(es); retrying from_pretrained...")
            self.model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, **model_kwargs)

        self.model.eval()
        print("[judge] Ready")

    def query(self, pil_image, prompt: str, max_new_tokens: int = 120) -> str:
        """Greedy decode via a manual loop over Molmo's own forward().

        We deliberately do NOT use transformers' generate(): Molmo-7B-D's
        remote code predates DynamicCache and expects legacy tuple caches
        (its forward does `past_key_values[0][0].size(-2)`), while modern
        transformers pre-injects a DynamicCache during prefill — crashing
        with "'list' object has no attribute 'size'". This loop mirrors the
        model's own prepare_inputs_for_generation/_update_model_kwargs logic
        for use_position_ids (full-length attention mask built once,
        position_ids incremented per step, images only on prefill), keeping
        the cache as the legacy tuples the model itself produces. That makes
        it independent of the transformers generation internals entirely.
        """
        import time

        import torch
        from PIL import Image

        t0 = time.perf_counter()
        img = pil_image
        # Cap width — each 448x448 crop costs ~729 tokens.
        if img.width > 896:
            scale = 896 / img.width
            img = img.resize((896, max(1, int(img.height * scale))), Image.LANCZOS)

        raw = self.processor.process(images=[img], text=prompt)
        inputs = {
            k: (v.unsqueeze(0).to("cuda") if isinstance(v, torch.Tensor) else v)
            for k, v in raw.items()
        }
        input_ids = inputs["input_ids"]
        batch, input_len = input_ids.shape
        eos_id = self.processor.tokenizer.eos_token_id

        generated: list[int] = []
        with torch.inference_mode():
            # Prefill — matches generate_from_batch's setup for use_position_ids:
            # mask covers prompt + all future tokens; images only on this call.
            attn = input_ids != -1
            position_ids = torch.clamp(torch.cumsum(attn.to(torch.int32), dim=-1) - 1, min=0)
            append_last = attn.long().sum(dim=-1) - 1
            attn_full = torch.cat([attn, attn.new_ones((batch, max_new_tokens))], dim=1)

            out = self.model(
                input_ids=input_ids,
                attention_mask=attn_full,
                position_ids=position_ids,
                images=inputs.get("images"),
                image_masks=inputs.get("image_masks"),
                image_input_idx=inputs.get("image_input_idx"),
                append_last_valid_logits=append_last,
                use_cache=True,
                last_logits_only=True,
            )
            pos = position_ids[:, -1:]

            for step in range(max_new_tokens):
                next_tok = out.logits[:, -1, :].argmax(dim=-1)  # greedy (do_sample=False)
                tok_id = int(next_tok[0])
                if eos_id is not None and tok_id == eos_id:
                    break
                generated.append(tok_id)
                if step == max_new_tokens - 1:
                    break
                pos = pos + 1
                out = self.model(
                    input_ids=next_tok.view(batch, 1),
                    attention_mask=attn_full,
                    position_ids=pos,
                    past_key_values=out.past_key_values,  # legacy tuples end-to-end
                    use_cache=True,
                    last_logits_only=True,
                )

        text = self.processor.tokenizer.decode(generated, skip_special_tokens=True).strip()
        print(f"[judge] {input_len} in / {len(generated)} out tokens, "
              f"{round((time.perf_counter() - t0) * 1000)} ms")
        return text


# ---------------------------------------------------------------------------
# Modal function
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    gpu="A10G",
    timeout=900,
    memory=16384,
    max_containers=1,       # cost ceiling — judging is never latency-critical
    scaledown_window=300,   # reuse the warm model across back-to-back jobs
)
def judge_alt_text(items: list[dict]) -> list[dict]:
    """
    Judge a batch of generated alt texts against their images.

    items:   [{"filename": str, "image_b64": str, "alt_text": str, "context": str}]
    returns: [{"filename", "score": 1-5 | None, "critique": str,
               "long_desc_opinion": bool | None, "success": bool}]

    One batch call per document so N images never cause N cold starts
    (mirrors the reasoning behind ALTTEXT_CONCURRENCY in build_syllabus_slice).
    A single bad image must not sink the batch — per-item try/except.
    """
    from io import BytesIO

    from PIL import Image

    global _judge
    if _judge is None:
        _judge = _MolmoJudge()

    results = []
    for item in items:
        fname = item.get("filename", "?")
        try:
            img = Image.open(BytesIO(base64.b64decode(item["image_b64"]))).convert("RGB")
            prompt = build_judge_prompt(item.get("alt_text", ""), item.get("context", ""))
            raw = _judge.query(img, prompt)
            parsed = parse_judge_response(raw)
            results.append({"filename": fname, "success": parsed["score"] is not None, **parsed})
            print(f"[judge] {fname}: score={parsed['score']} "
                  f"long_desc={parsed['long_desc_opinion']} \"{parsed['critique'][:60]}\"")
        except Exception as e:
            import traceback

            print(f"[judge] {fname} failed (non-fatal): {type(e).__name__}: {e}\n"
                  f"{traceback.format_exc()}")
            results.append(
                {"filename": fname, "success": False, "score": None,
                 "critique": "", "long_desc_opinion": None}
            )
    return results


def parse_fidelity_response(text: str) -> dict:
    """Parse the page-inventory answer into counts/flags (never fabricates).

    Expected format: IMAGES: n / TABLES: n / CHART: yes|no / TEXT: yes|no.
    Missing or unparseable fields come back None — callers must skip Nones
    rather than treat them as zero (a None count is 'unknown', not 'empty').
    """
    text = (text or "").strip()

    def _count(label: str):
        m = re.search(rf"{label}\s*[:=]?\s*(\d+)", text, re.I)
        if m:
            return min(int(m.group(1)), 50)  # cap absurd model output
        # spelled-out zero/none
        m = re.search(rf"{label}\s*[:=]?\s*(no|none|zero)\b", text, re.I)
        return 0 if m else None

    def _flag(label: str):
        m = re.search(rf"{label}\s*[:=]?\s*(yes|no|true|false)\b", text, re.I)
        if not m:
            return None
        return m.group(1).lower() in ("yes", "true")

    return {
        "images": _count("IMAGES"),
        "tables": _count("TABLES"),
        "has_chart": _flag("CHART"),
        "text_heavy": _flag("TEXT"),
    }


_FIDELITY_PROMPT = (
    "Look at this page from a PDF document. Answer in exactly this format:\n"
    "IMAGES: <number of photographs, figures, charts, logos, or illustrations "
    "visible on the page>\n"
    "TABLES: <number of data tables with visible rows and columns>\n"
    "CHART: <yes or no — is any of the images a chart, graph, or data visualization>\n"
    "TEXT: <yes or no — does the page contain more than a few sentences of readable text>"
)


@app.function(
    image=image,
    gpu="A10G",
    timeout=900,
    memory=16384,
    max_containers=1,       # cost ceiling — the gate is never latency-critical
    scaledown_window=300,
)
def judge_page_fidelity(pages: list[dict]) -> list[dict]:
    """
    Content-inventory each rendered PDF page (PointCheck Phase 3, PDF side).

    pages:   [{"page_number": int, "image_b64": str}]
    returns: [{"page_number", "images", "tables", "has_chart", "text_heavy",
               "success": bool}]  (counts/flags may be None = unknown)

    The HTML side of the fidelity comparison is computed structurally from the
    DOM (src/fidelity_gate.py) — only the unstructured PDF needs vision.
    Batch call per document; per-page failures never sink the batch.
    """
    from io import BytesIO

    from PIL import Image

    global _judge
    if _judge is None:
        _judge = _MolmoJudge()

    results = []
    for p in pages:
        n = p.get("page_number", 0)
        try:
            img = Image.open(BytesIO(base64.b64decode(p["image_b64"]))).convert("RGB")
            raw = _judge.query(img, _FIDELITY_PROMPT, max_new_tokens=60)
            parsed = parse_fidelity_response(raw)
            ok = any(v is not None for v in parsed.values())
            results.append({"page_number": n, "success": ok, **parsed})
            print(f"[fidelity] page {n}: {parsed}")
        except Exception as e:
            import traceback

            print(f"[fidelity] page {n} failed (non-fatal): {type(e).__name__}: {e}\n"
                  f"{traceback.format_exc()}")
            results.append(
                {"page_number": n, "success": False, "images": None,
                 "tables": None, "has_chart": None, "text_heavy": None}
            )
    return results


@app.local_entrypoint()
def smoke(image_path: str, alt_text: str = "an image", context: str = ""):
    """Smoke test one image: modal run modal/modal_alttext_judge.py --image-path x.png --alt-text '...'"""
    b64 = base64.b64encode(open(image_path, "rb").read()).decode()
    out = judge_alt_text.remote(
        [{"filename": image_path, "image_b64": b64, "alt_text": alt_text, "context": context}]
    )
    print(out)
