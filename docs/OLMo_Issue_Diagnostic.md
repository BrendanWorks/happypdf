# OLMo Reviewer JSON Output Issue - Technical Diagnostic

## Project Context: HappyPDF v1.1

### What is HappyPDF?
HappyPDF is a **WCAG 2.2 accessibility auditor** that converts inaccessible PDFs into accessible semantic HTML. It's a portfolio project demonstrating multi-model AI orchestration, running on **Modal A100-40GB GPU infrastructure**.

**Goal:** Take a PDF document and automatically:
1. Extract text and images using OCR
2. Generate alt text for images
3. Create semantic HTML structure
4. Identify accessibility violations
5. Synthesize multi-model AI reviews into actionable patches
6. Output a fully accessible HTML document

**Live Demo:** https://pointcheck.org

---

### The Pipeline: How It Works

The HappyPDF pipeline is a **multi-round, multi-model orchestration** system:

```
User uploads PDF
    ↓
[Stage 1] olmOCR extraction (Qwen2-VL on A10G)
    → Extracts text, detects images, OCR
    ↓
[Stage 2] Alt text generation (Qwen2-VL on A10G)
    → Generates alt text for images
    ↓
[Stage 3] Semantic HTML generation (Claude)
    → Creates well-formed HTML structure
    ↓
[Stage 4] axe-core baseline scan
    → Measures baseline accessibility violations
    ↓
[Rounds 1-3] Peer Review Loop
    → THREE PARALLEL PEER REVIEWERS (each round):
        • OLMo-2-1124-7B-Instruct (Allen AI, Modal A10G)
        • Gemini-2.5-Flash (Google)
        • GPT-4o-mini (OpenAI)
    → Each reviewer analyzes HTML for WCAG issues
    → Each returns structured JSON: {"violations": [{"issue_id", "element_id", "suggested_fix", ...}]}
    → Claude Judge synthesizes reviews into patches
    → Patches applied if they pass quality gates
    ↓
[Final] Output accessibility report + fixed HTML
```

### Why Multi-Model Peer Review?
- **Diversity:** Different models catch different issues (OLMo excels at reasoning, GPT at practical fixes, Gemini at compliance rules)
- **Resilience:** If one reviewer fails, others continue (redundancy)
- **Credibility:** Demonstrates working AI orchestration for portfolio
- **Convergence:** System stops when reviews converge (3 rounds max)

---

### The Role of OLMo
OLMo is the **open-source peer reviewer** in this system:

| Reviewer | Model | Provider | Cost | Speed | Specialty |
|----------|-------|----------|------|-------|-----------|
| **OLMo** | OLMo-2-1124-7B-Instruct | Allen AI / Modal | $0.10/hour (A10G) | ~90s per review | Reasoning, explanations |
| Gemini | Gemini-2.5-Flash | Google | $0.075/M input tokens | ~5s per review | Rule-based compliance |
| GPT | GPT-4o-mini | OpenAI | $0.15/M input tokens | ~10s per review | Practical fixes |

**Why OLMo matters:**
1. **Cost-effective:** Runs on Modal, scales automatically
2. **Open-source:** Can be self-hosted or optimized
3. **Portfolio value:** Shows multi-cloud, multi-model orchestration
4. **Demonstrates reasoning:** 7B parameters can explain accessibility fixes

---

## Current Status: The Issue

### Overview
The OLMo-2-1124-7B-Instruct peer reviewer is **failing to produce usable output** in the HappyPDF v1.1 live pipeline, even after fixes to improve JSON formatting. While Gemini and GPT reviewers work correctly, OLMo fails with RuntimeError on both initial attempt and retry.

**Project:** HappyPDF v1.1 (WCAG 2.2 accessibility auditor)  
**Date:** July 3-4, 2026  
**Status:** OLMo peer reviewer failing; system remains functional via Gemini/GPT fallback (converges in 1 round instead of 3)  
**Impact:** Reduces model diversity and portfolio value; limits cost-effectiveness demonstration

---

## Problem Statement

### Symptoms
1. **End-to-end test failure:** PDF uploaded to live pipeline → OLMo fails with `RuntimeError`
2. **Failure occurs twice:** Initial attempt (155.0s), retry after 2s (89.8s)
3. **Error message abbreviated:** Logs show only `RuntimeError` without details (intentional truncation in reviewers.py line 231-233)
4. **Gemini/GPT succeed:** Other peer reviewers work fine, confirming the issue is OLMo-specific
5. **Direct API test partial success:** Simple HTML test returns valid JSON `{"violations": []}`, but real document processing fails

### Where It Fails
- **Endpoint:** `/review` POST on deployed Modal app at `https://brendanworks--olmo-wcag-reviewer-api.modal.run`
- **Called from:** `happypdf/src/reviewers.py::_call_olmo()` (async wrapper around sync httpx client)
- **Error logged at:** `happypdf/src/reviewers.py::_run_one()` line 239, caught as RuntimeError

---

## Root Cause Hypothesis

### What I've Fixed So Far (Commit ffca7ec)
**Problem:** OLMo was concatenating system prompt with user message instead of using a proper system role.

**Fix Applied:**
```python
# Before (concatenated):
messages = [{
    "role": "user",
    "content": f"{system_prompt}\n\nHTML to review:\n{html_chunk}"
}]

# After (proper system role):
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
```

**Added Fallback:** If chat template doesn't support system role, fall back to original approach.

**Added Extraction:** Regex-based JSON extraction to pull valid JSON from plain-text output:
```python
if generated_text and not generated_text.startswith(("{", "[")):
    json_match = re.search(r'\{.*\}|\[.*\]', generated_text, re.DOTALL)
    if json_match:
        generated_text = json_match.group(0)
```

**Result:** Direct API test with simple HTML succeeds, returns `{"violations": []}` valid JSON. But real document processing still fails.

---

## Current Test Results

### Direct OLMo Endpoint Test (July 3, 10:18 AM)
**Input:**
```python
html_chunk = "<h1>Test</h1><p><img src='test.jpg'/></p><button>Click me</button>"
system_prompt = "You are a WCAG 2.2 accessibility reviewer. Identify issues. Respond with ONLY JSON."
max_tokens = 512
```

**Output:**
```json
{
  "raw_output": "{\"violations\": []}",
  "success": true,
  "error": null
}
```
**Status:** ✓ SUCCESS - Valid JSON returned after ~90 second cold start

---

### End-to-End PDF Processing Test (July 3, 10:00 AM - 10:09 AM)
**Document:** `syllabus_NOTaccessible.pdf` (169 KB)  
**Processing Time:** ~9 minutes total

**Flask Logs Show:**
```
[10:05:17] [reviewers] round 1: calling olmo, gemini, gpt in parallel (17 addressable elements)
[10:07:52] [reviewers] olmo: FAILED in 155.0s (RuntimeError); retrying in 2s
[10:09:24] [reviewers] olmo: FAILED in 89.8s (RuntimeError); skipping
```

**Reviewer Health Result:**
```json
{
  "olmo": {"status": "failed", "round": 1},
  "gemini": {"status": "success", "round": 1},
  "gpt": {"status": "success", "round": 1}
}
```

**Other Results:**
- HTML: ✓ Generated
- Final Score: 100.0% (26 passes, 0 violations)
- Pipeline: ✓ Completed successfully (Gemini + GPT sufficient)

---

## Code Structure

### OLMo Endpoint (`modal/modal_olmo_wcag.py`)

**Relevant Sections:**

**1. Model Initialization (lines 43-65):**
```python
class OLMoWCAGReviewer:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
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
```
**GPU:** A10G (24 GB VRAM)  
**Model:** allenai/OLMo-2-1124-7B-Instruct (instruction-tuned, 7B parameters)

**2. Review Method (lines 67-149, FIXED):**
```python
def review_html(self, html_chunk: str, system_prompt: str, max_tokens: int = 1024) -> str:
    # Now uses proper system role:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"HTML to review:\n{html_chunk}"}
    ]
    
    # Apply chat template
    try:
        formatted_prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        # Fallback if system role not supported
        formatted_prompt = self.tokenizer.apply_chat_template(
            [{"role": "user", "content": f"{system_prompt}\n\nHTML to review:\n{html_chunk}"}],
            tokenize=False, add_generation_prompt=True
        )
    
    # Generate with greedy decoding
    output_ids = self.model.generate(
        **inputs,
        max_new_tokens=max_tokens,
        temperature=0.3,
        top_p=0.95,
        do_sample=False,  # Greedy decoding
        pad_token_id=self.tokenizer.eos_token_id,
    )
    
    # Extract + post-process
    generated_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
    
    # Post-process: extract JSON if not proper format
    generated_text = generated_text.strip()
    if generated_text and not generated_text.startswith(("{", "[")):
        json_match = re.search(r'\{.*\}|\[.*\]', generated_text, re.DOTALL)
        if json_match:
            generated_text = json_match.group(0)
    
    return generated_text
```

**3. FastAPI Endpoint (lines 186-202):**
```python
@app.post("/review", response_model=ReviewResponse)
async def review(req: ReviewRequest):
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
```

---

### Peer Reviewer Caller (`src/reviewers.py`)

**Relevant Sections:**

**1. OLMo Call Function (lines 180-205):**
```python
async def _call_olmo(html: str) -> str:
    import httpx

    def _sync() -> str:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            r = client.post(
                f"{OLMO_URL}/review",
                json={"html_chunk": _clip(html), "system_prompt": REVIEW_INSTRUCTION,
                      "max_tokens": 1024},
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(data.get("error", "OLMo review failed"))
            raw_output = data.get("raw_output", "")
            # Verify it looks like JSON, not plain text prose
            if raw_output and not raw_output.strip().startswith(("{", "[")):
                raise RuntimeError(f"OLMo returned non-JSON text: {raw_output[:100]}")
            return raw_output

    return await asyncio.to_thread(_sync)
```

**2. Single Reviewer Runner (lines 219-240):**
```python
async def _run_one(name: str, fn, html: str, valid_ids: set[str]) -> tuple[str, list[dict] | None]:
    for attempt in range(RETRIES + 1):
        t0 = time.time()
        try:
            raw = await fn(html)
            issues = _normalize(_extract_json(raw), name, valid_ids)
            log(f"{name}: {len(issues)} issue(s) in {time.time() - t0:.1f}s")
            return name, issues
        except Exception as e:
            dt = time.time() - t0
            error_summary = f"{type(e).__name__}"
            if str(e) and len(str(e)) < 100:
                error_summary += f": {str(e)[:80]}"
            if attempt < RETRIES:
                wait = BACKOFF_BASE ** (attempt + 1)
                log(f"{name}: FAILED in {dt:.1f}s ({error_summary}); retrying in {wait:.0f}s")
                await asyncio.sleep(wait)
            else:
                log(f"{name}: FAILED in {dt:.1f}s ({error_summary}); skipping")
                return name, None
```

**Error Truncation:** Line 231-233 truncates error messages to 80 chars to avoid leaking credentials/sensitive data.

**3. JSON Extraction (lines 89-102):**
```python
def _extract_json(text: str) -> dict | list:
    text = (text or "").strip()
    if text.startswith("```"):  # strip markdown code fences
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Salvage the first complete JSON value
        m = re.search(r"[\{\[]", text)
        if m:
            return json.JSONDecoder().raw_decode(text[m.start():])[0]
        raise
```

**WCAG Review Instruction (lines 47-62):**
```python
REVIEW_INSTRUCTION = (
    "You are a WCAG 2.2 accessibility reviewer. You are given an HTML fragment in "
    "which every block-level element has a stable `data-ir-id` attribute. Identify "
    "accessibility issues that can be fixed by adding or correcting ARIA attributes "
    "(aria-label, role, aria-describedby) or alt text. For each issue, cite the exact "
    "`data-ir-id` value of the element it applies to, never invent an id that is not "
    "present in the HTML. Prefer concrete, deterministic fixes and put the literal "
    "attribute and value in suggested_fix, e.g. 'Add aria-label=\"Class schedule\" to "
    "the table.'\n\n"
    "Respond with ONLY a JSON object of the form:\n"
    '{"violations": [{"issue_id": "string", "wcag_criterion": "1.3.1", '
    '"element_id": "block-1-...", "issue": "short description", '
    '"impact": "critical|serious|moderate|minor", "confidence": 0.0-1.0, '
    '"suggested_fix": "concrete fix", "fix_type": "deterministic|llm_safe|needs_human", '
    '"hallucinated": false}]}'
)
```

---

## Key Observations

### What Works
1. ✓ Simple HTML test (4 elements) → OLMo succeeds, returns JSON
2. ✓ Gemini peer reviewer → works reliably (succeeded in test)
3. ✓ GPT peer reviewer → works reliably (succeeded in test)
4. ✓ Error handling → failures are caught and logged without crashing
5. ✓ System resilience → pipeline completes despite OLMo failure

### What Fails
1. ✗ Real document processing → OLMo fails with RuntimeError
2. ✗ Both attempts fail → initial (155s) and retry (89.8s)
3. ✗ No usable error message → RuntimeError without context (truncated by design)

### Possible Differentiators (Simple vs. Complex)
| Aspect | Simple Test | Real Document |
|--------|------------|---------------|
| HTML chunk | 4 elements, ~100 chars | 17 elements, ~20,000 chars |
| Prompt instruction | Short, simple | Full WCAG instruction (500+ chars) |
| Processing time | ~90s cold start | 155s then 89.8s retry |
| Max tokens | 512 | 1024 |
| Result | ✓ Valid JSON | ✗ RuntimeError |

---

## Hypotheses for Root Cause

### Hypothesis 1: HTML Chunk Size / Complexity
**Issue:** OLMo struggles with large HTML chunks or many elements  
**Evidence:**
- Simple HTML (4 elements) succeeds
- Real document (17 elements, 20K chars) fails
- Max chunk size set to 20,000 chars in reviewers.py:43

**Test:** Try with medium-sized chunk, progressively larger

---

### Hypothesis 2: System Prompt Not Being Respected
**Issue:** Chat template doesn't properly inject system role, falls back to concatenation  
**Evidence:**
- System role is new code, fallback still used
- OLMo model might not support system role in its chat template

**Test:** Explicitly check if fallback is being used; log which code path executes

---

### Hypothesis 3: JSON Generation Failure at Inference
**Issue:** OLMo model generates text, but it's not JSON even after extraction attempt  
**Evidence:**
- Simple test: model outputs `{"violations": []}`
- Real doc: model outputs something that:
  - Isn't caught by the initial check (doesn't start with `{` or `[`)
  - Doesn't contain extractable JSON (regex finds nothing)
  - Causes _extract_json() to fail

**Test:** Log the actual raw_output before extraction; check what extraction produces

---

### Hypothesis 4: Model Timeout or Resource Issue
**Issue:** Model runs out of memory or times out during inference on complex content  
**Evidence:**
- Cold start took 155s (unusual, typically 30-90s)
- Retry faster at 89.8s but still fails
- A10G has 24GB, 7B model should fit

**Test:** Monitor GPU memory during inference; check for OOM errors in Modal

---

### Hypothesis 5: Inference Logic Issue
**Issue:** do_sample=False (greedy decoding) with temperature=0.3 might be conflicting  
**Evidence:**
- temperature parameter ignored when do_sample=False
- Could cause unexpected behavior

**Test:** Set temperature=0 when do_sample=False; or use do_sample=True with temperature

---

## Deployment Artifacts

**Deployed Endpoint:** `https://brendanworks--olmo-wcag-reviewer-api.modal.run`  
**File:** `/Users/brendanworks/clean-pdf/happypdf/modal/modal_olmo_wcag.py`  
**Commit:** ffca7ec ("Fix OLMo reviewer JSON output by using system role and extraction")  
**Deployed:** July 3, 2026, 08:36 AM

**Local Flask Backend:** `http://127.0.0.1:8000` (requires dependencies installed)  
**File:** `/Users/brendanworks/clean-pdf/happypdf/api/main.py`  
**Dependencies:** `requirements.txt` includes modal==1.4.3, httpx==0.28.1, transformers support

---

## Questions for Investigation

1. **What is the actual error inside the OLMo endpoint?** The RuntimeError is being caught but not logged with full details. Can we modify modal_olmo_wcag.py to log full exception + raw_output before raising?

2. **Is the system role being used?** Can we add logging to check which code path in the chat template is executing (system role vs. fallback)?

3. **What is OLMo actually generating?** We need to see:
   - The raw model output (before any parsing)
   - Whether it starts with `{` or `[`
   - What the regex extraction produces

4. **Is this a model behavior issue?** Does OLMo-2-1124-7B-Instruct reliably follow JSON instructions in all cases, or is it hit-or-miss with complex prompts?

5. **Would a different model work?** Would Llama, Mistral, or another 7B instruct model be more reliable?

---

## Suggested Next Steps (for other AI tools to evaluate)

### Quick Wins
1. Add detailed logging to modal_olmo_wcag.py to capture:
   - Full error messages (not just exception type)
   - Raw model output before post-processing
   - Which code path in chat template is taken
   - Model config (temperature, do_sample consistency)

2. Test with smaller HTML chunks to isolate size/complexity issue

3. Try do_sample=True with low temperature to allow some variance

### Deeper Investigation
4. Log OLMo model generation directly (before encoding):
   - What tokens is the model producing?
   - Is it entering a failure state partway through?

5. Test with different WCAG instructions:
   - Simpler instruction (fewer constraints)
   - Different instruction formats (bullet points vs. prose)

6. Compare system role handling:
   - Check if OLMo's tokenizer.apply_chat_template properly supports system role
   - Examine the formatted prompt that gets sent to the model

7. Profile resource usage:
   - GPU memory during inference
   - Token generation speed (is it stuck generating forever?)
   - Timeout behavior (is 300s limit being hit?)

### Alternative Approaches
8. Add pre-generation validation:
   - Before calling OLMo, validate HTML chunk size/structure
   - Chunk very large documents into smaller pieces

9. Add post-generation repair:
   - If raw output isn't valid JSON, try to fix it (add closing braces, etc.)
   - Fall back to empty violations list if all else fails

10. Consider model alternatives:
    - Test Qwen2-VL or other models that are known to follow JSON instructions
    - Create a lightweight fallback that doesn't require complex JSON

---

## Files for Reference

**OLMo Endpoint:**
- `/Users/brendanworks/clean-pdf/happypdf/modal/modal_olmo_wcag.py` (fixed code, deployed)

**Peer Reviewer Integration:**
- `/Users/brendanworks/clean-pdf/happypdf/src/reviewers.py` (calls OLMo, handles errors)

**Flask API:**
- `/Users/brendanworks/clean-pdf/happypdf/api/main.py` (job orchestration)

**Loop/Pipeline:**
- `/Users/brendanworks/clean-pdf/happypdf/src/loop.py` (calls live_provider)

**GitHub:**
- https://github.com/BrendanWorks/happypdf
- Latest commit: ffca7ec

---

## Summary for Another AI Tool

**What to focus on:**
- OLMo endpoint is deployed and partially working (simple cases succeed)
- End-to-end real document processing fails with RuntimeError from OLMo reviewer
- Error message is truncated, so we don't know the actual problem
- System role fix was deployed but may not be the root cause
- Gemini/GPT work fine, confirming issue is specific to OLMo

**Key question:** Why does OLMo succeed on simple HTML but fail on real documents, and what RuntimeError is it actually raising?
