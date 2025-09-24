import os
import sys

# Import helpers from knowledge and diff modules
sys.path.append(os.path.join(os.path.dirname(__file__), '../knowledge'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../diff'))
from extract_code_change import get_fork_info, get_changed_files_since_fork


def get_rust_files(project_path):
    # 获取fork信息
    upstream_remote, upstream_branch, fork_point = get_fork_info(project_path)
    print(f"Upstream remote: {upstream_remote}")
    print(f"Upstream branch: {upstream_branch}")
    print(f"Fork point: {fork_point}")

    # 获取变更的rust文件
    changed_rust_files = get_changed_files_since_fork(project_path, fork_point)
    print(f"Changed Rust files: {changed_rust_files}")
    return changed_rust_files, upstream_branch,fork_point

def get_original_file_content_with_upstream_branch(repo_path, upstream_branch, rust_file):
    import subprocess
    try:
        content = subprocess.check_output(
            ["git", "show", f"{upstream_branch}:{rust_file}"],
            cwd=repo_path,
            text=True
        )
        return content
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving original file content for {rust_file}: {e}")
        return None

def get_original_file_content(repo_path, rust_file):
    import subprocess
    try:
        # 获取fork信息
        upstream_remote, upstream_branch, fork_point = get_fork_info(repo_path)
        content = subprocess.check_output(
            ["git", "show", f"{upstream_branch}:{rust_file}"],
            cwd=repo_path,
            text=True
        )
        return content
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving original file content for {rust_file}: {e}")
        return None
    
def get_git_diff(file_a: str, file_b: str) -> str:
    """
    Get the git diff between two files.
    """
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--unified=0", file_a, file_b],
        capture_output=True, text=True
    )
    return result.stdout