import os
import sys
import json

from src.knowledge.extract_code_change import get_fork_info, get_changed_files_since_fork
from src.diff.group import semantic_group_diff_actions
from src.diff.git_util import get_git_diff

def analyze_forked_repo(repo_path: str):
    """
    Analyze a forked repo, retrieve changed rust files since fork point, and compute semantic change groups for each file.
    """
    # 获取fork信息
    upstream_remote, upstream_branch, fork_point = get_fork_info(repo_path)
    print(f"Upstream remote: {upstream_remote}")
    print(f"Upstream branch: {upstream_branch}")
    print(f"Fork point: {fork_point}")

    # 获取变更的rust文件
    changed_rust_files = get_changed_files_since_fork(repo_path, fork_point)
    print(f"Changed Rust files: {changed_rust_files}")

    import tempfile
    import subprocess
    result = {}
    for rust_file in changed_rust_files:
        # 检查upstream分支是否存在该文件
        file_exists_in_upstream = subprocess.call(
            ["git", "cat-file", "-e", f"{upstream_branch}:{rust_file}"],
            cwd=repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        ) == 0
        if not file_exists_in_upstream:
            print(f"Skipping {rust_file}: does not exist in upstream branch.")
            continue
        file_path = os.path.join(repo_path, rust_file)
        with tempfile.NamedTemporaryFile(delete=False) as tmp_upstream:
            tmp_upstream_path = tmp_upstream.name
            with open(tmp_upstream_path, 'w') as f:
                content = subprocess.check_output(
                    ["git", "show", f"{upstream_branch}:{rust_file}"],
                    cwd=repo_path,
                    text=True
                )
                f.write(content)
        diff_text = get_git_diff(tmp_upstream_path, file_path)
        if diff_text.strip() == "":
            os.remove(tmp_upstream_path)
            continue
        # semantic_groups = semantic_group_diff_actions(diff_text)
        # result[rust_file] = dict(git_diff = diff_text, semantic_changes = semantic_groups)
        result[rust_file] = dict(git_diff = diff_text)
        os.remove(tmp_upstream_path)
    return result

if __name__ == "__main__":
    base_dir = "/workspaces/TEE-Forge-It/forked_repo"
    output_dir = "/workspaces/TEE-Forge-It/changes"
    os.makedirs(output_dir, exist_ok=True)
    for project in os.listdir(base_dir):
        project_path = os.path.join(base_dir, project)
        if not os.path.isdir(project_path):
            continue
        print(f"Analyzing {project_path}")
        try:
            changes = analyze_forked_repo(project_path)
            output_path = os.path.join(output_dir, f"{project}.json")
            with open(output_path, "w") as f:
                json.dump(changes, f, indent=2, ensure_ascii=False)
            print(f"Saved changes to {output_path}")
            
            # save changes to a text file for easier viewing
            text_output_path = os.path.join(output_dir, f"{project}_changes.txt")
            with open(text_output_path, "w") as f:
                for file, change_info in changes.items():
                    f.write(f"File: {file}\n")
                    f.write("Git Diff:\n")
                    f.write(change_info['git_diff'] + "\n")
                    # if 'semantic_changes' in change_info:
                    #     f.write("Semantic Changes:\n")
                    #     for change in change_info['semantic_changes']:
                    #         f.write(json.dumps(change, ensure_ascii=False) + "\n")
                    f.write("\n" + "="*80 + "\n\n")
            print(f"Saved text changes to {text_output_path}")
        
        except Exception as e:
            print(f"Error analyzing {project_path}: {e}")
