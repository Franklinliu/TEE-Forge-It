import os
import re

HUNK_HEADER_RE = re.compile(r'^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@')

class DiffHunk:
    def __init__(self, old_start, old_count, new_start, new_count, lines):
        self.old_start = int(old_start)
        self.old_count = int(old_count) if old_count else 1
        self.new_start = int(new_start)
        self.new_count = int(new_count) if new_count else 1
        self.lines = lines  # List of lines in the hunk

    def __repr__(self):
        return (f"<DiffHunk -{self.old_start},{self.old_count} "
                f"+{self.new_start},{self.new_count} lines={len(self.lines)}>")

def parse_diff_hunks(diff_text):
    """
    Parses hunks from a git diff text.
    Returns a list of DiffHunk objects.
    """
    lines = diff_text.splitlines()
    hunks = []
    i = 0
    # 跳过所有非 hunk 头部的内容
    while i < len(lines) and not HUNK_HEADER_RE.match(lines[i]):
        i += 1
    # 开始解析 hunk
    while i < len(lines):
        match = HUNK_HEADER_RE.match(lines[i])
        if match:
            old_start, old_count, new_start, new_count = match.groups()
            hunk_lines = []
            i += 1
            while i < len(lines) and not HUNK_HEADER_RE.match(lines[i]):
                hunk_lines.append(lines[i])
                i += 1
            hunks.append(DiffHunk(old_start, old_count, new_start, new_count, hunk_lines))
        else:
            i += 1
    return hunks


import json


def parse_changes_project(project_change_json_path):
    """
    Parses a JSON file containing changes for a project.
    Returns a dict: {filename: [DiffHunk, ...]}
    """
    with open(project_change_json_path, 'r', encoding='utf-8') as f:
        changes = json.load(f)
    result = {}
    for change_file in changes:
        diff_text = changes[change_file]["git_diff"]
        hunks = parse_diff_hunks(diff_text)
        result[change_file] = hunks
    return result


def parse_all_changes(directory="changes"):
    """
    Parses all .json files in the given directory as git diff hunks.
    Returns a dict: {filename: [DiffHunk, ...]}
    """
    result = {}
    for fname in os.listdir(directory):
        if fname.endswith('.json'):
            path = os.path.join(directory, fname)
            result[fname] = parse_changes_project(path)
    return result

# Example usage:
if __name__ == "__main__":
    all_hunks = parse_all_changes()
    for fname, hunks in all_hunks.items():
        print(f"{fname}: {hunks.keys()}")
