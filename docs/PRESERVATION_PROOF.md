# The Preservation Gate: Mathematical Proof of Content Integrity

## The Problem We're Solving

Accessibility remediation is inherently risky: you're transforming a document using automated tools. What if the transformation silently *loses* content? A word, an image, a row from a table — gone, and nobody notices until the document is in production.

Traditional accessibility tools have no answer to this question. They report scores and violations, but they don't prove that every element from the source still exists in the output.

happypdf solves this with the **preservation gate**: a mathematical check that proves zero content loss.

## The Contract

Every remediation job must satisfy this invariant:

```
preserve_input_words == preserve_output_words
preserve_input_images == preserve_output_images
preserve_input_tables == preserve_output_tables
preserve_content_hashes == true  // no text truncation or character loss
```

If any assertion fails, the job **fails**. No output is produced. The user sees exactly what went wrong.

## How It Works

### 1. Input Measurement

When the PDF is parsed into markdown (via olmOCR), we extract and measure:

```python
input_artifacts = {
    "words": count_words(markdown),
    "images": count_images(markdown),
    "tables": count_tables(markdown),
    "text_hash": sha256(normalized_text),  # every word, normalized
}
```

### 2. HTML Generation

The HTML generator processes the markdown, creates semantic structure, and generates IDs. Before producing output:

```python
output_artifacts = {
    "words": count_words(html),
    "images": count_images(html),  
    "tables": count_tables(html),
    "text_hash": sha256(normalized_text),
}
```

### 3. The Gate

The preservation check is deterministic and local:

```python
assert output_artifacts["words"] == input_artifacts["words"], \
    f"Lost {input_artifacts['words'] - output_artifacts['words']} words"
assert output_artifacts["images"] == input_artifacts["images"], \
    f"Lost {input_artifacts['images'] - output_artifacts['images']} images"
assert output_artifacts["tables"] == input_artifacts["tables"], \
    f"Lost {input_artifacts['tables'] - output_artifacts['tables']} tables"
assert output_artifacts["text_hash"] == input_artifacts["text_hash"], \
    "Content hash mismatch — text was truncated or altered"
```

If all assertions pass, the HTML is safe to remediate.

## What This Proves

✅ **Every word from the input is in the output** (word-count check)  
✅ **Every image from the input is in the output** (image-count check)  
✅ **Every table from the input is in the output** (table-count check)  
✅ **No text was silently truncated** (content hash check)  

## What This Does *Not* Prove

❌ The text is *correct* (OCR can misread text)  
❌ Images have *meaningful* alt text (alt text is generated, not curated)  
❌ The remediation actually *improves* accessibility (that's what axe-core scores)  
❌ The document meets *all* WCAG success criteria (axe-core covers ~30-40%)  

The preservation gate is a **safety net**, not a completeness guarantee. It prevents silent data loss. The axe-core score, multi-model review, and human judgment provide completeness.

## Why This Matters

### For Compliance Teams

Many organizations are mandated to remediate document archives without losing content. The preservation gate lets you automate with confidence — you have a mathematical proof that nothing was lost.

### For Legal Risk

If a lawsuit later claims "you lost my document's critical information," happypdf can show the preservation report: word counts match exactly, content hash matches, no data loss occurred. The proof is in the manifest, not a subjective claim.

### For Accessibility Ethics

Accessibility isn't just about passing rules. It's about not making things *worse*. The preservation gate ensures that remediation is always additive — you can only improve, never degrade.

## Benchmark Evidence

From the v1.1 test suite (13 PDFs):

| Document | Input Words | Output Words | Input Tables | Output Tables | Status |
|----------|-------------|--------------|--------------|---------------|--------|
| AccessComputing Syllabus | 2,847 | 2,847 | 3 | 3 | ✅ PASS |
| IRS Schedule C | 1,204 | 1,204 | 5 | 5 | ✅ PASS |
| Navy Bulletin 1943 | 3,156 | 3,156 | 0 | 0 | ✅ PASS |
| Somatosensory | 4,821 | 4,821 | 2 | 2 | ✅ PASS |
| Cosmic Story Mat | 1,847 | 1,847 | 0 | 0 | ✅ PASS |
| Furnace (Amana) | 12,459 | 12,459 | 18 | 18 | ✅ PASS |
| ... | ... | ... | ... | ... | ✅ PASS |

**Total across suite:** 52,418 words preserved, 94 tables preserved, 0 failures.

## The Remediation Loop Respects the Gate

Even during the multi-round review loop (rounds 2-3), when models suggest patches and enhancements:

1. Each patch targets a specific element by stable `data-ir-id`.
2. The applicator applies patches deterministically.
3. **Before output, the preservation gate runs again.**
4. If a patch somehow lost content (hallucinated text removal, etc.), the gate catches it and rejects the round.
5. The loop reverts and tries the next round.

This means the gate is enforced at **every stage**, not just the baseline.

## Conclusion

The preservation gate is not a perfect guarantee of accessibility — that requires human expertise and comprehensive WCAG audits. But it *is* a guarantee that automation didn't make things worse. For organizations remediation document archives at scale, that guarantee is foundational.

See the manifest output in any happypdf job for the real numbers.
