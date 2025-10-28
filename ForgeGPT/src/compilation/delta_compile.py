import os
import json
import subprocess
import sys 
sys.path.append(os.path.join(os.path.dirname(__file__), '../knowledge'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../diff'))
from compile import xargo_compile_sgx_project, cargo_compile_sgx_project
from undo_diff_hunk import revert_hunk_on_new_file
from diff_hunk_read import parse_diff_hunks

def delta_compile_sgx_project(work_dir, project_name):
    """
    遍历每个 git diff hunk，依次还原并测试编译。
    :param project_name: original_repo 下的子目录名（即 SGX 库项目名）
    """
    project_path = f"{work_dir}/{project_name}"
    if not os.path.isdir(project_path):
        raise FileNotFoundError(f"Project path not found: {project_path}")

    # 读取 diff 信息（假设 diff 文件为 changes/{project_name}.json，结构同 repo_diff.py 输出）
    diff_json_path = f"/workspaces/TEE-Forge-It/changes/{project_name}.json"
    if not os.path.isfile(diff_json_path):
        raise FileNotFoundError(f"Diff json not found: {diff_json_path}")
    with open(diff_json_path, 'r') as f:
        diff_data = json.load(f)

    revert_results = {}
    for rel_file, info in diff_data.items():
        file_path = os.path.join(project_path, rel_file)
        if not os.path.isfile(file_path):
            print(f"File not found: {file_path}, skip.")
            continue
        diff_text = info['git_diff']
        # 解析所有hunk
       
        hunks = parse_diff_hunks(diff_text)
        # 读取新文件内容
        with open(file_path, 'r') as f:
            orig_content = f.read()
        for idx, hunk in enumerate(hunks):
            # 还原hunk
            try:
                reverted_content = revert_hunk_on_new_file(hunk, orig_content)
            except Exception as e:
                print(f"Failed to revert hunk {idx} in {rel_file}: {e}")
                continue
            # 写入临时还原文件
            tmp_file_path = file_path + ".revert_tmp"
            with open(tmp_file_path, 'w') as f:
                f.write(reverted_content)
            # 用还原内容替换原文件
            os.replace(tmp_file_path, file_path)
            print(f"Reverted hunk {idx} in {file_path}, testing compilation...")
            # 编译测试
            try:
                xargo_compile_sgx_project(work_dir, project_name)
                revert_results.setdefault(rel_file, []).append({"hunk_index": idx, "hunk": "\n".join(hunk.lines), "xargo_compilable": True})
            except Exception as e:
                revert_results.setdefault(rel_file, []).append({"hunk_index": idx,  "hunk": "\n".join(hunk.lines), "xargo_compilable": False, "xargo_error": str(e)})
            try:
                cargo_compile_sgx_project(work_dir, project_name)
                revert_results.setdefault(rel_file, []).append({"hunk_index": idx,  "hunk": "\n".join(hunk.lines), "cargo_compilable": True})
            except Exception as e:
                revert_results.setdefault(rel_file, []).append({"hunk_index": idx,  "hunk": "\n".join(hunk.lines), "cargo_compilable": False, "cargo_error": str(e)})
            # 恢复原内容，准备下一个hunk
            with open(file_path, 'w') as f:
                f.write(orig_content)

    return revert_results


def delta_compile_sgx_projects(work_dir):
    def get_git_submodules(work_dir):
        "/获取所有git子模块路径/"
        gitmodules_path = os.path.join(work_dir, '.gitmodules')
        submodules = []
        if os.path.isfile(gitmodules_path):
            with open(gitmodules_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('path = '):
                        submodules.append(line.split('=', 1)[1].strip())
        return submodules

    # docker-sgx-xargo-create
    subprocess.run(f"bash -i -c 'docker-sgx-xargo-create {work_dir}'", shell=True)
    # docker-sgx-cargo-create
    subprocess.run(f"bash -i -c 'docker-sgx-cargo-create {work_dir}'", shell=True)

    projects = get_git_submodules(work_dir)
    all_results = {}
    for project in projects:
        if not os.path.isdir(os.path.join(work_dir, project)):
            print(f"Skipping non-directory submodule: {project}")
            continue
        
        # if project != "cbor-sgx":
        #     continue
        print("Processing project:", project)
        
        # call git reset --hard to discard any local changes
        subprocess.run("git reset --hard", shell=True, cwd=os.path.join(work_dir, project))

        try:
            xargo_compile_sgx_project(work_dir, project)
        except Exception as e:
            print(f"Initial xargo compile failed for {project}: {e}")
            all_results[project] = {"error": f"Initial compile failed: {str(e)}"}
            continue
     
        try:
            results = delta_compile_sgx_project(work_dir, project)
            all_results[project] = {"success": True}
        except Exception as e:
            print(f"Delta compile failed for {project}: {e}")
            all_results[project] = {"error": f"Delta compile failed: {str(e)}"}
            continue
        
        # 保存每个项目的结果到 project.deltacompile.json
        output_path = os.path.join("/workspaces/TEE-Forge-It/changes", f"{project}.deltacompile.json")
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    
    #docker-sgx-xargo-destroy
    subprocess.run("bash -i -c 'docker-sgx-xargo-destroy'", shell=True)
    #docker-sgx-cargo-destroy
    subprocess.run("bash -i -c 'docker-sgx-cargo-destroy'", shell=True)
    return all_results


if __name__ == "__main__":
    # Note this requires that the script is run when working directory is /workspaces/TEE-Forge-It
    all_results = delta_compile_sgx_projects("forked_repo")
    for project, result in all_results.items():
        print(f"Project: {project}, Result: {result}")