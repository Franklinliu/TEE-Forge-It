import sys 
import os 
sys.path.append(os.path.join(os.path.dirname(__file__), '../diff'))
from diff_hunk_read import DiffHunk

def apply_hunk_on_new_file(hunk: DiffHunk, orig_file_content):
    """
    根据 diff hunk 和新文件内容，返回还原后的文件内容。
    """
    old_lines = orig_file_content.splitlines()
    new_start, hunk_lines = hunk.new_start, hunk.lines
    # 构建新内容和旧内容
    old_chunk = []
    new_chunk = []
    for line in hunk_lines:
        if line.startswith('-'):
            old_chunk.append(line[1:])
        elif line.startswith('+'):
            new_chunk.append(line[1:])
        else:
            old_chunk.append(line[1:])
            new_chunk.append(line[1:])
    # 还原：找到 new_chunk 在 new_lines 的位置并替换为 old_chunk
    idx = new_start - 1
    for i in range(len(old_lines) - len(old_chunk) + 1):
        if list(map(lambda item: item.strip(), old_lines[i:i+len(old_chunk)])) == list(map(lambda item: item.strip(), old_chunk)):
            idx = i
            break
    old_lines = old_lines[:idx] + new_chunk + old_lines[idx+len(old_chunk):]
    return '\n'.join(old_lines)


if __name__ == "__main__":
    # 示例用法
    hunk = (3, 5, [
        " line unchanged",
        "+line removed",
        "-line added",
        " line unchanged"
    ])
    orig_file_content = """line 1
line 2
line unchanged
line added
line unchanged
line 4
line 5"""
    reverted_content = apply_hunk_on_new_file(hunk, orig_file_content)
    print("New File Content:\n", reverted_content)
