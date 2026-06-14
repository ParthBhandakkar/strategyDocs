import os
import re

batch_dir = "/Users/parthbhandakkar/Desktop/WorkZera/Projects/TradeBot/ytLearning/backtester-app/documents/video_docs"
out_dir = os.path.join(batch_dir, "individual")
os.makedirs(out_dir, exist_ok=True)

batch_files = [f for f in os.listdir(batch_dir) if f.startswith("batch_") and f.endswith(".md")]
batch_files.sort()

video_counter = 1

for batch_file in batch_files:
    filepath = os.path.join(batch_dir, batch_file)
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # We will split the text based on `Source: Faiz SMC` or `Video URL:`
    # Let's find all occurrences of `Video URL:`
    matches = list(re.finditer(r'(?mi)^.*Video URL:\s*(https?://[^\s]+)', content))
    
    if not matches:
        print(f"Warning: No videos found in {batch_file}")
        continue
        
    for i, match in enumerate(matches):
        url = match.group(1)
        video_id = url.split('v=')[-1][:11] if 'v=' in url else f"vid_{video_counter}"
        
        # The start of this video's content
        # We need to backtrack a few lines to capture the title and Source
        # Let's find the start index of the match
        start_idx = match.start()
        
        # Backtrack up to 5 lines or to the end of the previous video
        # A good heuristic: split by `Source: Faiz SMC` if we can, or just split halfway between videos.
        # Actually, let's find `Source:` which is right before `Video URL:`
        source_match = re.search(r'(?msi)(?:^|\n)([^\n]+)\n+[^\n]*Source:\s*Faiz SMC.*?(?=\n.*Video URL:)', content[:match.start()+1])
        
        if source_match:
            # We found the title! It's the first group of source_match, but wait, source_match is searching from the beginning of the file.
            # Better to search backwards from match.start()
            pass
            
    # Alternative approach: split by looking for the Title lines. The prompt asked for:
    # ---
    # # Strategy/Topic Name
    # **Source:** Faiz SMC
    # **Video URL:**
    
    # Let's just split the content using regex that looks for `Source: Faiz SMC`
    # We can split the string by looking for a line that contains `Source: Faiz SMC` or similar.
    # But wait, the title is usually the line *before* `Source: Faiz SMC`.
    pass

# Let's do a simpler block-based extraction
for batch_file in batch_files:
    filepath = os.path.join(batch_dir, batch_file)
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    video_blocks = []
    current_block = []
    
    for i, line in enumerate(lines):
        # Identify the start of a new video. It's usually a title line followed closely by Source or Video URL.
        # Let's just look for `Video URL:`
        if re.search(r'(?i)^[\s\*\#]*Video URL:', line):
            # This line is Video URL. The previous 1-5 lines should be the start of the block.
            # We will mark the start of the current_block at the Title line.
            # Let's find the Title line. It's usually above the `Source:` line.
            pass

def process_batch_files():
    global video_counter
    for batch_file in batch_files:
        filepath = os.path.join(batch_dir, batch_file)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Find all Video URLs
        urls = list(re.finditer(r'(?mi)^.*Video URL:\s*(https?://[^\s]+)', content))
        if not urls:
            # Fallback for batches that might have failed to format
            continue
            
        for i in range(len(urls)):
            current_match = urls[i]
            next_match = urls[i+1] if i + 1 < len(urls) else None
            
            # The end of this video is the start of the next video's title
            # Let's say the next video's title is ~3 lines before its Video URL
            end_pos = len(content)
            if next_match:
                # Find the `Source:` or title line before next_match
                # We can just split at the next_match.start() and backtrack to the first empty line
                text_before_next = content[current_match.end():next_match.start()]
                last_empty_line = text_before_next.rfind('\n\n')
                if last_empty_line != -1:
                    end_pos = current_match.end() + last_empty_line
                else:
                    end_pos = next_match.start() - 100 # arbitrary backtrack
            
            # The start of this video is before its Video URL
            # Backtrack to find the title
            text_before_current = content[:current_match.start()]
            last_empty_line_before = text_before_current.rfind('\n\n')
            
            # Actually, `Source: Faiz SMC` is between the title and the URL.
            source_idx = text_before_current.rfind('Source:')
            if source_idx != -1 and (current_match.start() - source_idx) < 200:
                # Find the title which is before `Source:`
                text_before_source = content[:source_idx]
                last_empty = text_before_source.rfind('\n\n')
                start_pos = last_empty if last_empty != -1 else 0
            else:
                start_pos = last_empty_line_before if last_empty_line_before != -1 else 0
                
            video_text = content[start_pos:end_pos].strip()
            
            # Extract clean title from the text
            # Usually the first non-empty line
            lines = [l.strip() for l in video_text.split('\n') if l.strip()]
            title = "Unknown_Video"
            for l in lines:
                if not l.startswith('Source:') and not l.startswith('Video URL:') and not l.startswith('---'):
                    title = l
                    break
            
            clean_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', title)
            clean_title = clean_title.replace(' ', '_')[:50]
            if clean_title.startswith('StrategyTopic_Name_'):
                clean_title = clean_title.replace('StrategyTopic_Name_', '')
                
            filename = f"video_{video_counter:02d}_{clean_title}.md"
            out_path = os.path.join(out_dir, filename)
            
            with open(out_path, 'w', encoding='utf-8') as out_f:
                out_f.write(video_text + '\n')
                
            print(f"Saved {filename}")
            video_counter += 1

process_batch_files()
print(f"\nDone! Extracted {video_counter-1} individual videos.")
