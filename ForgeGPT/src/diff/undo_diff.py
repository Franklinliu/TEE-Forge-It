import sys
import os
import json

# 确保可以导入 group.py 和 chatgpt.py
from src.diff.group import semantic_group_diff_actions
from src.diff.git_util import get_git_diff
from src.model.chatgpt import gpt3_5_turbo as model

def undo_semantic_change(diff_text: str, after_code: str, group_index: int) -> str:
    """
    Use LLM to undo a specific semantic change group.
    diff_text: git diff text between two files
    after_code: content of the file after change
    group_index: index of the semantic group to undo
    Returns the new file content after undo.
    """
    semantic_groups = semantic_group_diff_actions(diff_text)
    if group_index < 0 or group_index >= len(semantic_groups):
        raise ValueError("group_index out of range")
    group_to_undo = semantic_groups[group_index]
    prompt = (
        "You are an expert in code change rollback. Given the following code content and a semantic change group to revert, "
        "please generate the new code with this change group reverted.\n"
        f"Current code content:\n{after_code}\n"
        f"Semantic change group to revert:\n{json.dumps(group_to_undo, ensure_ascii=False)}\n"
        "Please output the full code after reverting the change group, and do not include any extra explanation."
    )
    response = model.invoke(prompt)
    code = response.content if hasattr(response, 'content') else str(response)
    code = code.replace('```', '').replace('python', '').strip()
    return code

# Example usage:
if __name__ == "__main__":
    file1 = "/workspaces/TEE-Forge-It/original_repo/bytes-sgx/src/lib.rs"
    file2 = "/workspaces/TEE-Forge-It/forked_repo/bytes-sgx/src/lib.rs"
    group_idx = 0  # 需要撤销的语义分组索引
    diff_text = get_git_diff(file1, file2)
    with open(file2, 'r') as f:
        after_code = f.read()
    new_code = undo_semantic_change(diff_text, after_code, group_idx)
    print(new_code)
