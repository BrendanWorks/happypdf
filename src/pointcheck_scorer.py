"""
PointCheck Layer-1 accessibility checks — ported from PointCheck
(https://github.com/BrendanWorks/PointCheck, same author; see
docs/POINTCHECK_INTEGRATION.md for the design doc and phasing).

Three pure-JS checks that run in the headless Chromium already used for axe
scoring. No GPU, no network, no AI — each is a single page.evaluate(). They
catch classes of issues axe-core's ruleset misses:

  STRUCTURE_JS        filename-pattern alt text ("img_042.png"), meaningful
                      images with empty alt, vague link text, heading-level
                      skips, deprecated moving content, unnamed ARIA roles.
  KEYBOARD_STATIC_JS  javascript: links, click handlers on non-interactive
                      elements, hover-only handlers, scrollable regions that
                      keyboards can't reach, positive tabindex.
  CONTRAST_JS         WCAG contrast ratios computed against the EFFECTIVE
                      rendered background (alpha-compositing the ancestor
                      stack) — axe can false-pass when the visible color
                      comes from stacked semi-transparent layers.

The JS blocks are verbatim copies from PointCheck v1 (backend/app/wcag_checks/
page_structure.py, keyboard_nav.py, color_blindness.py). Do not edit them
here — upstream fixes should be re-copied so the two repos stay diffable.

Findings are REPORT-ONLY: they are surfaced in a sibling "pointcheck" block
and never feed axe's score/violations keys, the regression guard, or the
convergence gate (the remediation loop has no patch strategies for these
finding types yet — see the design doc's "Integration point" section).

Web-page findings that are structural noise on a converted single-flow
document (skip links, <nav> landmarks, 24px touch targets on inline text
links) are pruned in Python — the JS stays a verbatim copy.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# JS blocks — verbatim from PointCheck v1 (all-rights-reserved by the same
# author as this project; reproduced here with permission by construction).
# ---------------------------------------------------------------------------

# From PointCheck backend/app/wcag_checks/page_structure.py
STRUCTURE_JS = """
() => {
    const issues = [];

    const lang = document.documentElement.getAttribute('lang') || '';
    if (!lang.trim()) {
        issues.push({criterion:'3.1.1',severity:'serious',
            description:'Missing lang attribute on <html>. Screen readers cannot determine page language.',
            fix:'Add lang="en" (or appropriate code) to the <html> tag.'});
    }

    const title = (document.title||'').trim();
    if (!title) {
        issues.push({criterion:'2.4.2',severity:'serious',
            description:'Page has no <title> element.',
            fix:'Add a descriptive <title> to the <head>.'});
    } else if (title.length<5 || /^(untitled|page|home|index)$/i.test(title)) {
        issues.push({criterion:'2.4.2',severity:'moderate',
            description:`Page title "${title}" is not descriptive.`,
            fix:'Use a title that describes the page content.'});
    }

    const images = Array.from(document.querySelectorAll('img'));
    const missingAlt = images.filter(img => !img.hasAttribute('alt'));
    const emptyAltOnMeaningful = images.filter(img => {
        if(!img.hasAttribute('alt')||img.getAttribute('alt')!=='') return false;
        const r=img.getBoundingClientRect();
        const role=img.getAttribute('role')||'';
        const isDecorative=role==='presentation'||role==='none'||
                           img.getAttribute('aria-hidden')==='true'||r.width<10||r.height<10;
        const isLinked=!!img.closest('a');
        const isLarge=r.width>100&&r.height>100;
        return !isDecorative&&(isLinked||isLarge);
    });
    const filenameAlt = images.filter(img => {
        const alt=img.getAttribute('alt')||'';
        return /\\.(png|jpg|jpeg|gif|svg|webp)$/i.test(alt)||/^img_?\\d+/i.test(alt);
    });
    if(missingAlt.length>0){
        issues.push({criterion:'1.1.1',severity:'critical',
            description:`${missingAlt.length} image(s) missing alt attribute entirely.`,
            examples:missingAlt.slice(0,3).map(img=>(img.getAttribute('src')||'').split('/').pop().slice(0,40)),
            fix:'Add alt="" for decorative images, or descriptive alt text for meaningful images.'});
    }
    if(emptyAltOnMeaningful.length>0){
        issues.push({criterion:'1.1.1',severity:'serious',
            description:`${emptyAltOnMeaningful.length} large/linked image(s) have empty alt text but appear meaningful.`,
            examples:emptyAltOnMeaningful.slice(0,3).map(img=>(img.getAttribute('src')||'').split('/').pop().slice(0,40)),
            fix:'Provide descriptive alt text for images that convey information.'});
    }
    if(filenameAlt.length>0){
        issues.push({criterion:'1.1.1',severity:'moderate',
            description:`${filenameAlt.length} image(s) have filename-style alt text.`,
            examples:filenameAlt.slice(0,2).map(img=>img.getAttribute('alt')),
            fix:'Replace filename alt text with a description of what the image shows.'});
    }

    const headings=Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
        .filter(h=>{const r=h.getBoundingClientRect();return r.width>0||r.height>0;});
    const h1s=headings.filter(h=>h.tagName==='H1');
    if(h1s.length===0&&document.body){
        issues.push({criterion:'1.3.1',severity:'serious',
            description:'No <h1> found. Every page should have a single main heading.',
            fix:'Add one <h1> that describes the main topic of the page.'});
    } else if(h1s.length>1){
        issues.push({criterion:'1.3.1',severity:'moderate',
            description:`${h1s.length} <h1> elements found. Pages should have exactly one.`,
            examples:h1s.slice(0,3).map(h=>(h.innerText||'').trim().slice(0,50)),
            fix:'Use one <h1> per page.'});
    }
    const skips=[]; let prevLevel=0;
    for(const h of headings){
        const level=parseInt(h.tagName[1]);
        if(prevLevel>0&&level>prevLevel+1)
            skips.push(`<h${prevLevel}> → <h${level}> "${(h.innerText||'').trim().slice(0,40)}"`);
        prevLevel=level;
    }
    if(skips.length>0){
        issues.push({criterion:'1.3.1',severity:'moderate',
            description:`Heading levels skipped ${skips.length} time(s).`,
            examples:skips.slice(0,3),
            fix:'Do not skip heading levels. Use h1→h2→h3 in order.'});
    }

    const mainLandmarks=Array.from(document.querySelectorAll('main,[role="main"]'))
        .filter(el=>{const r=el.getBoundingClientRect();return r.width>0||r.height>0;});
    if(mainLandmarks.length===0){
        issues.push({criterion:'1.3.1',severity:'serious',
            description:'No <main> landmark found.',
            fix:'Wrap the primary page content in a <main> element.'});
    } else if(mainLandmarks.length>1){
        issues.push({criterion:'1.3.1',severity:'serious',
            description:`${mainLandmarks.length} <main> landmarks found. A page should have exactly one.`,
            fix:'Consolidate page content into a single <main> element.'});
    }
    const navLandmarks=Array.from(document.querySelectorAll('nav,[role="navigation"]'));
    const totalLinks=document.querySelectorAll('a[href]').length;
    if(navLandmarks.length===0&&totalLinks>=5){
        issues.push({criterion:'1.3.1',severity:'minor',
            description:`No <nav> landmark found, but the page has ${totalLinks} links.`,
            fix:'Wrap groups of navigation links in <nav> elements.'});
    }

    const idCounts={};
    Array.from(document.querySelectorAll('[id]')).forEach(el=>{
        const id=el.id.trim();
        if(id)idCounts[id]=(idCounts[id]||0)+1;
    });
    const dupIds=Object.entries(idCounts).filter(([,c])=>c>1).map(([id])=>id);
    if(dupIds.length>0){
        issues.push({criterion:'4.1.1',severity:'serious',
            description:`${dupIds.length} duplicate ID value(s) found. Breaks ARIA associations.`,
            examples:dupIds.slice(0,5),
            fix:'Every id attribute must be unique within the page.'});
    }

    const blinkEls=Array.from(document.querySelectorAll('blink'));
    const marqueeEls=Array.from(document.querySelectorAll('marquee'));
    if(blinkEls.length>0||marqueeEls.length>0){
        const parts=[];
        if(blinkEls.length>0)parts.push(`${blinkEls.length} <blink> element(s)`);
        if(marqueeEls.length>0)parts.push(`${marqueeEls.length} <marquee> element(s)`);
        issues.push({criterion:'2.2.2',severity:'serious',
            description:`${parts.join(' and ')} found — deprecated moving content users cannot pause.`,
            examples:[...blinkEls.slice(0,2).map(el=>`<blink> "${(el.innerText||'').trim().slice(0,40)}"`),...marqueeEls.slice(0,2).map(el=>`<marquee> "${(el.innerText||'').trim().slice(0,40)}"`)].slice(0,3),
            fix:'Remove <blink> and <marquee>. Use CSS with prefers-reduced-motion if animation is needed.'});
    }

    const VAGUE=/^(click here|here|read more|more|learn more|details|link|this|continue|go|view|see more|info|information|download|click|tap)$/i;
    const vagueLinks=Array.from(document.querySelectorAll('a[href]')).filter(a=>{
        const text=(a.innerText||a.getAttribute('aria-label')||'').trim();
        const title=a.getAttribute('title')||'';
        const ariaLabel=a.getAttribute('aria-label')||'';
        if(ariaLabel.trim().length>10||title.trim().length>10)return false;
        return VAGUE.test(text)&&text.length<15;
    });
    if(vagueLinks.length>0){
        issues.push({criterion:'2.4.4',severity:'serious',
            description:`${vagueLinks.length} link(s) have vague text that doesn't describe the destination.`,
            examples:[...new Set(vagueLinks.map(a=>(a.innerText||'').trim()))].slice(0,5),
            fix:'Use descriptive link text, or add aria-label="Read more about [topic]".'});
    }

    const MIN_TARGET_PX=24;
    const smallTargets=Array.from(document.querySelectorAll(
        'a[href],button,input:not([type="hidden"]),select,textarea,[role="button"],[role="link"]'
    )).filter(el=>{
        const tab=el.getAttribute('tabindex');
        if(tab!==null&&parseInt(tab)<0)return false;
        const r=el.getBoundingClientRect();
        return r.width>0&&r.height>0&&(r.width<MIN_TARGET_PX||r.height<MIN_TARGET_PX);
    }).map(el=>{
        const r=el.getBoundingClientRect();
        const label=(el.innerText||el.getAttribute('aria-label')||el.getAttribute('value')||el.getAttribute('placeholder')||'').trim().slice(0,40);
        return `<${el.tagName.toLowerCase()}>${label?' "'+label+'"':''} (${Math.round(r.width)}×${Math.round(r.height)}px)`;
    }).slice(0,5);
    if(smallTargets.length>0){
        issues.push({criterion:'2.5.8',severity:'minor',
            description:`${smallTargets.length} interactive element(s) have touch targets smaller than 24×24px (WCAG 2.2 AA).`,
            examples:smallTargets,
            fix:'Ensure all interactive elements have a minimum 24×24px clickable area.'});
    }

    const ariaIssues=[];
    const roleNeedsName=['button','link','checkbox','radio','textbox','combobox','listbox','option','menuitem','tab','treeitem'];
    const unnamedRoles=Array.from(document.querySelectorAll('[role]')).filter(el=>{
        const role=el.getAttribute('role');
        if(!roleNeedsName.includes(role))return false;
        const name=el.getAttribute('aria-label')||el.getAttribute('aria-labelledby')||(el.innerText||'').trim();
        return !name;
    });
    if(unnamedRoles.length>0)ariaIssues.push(`${unnamedRoles.length} element(s) with interactive role but no accessible name`);
    const hiddenFocusable=Array.from(document.querySelectorAll(
        '[aria-hidden="true"] a,[aria-hidden="true"] button,[aria-hidden="true"] input,[aria-hidden="true"] [tabindex]'
    )).filter(el=>{const tab=el.getAttribute('tabindex');return tab===null||parseInt(tab)>=0;});
    if(hiddenFocusable.length>0)ariaIssues.push(`${hiddenFocusable.length} focusable element(s) inside aria-hidden="true"`);
    if(ariaIssues.length>0){
        issues.push({criterion:'4.1.2',severity:'serious',
            description:ariaIssues.join('; '),
            fix:'Ensure all interactive elements have accessible names. Do not place focusable elements inside aria-hidden.'});
    }

    const untitledFrames=Array.from(document.querySelectorAll('iframe,frame')).filter(f=>{
        return !((f.getAttribute('title')||'').trim()||(f.getAttribute('aria-label')||'').trim()||f.getAttribute('aria-labelledby'));
    });
    if(untitledFrames.length>0){
        issues.push({criterion:'4.1.2',severity:'serious',
            description:`${untitledFrames.length} iframe(s) have no title attribute.`,
            examples:untitledFrames.slice(0,3).map(f=>(f.getAttribute('src')||'<iframe>').split('/').pop().slice(0,50)),
            fix:'Add a descriptive title attribute to every <iframe>.'});
    }

    return issues;
}
"""

# From PointCheck backend/app/wcag_checks/keyboard_nav.py
KEYBOARD_STATIC_JS = """
() => {
    const issues = [];

    const jsLinks = Array.from(document.querySelectorAll('a[href]')).filter(a =>
        a.getAttribute('href').trim().toLowerCase().startsWith('javascript:')
    );
    if (jsLinks.length > 0) {
        issues.push({
            criterion: '2.1.1', severity: 'serious',
            description: `${jsLinks.length} link(s) use javascript: href — unreliable for keyboard/AT users.`,
            examples: jsLinks.slice(0,3).map(a => (a.innerText||a.href).trim().slice(0,120)),
        });
    }

    const mouseOnlyEls = Array.from(document.querySelectorAll('div,span,td,li')).filter(el => {
        const hasClick = el.onclick || el.getAttribute('onclick');
        const role = el.getAttribute('role') || '';
        const tab  = el.getAttribute('tabindex');
        const interactive = ['button','link','menuitem','option','tab','checkbox','radio'].includes(role);
        return hasClick && !interactive && tab === null;
    });
    if (mouseOnlyEls.length > 0) {
        issues.push({
            criterion: '2.1.1', severity: 'serious',
            description: `${mouseOnlyEls.length} element(s) have click handlers but are not keyboard-reachable.`,
            examples: mouseOnlyEls.slice(0,3).map(el => (el.innerText||el.tagName).trim().slice(0,120)),
        });
    }

    const hoverOnly = Array.from(document.querySelectorAll('[onmouseover]')).filter(el =>
        !el.getAttribute('onfocus') && !el.getAttribute('onmouseenter')
    );
    if (hoverOnly.length > 0) {
        issues.push({
            criterion: '2.1.1', severity: 'moderate',
            description: `${hoverOnly.length} element(s) use onmouseover without an onfocus equivalent.`,
            examples: hoverOnly.slice(0,3).map(el => (el.innerText||el.tagName).trim().slice(0,120)),
        });
    }

    const skipLinks = Array.from(document.querySelectorAll('a')).filter(a => {
        const text = (a.innerText||'').toLowerCase();
        const href = a.getAttribute('href') || '';
        return (text.includes('skip') || text.includes('jump')) && href.startsWith('#');
    });
    if (skipLinks.length === 0) {
        issues.push({
            criterion: '2.4.1', severity: 'minor',
            description: 'No skip navigation link found. Users must Tab through all repeated navigation on every page.',
            examples: [],
        });
    }

    const NATIVE_FOCUSABLE = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA']);
    const scrollableNotFocusable = Array.from(document.querySelectorAll('*')).filter(el => {
        if (el === document.body || el === document.documentElement) return false;
        const s = window.getComputedStyle(el);
        if (!/auto|scroll/.test(s.overflow+' '+s.overflowX+' '+s.overflowY)) return false;
        const hasOverflow = el.scrollHeight > el.clientHeight+2 || el.scrollWidth > el.clientWidth+2;
        if (!hasOverflow) return false;
        const tab = el.getAttribute('tabindex');
        return !NATIVE_FOCUSABLE.has(el.tagName) && (tab===null || parseInt(tab)<0);
    });
    if (scrollableNotFocusable.length > 0) {
        issues.push({
            criterion: '2.1.1', severity: 'serious',
            description: `${scrollableNotFocusable.length} scrollable region(s) are not keyboard accessible.`,
            examples: scrollableNotFocusable.slice(0,3).map(el => {
                const label = (el.getAttribute('aria-label')||el.id||el.className||'').trim().slice(0,40);
                return `<${el.tagName.toLowerCase()}>${label?' "'+label+'"':''} (scroll: ${Math.round(el.scrollHeight)}px / visible: ${Math.round(el.clientHeight)}px)`;
            }),
        });
    }

    const posTabEls = Array.from(document.querySelectorAll('[tabindex]')).filter(el =>
        parseInt(el.getAttribute('tabindex')) > 0
    );
    if (posTabEls.length > 0) {
        issues.push({
            criterion: '2.4.3', severity: 'serious',
            description: `${posTabEls.length} element(s) use positive tabindex values, disrupting natural tab order.`,
            examples: posTabEls.slice(0,3).map(el => {
                const tag   = el.tagName.toLowerCase();
                const label = (el.innerText||el.getAttribute('aria-label')||'').trim().slice(0,40);
                return `<${tag} tabindex="${el.getAttribute('tabindex')}">${label?' "'+label+'"':''}`;
            }),
        });
    }

    return issues;
}
"""

# From PointCheck backend/app/wcag_checks/color_blindness.py
CONTRAST_JS = """
() => {
    function luminance(r,g,b){
        return [r,g,b].reduce((s,v,i)=>{
            v/=255;
            const lin=v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);
            return s+lin*[0.2126,0.7152,0.0722][i];
        },0);
    }
    function parseRGB(c){
        const m=c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/);
        if(!m)return null;
        return{rgb:[+m[1],+m[2],+m[3]],alpha:m[4]!==undefined?parseFloat(m[4]):1};
    }
    function contrast(fg,bg){
        const l1=luminance(...fg),l2=luminance(...bg);
        return(Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);
    }
    function getEffectiveBg(el){
        let node=el,r=255,g=255,b=255;
        const stack=[];
        while(node&&node.tagName!=='HTML'){
            const p=parseRGB(window.getComputedStyle(node).backgroundColor);
            if(p&&p.alpha>0.01)stack.push(p);
            node=node.parentElement;
        }
        for(let i=stack.length-1;i>=0;i--){
            const{rgb,alpha}=stack[i];
            r=Math.round(rgb[0]*alpha+r*(1-alpha));
            g=Math.round(rgb[1]*alpha+g*(1-alpha));
            b=Math.round(rgb[2]*alpha+b*(1-alpha));
        }
        return[r,g,b];
    }
    const els=Array.from(document.querySelectorAll(
        'p,h1,h2,h3,h4,h5,h6,a,button,label,li,td,th,span,div'
    )).filter(el=>{
        const r=el.getBoundingClientRect();
        const text=(el.innerText||'').trim();
        return r.width>0&&r.height>0&&text.length>1&&text.length<200;
    }).slice(0,60);
    const failures=[],seen=new Set();
    for(const el of els){
        const s=window.getComputedStyle(el);
        const fgParsed=parseRGB(s.color);
        if(!fgParsed)continue;
        const fg=fgParsed.rgb,bg=getEffectiveBg(el);
        const ratio=contrast(fg,bg);
        const size=parseFloat(s.fontSize),weight=parseInt(s.fontWeight)||400;
        const large=size>=24||(size>=18.67&&weight>=700);
        const threshold=large?3.0:4.5;
        const text=(el.innerText||'').trim().slice(0,60);
        const key=text+fg.join(',')+bg.join(',');
        if(seen.has(key))continue;
        seen.add(key);
        const entry={tag:el.tagName,text,ratio:Math.round(ratio*100)/100,
                     threshold,passes:ratio>=threshold,
                     fg:'rgb('+fg+')',bg:'rgb('+bg+')'};
        if(!entry.passes)failures.push(entry);
    }
    return{failures:failures.slice(0,8),checked:seen.size};
}
"""

# ---------------------------------------------------------------------------
# Document-shape pruning
# ---------------------------------------------------------------------------
# These findings are correct for live websites but structural noise on a
# converted single-flow document (no page chrome, no repeated navigation):
#   2.4.1  "No skip navigation link"   — nothing to skip past in a document
#   1.3.1  "No <nav> landmark ..."     — documents legitimately have many
#                                        links without site navigation
#   2.5.8  small touch targets         — the ported JS lacks WCAG 2.5.8's
#                                        inline-text exception, so ordinary
#                                        links inside sentences fire it
_PRUNED_CRITERIA = {"2.4.1", "2.5.8"}


def _is_document_noise(issue: dict) -> bool:
    if issue.get("criterion") in _PRUNED_CRITERIA:
        return True
    if issue.get("criterion") == "1.3.1" and issue.get("description", "").startswith(
        "No <nav> landmark"
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_SEVERITIES = ("critical", "serious", "moderate", "minor")


def score_page(page) -> dict:
    """Run the three Layer-1 checks on an already-loaded sync Playwright Page.

    Returns a report-only block:
      {"findings": [{check, criterion, severity, description, examples, fix}],
       "counts": {critical, serious, moderate, minor},
       "contrast_elements_checked": int,
       "pruned_as_document_noise": int}
    """
    findings: list[dict] = []
    pruned = 0

    for check, js in (("page_structure", STRUCTURE_JS), ("keyboard_nav", KEYBOARD_STATIC_JS)):
        for issue in page.evaluate(js):
            if _is_document_noise(issue):
                pruned += 1
                continue
            findings.append(
                {
                    "check": check,
                    "criterion": issue.get("criterion", ""),
                    "severity": issue.get("severity", "moderate"),
                    "description": issue.get("description", ""),
                    "examples": issue.get("examples", []),
                    "fix": issue.get("fix", ""),
                }
            )

    contrast = page.evaluate(CONTRAST_JS)
    if contrast.get("failures"):
        findings.append(
            {
                "check": "contrast",
                "criterion": "1.4.3",
                "severity": "serious",
                "description": (
                    f"{len(contrast['failures'])} text element(s) fail WCAG contrast against "
                    "their effective rendered background (alpha-composited)."
                ),
                "examples": [
                    f"<{f['tag'].lower()}> \"{f['text']}\" ratio {f['ratio']} "
                    f"(needs {f['threshold']}, {f['fg']} on {f['bg']})"
                    for f in contrast["failures"][:5]
                ],
                "fix": "Increase the contrast between the text color and its rendered background.",
            }
        )

    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in _SEVERITIES}
    return {
        "findings": findings,
        "counts": counts,
        "contrast_elements_checked": contrast.get("checked", 0),
        "pruned_as_document_noise": pruned,
    }


def pointcheck_score(html_str: str) -> dict:
    """One-shot: load HTML into a fresh headless Chromium and run score_page().

    Mirrors loop.axe_score()'s file:// + sync-Playwright pattern. Launching
    Chromium costs ~1s; this runs twice per job (baseline + final), which is
    negligible next to the 2-6 min pipeline. Callers should treat this as
    best-effort and catch exceptions — findings are report-only and must
    never fail a conversion.
    """
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html_str)
        tmp = Path(f.name)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f"file://{tmp}")
                return score_page(page)
            finally:
                browser.close()
    finally:
        tmp.unlink(missing_ok=True)
