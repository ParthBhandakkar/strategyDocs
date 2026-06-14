import time
import os
import sys
import json
from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "video_docs", "batches")
BATCH_SIZE = 5

ALL_URLS = [
    "https://www.youtube.com/watch?v=yvcqeXnghDc",
    "https://www.youtube.com/watch?v=eap7vH0zOQ8",
    "https://www.youtube.com/watch?v=FAiYE-2zESk",
    "https://www.youtube.com/watch?v=LsC2IokcYpc",
    "https://www.youtube.com/watch?v=hIn61C0nRqY",
    "https://www.youtube.com/watch?v=YGKTvqJIx1w",
    "https://www.youtube.com/watch?v=FT3CoupoWAE",
    "https://www.youtube.com/watch?v=dcmKOcMMT8Y",
    "https://www.youtube.com/watch?v=eMpWLS4mSiY",
    "https://www.youtube.com/watch?v=HyJuZNo_ikM",
    "https://www.youtube.com/watch?v=wmcoNjbUxyI",
    "https://www.youtube.com/watch?v=2cuaTYjEw9Q",
    "https://www.youtube.com/watch?v=UG9lY_LF_mw",
    "https://www.youtube.com/watch?v=gc_CIx_sgU8",
    "https://www.youtube.com/watch?v=2cOo0oEPUPE",
    "https://www.youtube.com/watch?v=VkoUIMsgDZ0",
    "https://www.youtube.com/watch?v=f7UXeZ1AZtA",
    "https://www.youtube.com/watch?v=W6Cd0yiOTtc",
    "https://www.youtube.com/watch?v=1Y19QjyLt6M",
    "https://www.youtube.com/watch?v=ehV08YNaNAc",
    "https://www.youtube.com/watch?v=lN7oMZ_S8xI",
    "https://www.youtube.com/watch?v=nV9gknhy2Ew",
    "https://www.youtube.com/watch?v=a5nZhjyCCJo",
    "https://www.youtube.com/watch?v=CLDEIsNpVRc",
    "https://www.youtube.com/watch?v=7rpncfx75HY",
    "https://www.youtube.com/watch?v=LO5xTXRYN8Y",
    "https://www.youtube.com/watch?v=exkANBItgUc",
    "https://www.youtube.com/watch?v=KBGaDKKtUMo",
    "https://www.youtube.com/watch?v=6HMG-NO2h_A",
    "https://www.youtube.com/watch?v=wpvzFFN3pDo",
    "https://www.youtube.com/watch?v=kz2rw7VWpMM",
    "https://www.youtube.com/watch?v=PGK_wp_H_8U",
    "https://www.youtube.com/watch?v=Yinhff6uLyw",
    "https://www.youtube.com/watch?v=Ocu8vSvOGCU",
    "https://www.youtube.com/watch?v=dyGl-XkMUwQ",
    "https://www.youtube.com/watch?v=fAkQOcbChV4",
    "https://www.youtube.com/watch?v=osc_hFXmQZA",
    "https://www.youtube.com/watch?v=ugsA3FHiF0I",
    "https://www.youtube.com/watch?v=bUKt8df141U",
    "https://www.youtube.com/watch?v=CD041rzY67Y",
    "https://www.youtube.com/watch?v=YKbkZ4eRd04",
    "https://www.youtube.com/watch?v=Mk5DKZo9_-Q",
    "https://www.youtube.com/watch?v=jsDSBDJIF2Q",
    "https://www.youtube.com/watch?v=d9nUO0hdnT8",
    "https://www.youtube.com/watch?v=Jga2mj8kSJA",
    "https://www.youtube.com/watch?v=dcNU_Dwgy5E",
    "https://www.youtube.com/watch?v=3e2xQo-dsOI",
    "https://www.youtube.com/watch?v=MJRwsCzmB1s",
    "https://www.youtube.com/watch?v=G5nhJEC59k4",
    "https://www.youtube.com/watch?v=7_9bekMCNZA",
    "https://www.youtube.com/watch?v=6xbLspSa86A",
    "https://www.youtube.com/watch?v=vT_xPTnsZ5s",
    "https://www.youtube.com/watch?v=VOs4Dztopyo",
    "https://www.youtube.com/watch?v=LivWGyobZcA",
    "https://www.youtube.com/watch?v=SF4_BAEz9jg",
    "https://www.youtube.com/watch?v=Ei0MtKztZtA",
    "https://www.youtube.com/watch?v=rk3Lz5oS8pE",
    "https://www.youtube.com/watch?v=Ai0-TGDHoZo",
    "https://www.youtube.com/watch?v=KP9RnSnr4kg",
    "https://www.youtube.com/watch?v=Leh2moBQUpk",
    "https://www.youtube.com/watch?v=RZgRjnqVnzk",
    "https://www.youtube.com/watch?v=k76AXYhcr1U",
    "https://www.youtube.com/watch?v=6moA5TnQ2Ss",
    "https://www.youtube.com/watch?v=Rf2Q46dQcSk",
    "https://www.youtube.com/watch?v=s0jk8ENNkjw",
    "https://www.youtube.com/watch?v=-UcPjKlzaO0",
    "https://www.youtube.com/watch?v=s9lsHH1WwKg",
    "https://www.youtube.com/watch?v=l_hlLfj2UFs",
    "https://www.youtube.com/watch?v=06DxvYmOXP4",
    "https://www.youtube.com/watch?v=IJm1HLHNxY8",
    "https://www.youtube.com/watch?v=jqY4uL1a-oQ",
    "https://www.youtube.com/watch?v=EpmNNATDxyg",
    "https://www.youtube.com/watch?v=LPmmymPRpno",
    "https://www.youtube.com/watch?v=fr2dDjvWNW0",
    "https://www.youtube.com/watch?v=zqRQ3b0a0Sc",
    "https://www.youtube.com/watch?v=HT49YvYH9NQ",
    "https://www.youtube.com/watch?v=Zqw2tDMGqqA",
    "https://www.youtube.com/watch?v=-bEF1vca1Xc",
    "https://www.youtube.com/watch?v=HqmhaQrVxMM",
    "https://www.youtube.com/watch?v=08Tv4nOccCg",
    "https://www.youtube.com/watch?v=yPA1XioVF18",
    "https://www.youtube.com/watch?v=F4tcFpgYBdQ",
    "https://www.youtube.com/watch?v=FtDqcK4TUME",
    "https://www.youtube.com/watch?v=g7MxWxQ99_4",
    "https://www.youtube.com/watch?v=ksLTkMjm7-Y",
    "https://www.youtube.com/watch?v=RwscctjAhaw",
    "https://www.youtube.com/watch?v=9hXQV9_yfOI",
    "https://www.youtube.com/watch?v=9NF26IyivVY",
    "https://www.youtube.com/watch?v=IXW4lpfiknQ",
    "https://www.youtube.com/watch?v=epRYvYzROlA",
]

# The batches that failed: 10, 13, 15, 17
# Note: Batch numbers are 1-indexed. Batch 10 corresponds to index 9 in a 0-indexed batch list.
# Batch 10: Videos 46 to 50 -> Indices 45 to 49
# Batch 13: Videos 61 to 65 -> Indices 60 to 64
# Batch 15: Videos 71 to 75 -> Indices 70 to 74
# Batch 17: Videos 81 to 85 -> Indices 80 to 84

failed_batches = [
    (10, ALL_URLS[45:50]),
    (13, ALL_URLS[60:65]),
    (15, ALL_URLS[70:75]),
    (17, ALL_URLS[80:85])
]

PROMPT_TEMPLATE = """Watch each of these YouTube videos carefully and create a SEPARATE, INDEPENDENT, detailed document for each video.

IMPORTANT: DO NOT generate a Google Doc, Workspace document, or any external link. You MUST output ALL the text directly here in this chat response!

IMPORTANT FORMAT REQUIREMENTS - Each document must follow this exact structure:

---
# Strategy/Topic Name
**Source:** Faiz SMC ("[Video Title]")
**Video URL:** [URL]

## Overview
Brief summary of what this video covers.

## Step-by-Step Breakdown (Chronological)

### Step 1: [Step Title]
Detailed explanation of what to do in this step.
- Specific conditions, settings, timeframes
- Key levels to watch

**Example:** Describe a real trade example shown in the video with specific price levels, times, and outcomes.

### Step 2: [Step Title]
...continue for all steps...

## Key Rules & Conditions
- Rule 1
- Rule 2
- etc.

## Trade Examples From The Video
### Example 1:
- Asset/Pair:
- Date/Session:
- Entry:
- Stop Loss:
- Take Profit:
- Outcome:
- Screenshot description of the chart setup

## Risk Management
Any risk management rules mentioned.

## Summary / Key Takeaways
- Takeaway 1
- Takeaway 2
---

HERE ARE THE VIDEO LINKS:
{links}

CRITICAL INSTRUCTIONS:
1. OUTPUT TEXT DIRECTLY HERE. DO NOT USE GOOGLE DOCS.
2. Each video MUST be documented SEPARATELY and INDEPENDENTLY
3. Include ALL trade examples shown in each video with specific price levels
4. Follow the EXACT chronological order of the video content
5. Include specific timeframes, indicators, and settings mentioned
6. Do NOT skip any content - document EVERYTHING in the video
"""

def wait_for_gemini_response(page, timeout_seconds=600):
    print("  Waiting for generation to start...")
    time.sleep(8)
    start = time.time()
    check_interval = 5
    last_text_len = 0
    stable_count = 0
    while time.time() - start < timeout_seconds:
        time.sleep(check_interval)
        elapsed = int(time.time() - start)
        stop_buttons = page.locator('button[aria-label*="top"], button[aria-label*="ancel"], button[mattooltip*="top"]')
        try:
            if stop_buttons.count() > 0 and stop_buttons.first.is_visible():
                print(f"  Still generating... ({elapsed}s elapsed)")
                stable_count = 0
                continue
        except Exception:
            pass
        try:
            responses = page.locator('message-content, .message-content, model-response, .model-response-text')
            if responses.count() > 0:
                current_text = responses.last.inner_text()
                current_len = len(current_text)
                if current_len > 0 and current_len == last_text_len:
                    stable_count += 1
                    if stable_count >= 3:
                        print(f"  Response appears complete ({elapsed}s elapsed, {current_len} chars)")
                        return True
                else:
                    stable_count = 0
                last_text_len = current_len
                print(f"  Generating... ({elapsed}s, {current_len} chars so far)")
        except Exception:
            pass
    print(f"  WARNING: Timed out after {timeout_seconds}s")
    return False

def extract_response(page):
    selectors = [
        'message-content',
        '.message-content',
        'model-response',
        '.model-response-text',
        'div[class*="response"]',
        '.markdown-main-panel',
    ]
    for sel in selectors:
        try:
            elements = page.locator(sel)
            if elements.count() > 0:
                text = elements.last.inner_text()
                if len(text) > 100:
                    return text
        except Exception:
            continue
    return None

def start_new_chat(page):
    new_chat_selectors = [
        'button[aria-label*="ew chat"]',
        'a[aria-label*="ew chat"]',
        'button:has-text("New chat")',
        'a:has-text("New chat")',
    ]
    for sel in new_chat_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                time.sleep(3)
                print("  Started new chat.")
                return True
        except Exception:
            continue
    print("  Could not find new chat button, navigating to gemini.google.com...")
    page.goto("https://gemini.google.com/app")
    time.sleep(5)
    return True

def send_prompt(page, prompt_text):
    input_selectors = [
        'div.ql-editor[contenteditable="true"]',
        'rich-textarea div[contenteditable="true"]',
        'div[contenteditable="true"][aria-label*="rompt"]',
        'div[contenteditable="true"]',
        'textarea',
    ]
    chat_box = None
    for sel in input_selectors:
        try:
            el = page.locator(sel).locator('visible=true').first
            if el.is_visible(timeout=3000):
                chat_box = el
                break
        except Exception:
            continue
    if not chat_box:
        raise Exception("Could not find Gemini input box!")
    chat_box.click()
    time.sleep(0.5)
    page.evaluate(f"""
        navigator.clipboard.writeText({json.dumps(prompt_text)}).then(() => {{
            document.execCommand('paste');
        }});
    """)
    time.sleep(1)
    try:
        chat_box.fill(prompt_text)
    except Exception:
        chat_box.press_sequentially(prompt_text[:50])
    time.sleep(1)
    send_selectors = [
        'button[aria-label*="end"]',
        'button[aria-label*="ubmit"]',
        'button[mattooltip*="end"]',
    ]
    sent = False
    for sel in send_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible() and btn.is_enabled():
                btn.click()
                sent = True
                break
        except Exception:
            continue
    if not sent:
        chat_box.press("Enter")
    time.sleep(2)

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            print("Connected to Chrome!")
        except Exception as e:
            print(f"ERROR connecting to Chrome: {e}")
            print("Make sure Chrome is running with --remote-debugging-port=9222")
            sys.exit(1)

        page = None
        for pg in context.pages:
            if "gemini.google" in pg.url:
                page = pg
                break
        if not page:
            page = context.new_page()
            page.goto("https://gemini.google.com/app")
            time.sleep(5)

        for batch_num, chunk in failed_batches:
            print(f"\n{'='*60}")
            print(f"RETRYING BATCH {batch_num} (Videos {batch_num * 5 - 4} to {batch_num * 5})")
            print(f"{'='*60}")
            
            start_new_chat(page)
            time.sleep(3)

            links_text = "\n".join([f"{i+1}. {url}" for i, url in enumerate(chunk)])
            prompt = PROMPT_TEMPLATE.format(links=links_text)

            try:
                print("  Sending prompt to Gemini...")
                send_prompt(page, prompt)

                print("  Waiting for Gemini to generate response...")
                wait_for_gemini_response(page, timeout_seconds=600)

                response_text = extract_response(page)

                if response_text and len(response_text) > 200:
                    start_idx = batch_num * 5 - 4
                    end_idx = batch_num * 5
                    batch_file = os.path.join(OUTPUT_DIR, f"batch_{batch_num:02d}_videos_{start_idx}_to_{end_idx}.md")
                    with open(batch_file, 'w', encoding='utf-8') as f:
                        f.write(f"# Batch {batch_num} - Videos {start_idx} to {end_idx} (RETRY)\n\n")
                        f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        f.write(response_text)
                    print(f"  ✅ Saved: {batch_file}")
                else:
                    print(f"  ⚠️ Response too short or empty for batch {batch_num}")

                delay = 10
                print(f"  Waiting {delay}s before next batch...")
                time.sleep(delay)

            except Exception as e:
                print(f"\n  ❌ ERROR in batch {batch_num}: {e}")

        print(f"\n{'='*60}")
        print("ALL RETRY BATCHES COMPLETE!")
        print(f"{'='*60}")
        browser.close()

if __name__ == "__main__":
    main()
