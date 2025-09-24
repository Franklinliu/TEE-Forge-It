import os
import subprocess
from typing import List

def get_upstream_remote(repo_path: str) -> str:
    """
    Get the upstream remote URL of the forked repository.
    """
    try:
        remotes = subprocess.check_output(
            ["git", "remote", "-v"],
            cwd=repo_path,
            text=True
        ).splitlines()
        for remote in remotes:
            if "(fetch)" in remote and "upstream" in remote:
                return remote.split()[1]  # Extract the URL
        raise RuntimeError("Upstream remote not found. Ensure 'upstream' is set.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to get upstream remote: {e}")

def get_upstream_branch(repo_path: str) -> str:
    """
    Get the upstream branch of the forked repository.
    """
    try:
        # Get the current branch
        current_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            text=True
        ).strip()
        # Assume the upstream branch has the same name as the current branch
        return f"upstream/{current_branch}"
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to determine upstream branch: {e}")

def get_fork_point(repo_path: str, upstream_branch: str) -> str:
    """
    Get the fork point of the repository.
    """
    try:
        # Find the fork point using git merge-base
        fork_point = subprocess.check_output(
            ["git", "merge-base", "--fork-point", upstream_branch],
            cwd=repo_path,
            text=True
        ).strip()
        return fork_point
    except subprocess.CalledProcessError as e:
        # Fallback to using git merge-base without --fork-point
        try:
            fork_point = subprocess.check_output(
                ["git", "merge-base", upstream_branch, "HEAD"],
                cwd=repo_path,
                text=True
            ).strip()
            return fork_point
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to find fork point: {e}")


def get_changed_files_since_fork(repo_path: str, fork_point: str) -> List[str]:
    """
    Get the list of changed files since the fork point.
    """
    try:
        # Get the list of changed files since the fork point
        changed_files = subprocess.check_output(
            ["git", "diff", "--name-only", fork_point],
            cwd=repo_path,
            text=True
        ).splitlines()
        # Filter only Rust files
        rust_files = [file for file in changed_files if file.endswith(".rs")]
        return rust_files
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to get changed files: {e}")

def record_change_for_file(repo_path: str, rust_file: str, fork_point: str) -> str:
    """
    Get the diff for a specific Rust file since the fork point.
    """
    try:
        diff = subprocess.check_output(
            ["git", "diff", fork_point, "--", rust_file],
            cwd=repo_path,
            text=True
        )
        return diff
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to get diff for {rust_file}: {e}")
def record_changes(repo_path: str, rust_files: List[str], fork_point: str, output_file: str, upstream_branch: str):
    """
    Record the changes of Rust files to an output file, only for files that exist in both
    the upstream repository and the forked repository.

    Args:
        repo_path (str): Path to the forked repository.
        rust_files (List[str]): List of Rust files that have changed.
        fork_point (str): The fork point commit hash.
        output_file (str): Path to the output file.
        upstream_branch (str): The upstream branch to check file existence.
    """
    try:
        with open(output_file, "w") as f:
            for rust_file in rust_files:
                # Check if the file exists in the upstream branch
                file_exists_in_upstream = subprocess.call(
                    ["git", "cat-file", "-e", f"{upstream_branch}:{rust_file}"],
                    cwd=repo_path,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                ) == 0

                if file_exists_in_upstream:
                    # Get the diff for the Rust file
                    diff = subprocess.check_output(
                        ["git", "diff", fork_point, "--", rust_file],
                        cwd=repo_path,
                        text=True
                    )
                    f.write(f"Changes in {rust_file}:\n")
                    f.write(diff)
                    f.write("\n" + "="*80 + "\n")
                else:
                    print(f"Skipping {rust_file}: does not exist in upstream branch.")
    except Exception as e:
        raise RuntimeError(f"Failed to record changes: {e}")


def get_fork_info(repo_path: str):
    """
    Get the fork information including upstream remote, upstream branch, and fork point.
    """
    upstream_remote = get_upstream_remote(repo_path)
    upstream_branch = get_upstream_branch(repo_path)
    fork_point = get_fork_point(repo_path, upstream_branch)
    return upstream_remote, upstream_branch, fork_point

def main(repo_path: str, output_file: str):
    try:
        # Get the upstream remote URL (for debugging purposes)
        upstream_remote = get_upstream_remote(repo_path)
        print(f"Upstream remote: {upstream_remote}")

        # Determine the upstream branch
        upstream_branch = get_upstream_branch(repo_path)
        print(f"Upstream branch: {upstream_branch}")

        # Get the fork point
        fork_point = get_fork_point(repo_path, upstream_branch)
        print(f"Fork point: {fork_point}")

        # Get the list of changed Rust files
        rust_files = get_changed_files_since_fork(repo_path, fork_point)
        print(f"Changed Rust files: {rust_files}")

        # Record the changes
        record_changes(repo_path, rust_files, fork_point, output_file, upstream_branch)
        print(f"Changes recorded in {output_file}")
    except RuntimeError as e:
        print(e)

if __name__ == "__main__":
    import argparse

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Extract Rust file changes since the fork point.")
    parser.add_argument("repo_path", help="Path to the forked repository")
    parser.add_argument("--output-file", default="rust_changes_since_fork.txt", help="Output file to store the changes (default: rust_changes_since_fork.txt)")
    args = parser.parse_args()

    main(args.repo_path, args.output_file)