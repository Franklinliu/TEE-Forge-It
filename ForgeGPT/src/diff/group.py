import subprocess
from typing import List, Dict, Any

# 引入qwen模型（相对导入）
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../model'))
# from qwen import qwen as model

# 引入qwen模型（相对导入）
import sys
import os

from src.model.chatgpt import gpt3_5_turbo as model
from src.diff.git_util import get_git_diff

def parse_diff(diff_text: str) -> List[Dict[str, Any]]:
    """
    Parse the diff text and group changes into addition, update, and deletion.
    Returns a list of changes with type and content.
    """
    changes = []
    lines = diff_text.splitlines()
    for line in lines:
        if line.startswith('+++') or line.startswith('---') or line.startswith('@@'):
            continue
        if line.startswith('+') and not line.startswith('+++'):
            changes.append({'action': 'addition', 'content': line[1:].strip()})
        elif line.startswith('-') and not line.startswith('---'):
            changes.append({'action': 'deletion', 'content': line[1:].strip()})
    # Group updates: a deletion immediately followed by an addition
    grouped = []
    i = 0
    while i < len(changes):
        if (changes[i]['action'] == 'deletion' and
            i+1 < len(changes) and changes[i+1]['action'] == 'addition'):
            grouped.append({
                'action': 'update',
                'from': changes[i]['content'],
                'to': changes[i+1]['content']
            })
            i += 2
        else:
            grouped.append(changes[i])
            i += 1
    return grouped


def group_diff_actions(diff_text: str) -> List[Dict[str, Any]]:
    """
    Main function to group diff actions from diff text.
    """
    return parse_diff(diff_text)


def semantic_group_diff_actions(diff_text: str) -> List[Dict[str, Any]]:
    """
    Use LLM to semantically group diff actions from diff text.
    """
    prompt = (
        "You are an expert that understand code changes. Please group code changes based on the following semantic types:（addition, update, deletion），"
        "You must group them based on semantic relationship and generate brief summary, change type, and change content per semantic change group.\n"
        f"Code change: {diff_text}\n"
        "Please output in the form of JSON array, of which each element includes 'type' (e.g., addition, update, and deletion), 'summary'(showing what the changes do), and 'actions'(listing the corresponding raw code changes).",
        "NOTE for any 'update' element, it MUST include both the 'from' and 'to' content."
    )
    response = model.invoke(prompt)
    import json
    try:
        response = response.content.replace("```", "").replace("json", '')
        # print(diff_text)  # 调试输出
        # print("LLM response:", response)  # 调试输出
        semantic_groups = json.loads(response)
    except Exception:
        semantic_groups = [{"summary": "LLM输出解析失败", "actions": diff_text}]
    return semantic_groups

# Example usage:
if __name__ == "__main__":
    file1 = "/workspaces/TEE-Forge-It/original_repo/bytes-sgx/src/lib.rs"
    file2 = "/workspaces/TEE-Forge-It/forked_repo/bytes-sgx/src/lib.rs"
    diff_text = get_git_diff(file1, file2)
    print("=== 传统分组 ===")
    actions = group_diff_actions(diff_text)
    for action in actions:
        print(action)
    print("=== 语义分组（LLM） ===")
    semantic_actions = semantic_group_diff_actions(diff_text)
    for group in semantic_actions:
        print(group)