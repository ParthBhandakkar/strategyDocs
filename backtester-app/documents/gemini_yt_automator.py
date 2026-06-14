"""
Gemini YouTube Video Documentation Automator
=============================================
Connects to Chrome via CDP, feeds YouTube video URLs to Gemini in batches of 5,
and saves the generated documentation as markdown files.

Usage:
  1. Launch Chrome: /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome_gemini_profile"
  2. Sign into Gemini in the browser
  3. Run: python3 gemini_yt_automator.py
"""

import time
import os
import sys
import json
from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "video_docs")
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "progress.json")
BATCH_SIZE = 5

# All 90 video URLs from @faizsmcfx channel (cleaned of tracking params)
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

PROMPT_TEMPLATE = """Watch each of these YouTube videos carefully and create a SEPARATE, INDEPENDENT, detailed document for each video.

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

### Example 2:
(if more examples shown)

## Risk Management
Any risk management rules mentioned.

## Summary / Key Takeaways
- Takeaway 1
- Takeaway 2
---

HERE ARE THE VIDEO LINKS:
{links}

CRITICAL INSTRUCTIONS:
1. Each video MUST be documented SEPARATELY and INDEPENDENTLY
2. Include ALL trade examples shown in each video with specific price levels
3. Follow the EXACT chronological order of the video content
4. Include specific timeframes, indicators, and settings mentioned
5. Do NOT skip any content - document EVERYTHING in the video
6. Make each document self-contained so someone reading it gets the FULL video content
"""


def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {"completed_batches": [], "last_batch": -1}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def wait_for_gemini_response(page, timeout_seconds=600):
    """Wait for Gemini to finish generating its response."""
    print("  Waiting for generation to start...")
    time.sleep(8)

    # Poll for completion: check if the "stop" button disappears or
    # a new input area becomes active
    start = time.time()
    check_interval = 5
    last_text_len = 0
    stable_count = 0

    while time.time() - start < timeout_seconds:
        time.sleep(check_interval)
        elapsed = int(time.time() - start)

        # Check if there's a stop/cancel button visible (means still generating)
        stop_buttons = page.locator('button[aria-label*="top"], button[aria-label*="ancel"], button[mattooltip*="top"]')
        try:
            if stop_buttons.count() > 0 and stop_buttons.first.is_visible():
                print(f"  Still generating... ({elapsed}s elapsed)")
                stable_count = 0
                continue
        except Exception:
            pass

        # Check response length stability
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
    """Extract the latest Gemini response text."""
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
    """Click 'New chat' button in Gemini to start a fresh conversation."""
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

    # Fallback: navigate directly
    print("  Could not find new chat button, navigating to gemini.google.com...")
    page.goto("https://gemini.google.com/app")
    time.sleep(5)
    return True


def send_prompt(page, prompt_text):
    """Type and send a prompt in Gemini."""
    # Try multiple selectors for the input
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

    # Use clipboard to paste long prompts (more reliable than typing)
    page.evaluate(f"""
        navigator.clipboard.writeText({json.dumps(prompt_text)}).then(() => {{
            document.execCommand('paste');
        }});
    """)
    time.sleep(1)

    # Fallback: fill directly
    try:
        chat_box.fill(prompt_text)
    except Exception:
        # If fill fails, try pressing keys
        chat_box.press_sequentially(prompt_text[:50])

    time.sleep(1)

    # Press Enter or click send button
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
    progress = load_progress()

    total_batches = (len(ALL_URLS) + BATCH_SIZE - 1) // BATCH_SIZE
    start_batch = progress["last_batch"] + 1

    if start_batch > 0:
        print(f"Resuming from batch {start_batch + 1} of {total_batches}")
        print(f"Previously completed: {progress['completed_batches']}")

    print(f"\nTotal videos: {len(ALL_URLS)}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Total batches: {total_batches}")
    print(f"Starting from batch: {start_batch + 1}\n")

    print("=" * 60)
    print("STEP 1: Launch Chrome with remote debugging if not already running:")
    print('  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\')
    print('    --remote-debugging-port=9222 \\')
    print('    --user-data-dir="$HOME/chrome_gemini_profile"')
    print("\nSTEP 2: Sign into Gemini at https://gemini.google.com/")
    print("STEP 3: Press ENTER here when ready")
    print("=" * 60)
    input("\n>>> Press ENTER to connect and start automation... ")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            print("Connected to Chrome!")
        except Exception as e:
            print(f"ERROR connecting to Chrome: {e}")
            print("Make sure Chrome is running with --remote-debugging-port=9222")
            sys.exit(1)

        # Find or open Gemini page
        page = None
        for pg in context.pages:
            if "gemini.google" in pg.url:
                page = pg
                break
        if not page:
            page = context.new_page()
            page.goto("https://gemini.google.com/app")
            time.sleep(5)
            input("Please sign in to Gemini, then press ENTER here... ")

        print(f"\nOn page: {page.url}")

        batches = list(chunk_list(ALL_URLS, BATCH_SIZE))

        for batch_idx in range(start_batch, len(batches)):
            chunk = batches[batch_idx]
            batch_num = batch_idx + 1

            print(f"\n{'='*60}")
            print(f"BATCH {batch_num}/{total_batches}")
            print(f"Videos {batch_idx * BATCH_SIZE + 1} to {batch_idx * BATCH_SIZE + len(chunk)}")
            print(f"{'='*60}")

            # Start new chat for each batch (except first if already on clean page)
            if batch_idx > start_batch or start_batch > 0:
                start_new_chat(page)
                time.sleep(3)

            # Build prompt
            links_text = "\n".join([f"{i+1}. {url}" for i, url in enumerate(chunk)])
            prompt = PROMPT_TEMPLATE.format(links=links_text)

            try:
                print("  Sending prompt to Gemini...")
                send_prompt(page, prompt)

                print("  Waiting for Gemini to generate response...")
                wait_for_gemini_response(page, timeout_seconds=600)

                # Extract response
                response_text = extract_response(page)

                if response_text and len(response_text) > 200:
                    # Save batch file
                    batch_file = os.path.join(OUTPUT_DIR, f"batch_{batch_num:02d}_videos_{batch_idx*BATCH_SIZE+1}_to_{batch_idx*BATCH_SIZE+len(chunk)}.md")
                    with open(batch_file, 'w', encoding='utf-8') as f:
                        f.write(f"# Batch {batch_num} - Videos {batch_idx*BATCH_SIZE+1} to {batch_idx*BATCH_SIZE+len(chunk)}\n\n")
                        f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        f.write(response_text)
                    print(f"  ✅ Saved: {batch_file}")

                    # Update progress
                    progress["completed_batches"].append(batch_num)
                    progress["last_batch"] = batch_idx
                    save_progress(progress)
                else:
                    print(f"  ⚠️ Response too short or empty for batch {batch_num}")
                    print(f"  Response length: {len(response_text) if response_text else 0}")
                    user_input = input("  Copy response manually? Press ENTER to continue, 'r' to retry, 'q' to quit: ")
                    if user_input.lower() == 'q':
                        break
                    elif user_input.lower() == 'r':
                        # Don't update progress, will retry this batch
                        continue

                # Delay between batches
                if batch_idx < len(batches) - 1:
                    delay = 10
                    print(f"  Waiting {delay}s before next batch...")
                    time.sleep(delay)

            except Exception as e:
                print(f"\n  ❌ ERROR in batch {batch_num}: {e}")
                user_input = input("  Fix manually in browser. Press ENTER to continue, 'r' to retry, 'q' to quit: ")
                if user_input.lower() == 'q':
                    break
                elif user_input.lower() == 'r':
                    continue

        print(f"\n{'='*60}")
        print("ALL BATCHES COMPLETE!")
        print(f"Documents saved to: {OUTPUT_DIR}")
        print(f"Completed batches: {progress['completed_batches']}")
        print(f"{'='*60}")

        input("\nPress ENTER to exit...")
        browser.close()


if __name__ == "__main__":
    main()