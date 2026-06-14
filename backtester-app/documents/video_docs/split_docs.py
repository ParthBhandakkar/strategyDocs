import os
import re

batch_dir = "/Users/parthbhandakkar/Desktop/WorkZera/Projects/TradeBot/ytLearning/backtester-app/documents/video_docs"
out_dir = os.path.join(batch_dir, "individual")
os.makedirs(out_dir, exist_ok=True)

# Find all batch files and sort them to process in order
batch_files = [f for f in os.listdir(batch_dir) if f.startswith("batch_") and f.endswith(".md")]
batch_files.sort()

video_counter = 1

for batch_file in batch_files:
    filepath = os.path.join(batch_dir, batch_file)
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split the content by "Strategy/Topic Name:"
    # This might have ### or ** or nothing before it. Let's use regex to find all occurrences
    # Or just simple string splitting if it's consistent.
    # The prompt might have produced slightly different variations, e.g. "**Strategy/Topic Name:**" or "### Strategy/Topic Name:"
    
    # Let's split by looking for something similar to "Strategy/Topic Name:"
    # We can split using re.split
    parts = re.split(r'(?m)^[\s\#\*]*Strategy/Topic Name:', content)
    
    # The first part is usually the batch header ("# Batch X ... Generated: ...")
    header = parts[0]
    
    for part in parts[1:]:
        # Now part contains the rest of the document for one video
        # We need to prepend "Strategy/Topic Name:" back because it was consumed by split
        video_content = "Strategy/Topic Name:" + part
        
        # Try to extract a clean title from the first line
        first_line = part.strip().split('\n')[0].strip()
        # Clean up the title for filename
        clean_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', first_line)
        clean_title = clean_title.replace(' ', '_')[:50] # Limit length
        
        filename = f"video_{video_counter:02d}_{clean_title}.md"
        out_path = os.path.join(out_dir, filename)
        
        with open(out_path, 'w', encoding='utf-8') as out_f:
            out_f.write(video_content.strip() + '\n')
            
        print(f"Saved {filename}")
        video_counter += 1

print(f"\nDone! Extracted {video_counter-1} individual videos to {out_dir}")
