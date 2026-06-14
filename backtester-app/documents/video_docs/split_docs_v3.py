import os
import re

batch_dir = "/Users/parthbhandakkar/Desktop/WorkZera/Projects/TradeBot/ytLearning/backtester-app/documents/video_docs"
out_dir = os.path.join(batch_dir, "individual")
os.makedirs(out_dir, exist_ok=True)

# Clean up previously generated bad files
for f in os.listdir(out_dir):
    if f.endswith(".md"):
        os.remove(os.path.join(out_dir, f))

batch_files = [f for f in os.listdir(batch_dir) if f.startswith("batch_") and f.endswith(".md")]
batch_files.sort()

video_counter = 1

for batch_file in batch_files:
    filepath = os.path.join(batch_dir, batch_file)
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    video_url_indices = [i for i, line in enumerate(lines) if 'Video URL:' in line and 'youtube.com' in line]
    
    if not video_url_indices:
        print(f"Warning: No valid videos found in {batch_file}")
        continue
        
    for idx, url_idx in enumerate(video_url_indices):
        source_idx = url_idx
        for i in range(url_idx-1, max(0, url_idx-10), -1):
            if 'Source:' in lines[i]:
                source_idx = i
                break
                
        title_idx = source_idx
        for i in range(source_idx-1, max(0, source_idx-10), -1):
            line_str = lines[i].strip()
            if line_str and not line_str.startswith('---') and not line_str.startswith('Here are') and not line_str.startswith('# Batch'):
                title_idx = i
                break
                
        if idx + 1 < len(video_url_indices):
            next_url_idx = video_url_indices[idx + 1]
            next_source_idx = next_url_idx
            for i in range(next_url_idx-1, max(0, next_url_idx-10), -1):
                if 'Source:' in lines[i]:
                    next_source_idx = i
                    break
            next_title_idx = next_source_idx
            for i in range(next_source_idx-1, max(0, next_source_idx-10), -1):
                line_str = lines[i].strip()
                if line_str and not line_str.startswith('---'):
                    next_title_idx = i
                    break
            
            # If the line before next title is '---', exclude it from this block
            end_idx = next_title_idx
            if end_idx > 0 and lines[end_idx-1].strip() == '---':
                end_idx -= 1
        else:
            end_idx = len(lines)
            for i in range(url_idx+1, len(lines)-1):
                if 'Faiz SMC' in lines[i+1] and 'views' in lines[i+1]:
                    end_idx = i
                    break
                    
        video_lines = lines[title_idx:end_idx]
        video_text = "".join(video_lines).strip()
        
        title = lines[title_idx].strip()
        clean_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', title)
        clean_title = clean_title.replace(' ', '_')[:50]
        if clean_title.startswith('StrategyTopic_Name_'):
            clean_title = clean_title.replace('StrategyTopic_Name_', '')
        
        clean_title = re.sub(r'_+', '_', clean_title).strip('_')
            
        filename = f"video_{video_counter:02d}_{clean_title}.md"
        out_path = os.path.join(out_dir, filename)
        
        with open(out_path, 'w', encoding='utf-8') as out_f:
            out_f.write(video_text + '\n')
            
        print(f"Saved {filename}")
        video_counter += 1

print(f"\nDone! Extracted {video_counter-1} individual videos.")
