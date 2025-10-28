from langchain.tools import tool
import subprocess
import os
import asyncio
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from src.knowledge.extract_code_change import get_upstream_branch, get_fork_point

def compilation_env_init(parent_dir: str) -> str:
    """Initialize compilation environment containers for cross-compilation."""
    subprocess.run(f"bash -i -c 'docker-sgx-xargo-create {os.path.basename(parent_dir)}'", shell=True)
    subprocess.run(f"bash -i -c 'docker-sgx-cargo-create {os.path.basename(parent_dir)}'", shell=True)
    return "SGX and Xargo Docker containers initialized."


def compilation_env_destroy() -> str:
    """Destroy compilation environment containers to free up resources."""
    #docker-sgx-xargo-destroy
    subprocess.run("bash -i -c 'docker-sgx-xargo-destroy'", shell=True)
    #docker-sgx-cargo-destroy
    subprocess.run("bash -i -c 'docker-sgx-cargo-destroy'", shell=True)
    return "SGX and Xargo Docker containers destroyed."

@tool
def compile_xargo(rust_project_path: str) -> str:
    """Cross Compilation for Rust project."""
    # 调用 bash -i -c 保证加载 .bashrc 并执行函数
    project_name = os.path.basename(rust_project_path)
    parent_dir = os.path.dirname(rust_project_path)
    
    def exec(cmd, parent_dir):
        process = subprocess.Popen(cmd, shell=True, cwd=parent_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        output_lines = []
        for line in process.stdout:
            print(line, end='')  # 实时输出
            output_lines.append(line)
        process.stdout.close()
        process.wait()
        output = ''.join(output_lines)
        output = ''.join(output_lines)
        # 检查常见 Rust 编译错误关键字
        error_keywords = [
            'error', 'panicked at', "thread 'main' panicked", 'failed to compile', 'could not compile', 'aborting due to', "error: process didn't exit successfully"
        ]
        if any(keyword in output for keyword in error_keywords):
            if "could not compile `cc`" in output:
                cmd = f"bash -i -c 'docker-sgx-cargo-build-fix {project_name} {os.path.basename(parent_dir)}'"
                return exec(cmd, parent_dir)
            else:
                return "Xargo Cross-Compilation failure:{0}".format(output)
        else:
            return "Xargo Cross-Compilation success"
    cmd = f"bash -i -c 'docker-sgx-xargo-build {project_name} {os.path.basename(parent_dir)}'"
    return exec(cmd, parent_dir)
    
@tool
def compile_cargo(rust_project_path: str) -> str:
    """Standard Compilation for Rust project."""
    # 调用 bash -i -c 保证加载 .bashrc 并执行函数
    project_name = os.path.basename(rust_project_path)
    parent_dir = os.path.dirname(rust_project_path)
    def exec(cmd, parent_dir):
        process = subprocess.Popen(cmd, shell=True, cwd=parent_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        output_lines = []
        for line in process.stdout:
            print(line, end='')  # 实时输出
            output_lines.append(line)
        process.stdout.close()
        process.wait()
        output = ''.join(output_lines)
        output = ''.join(output_lines)
        # 检查常见 Rust 编译错误关键字
        error_keywords = [
                'error', 'panicked at', "thread 'main' panicked", 'failed to compile', 'could not compile', 'aborting due to', "error: process didn't exit successfully"
        ]
        if any(keyword in output for keyword in error_keywords):
            if "could not compile `cc`" in output:
                cmd = f"bash -i -c 'docker-sgx-cargo-build-fix {project_name} {os.path.basename(parent_dir)}'"
                return exec(cmd, parent_dir)
            else:
                return "Cargo Compilation failure:{0}".format(output)
        else:
            return "Cargo Compilation success"
    cmd = f"bash -i -c 'docker-sgx-cargo-build {project_name} {os.path.basename(parent_dir)}'"
    return exec(cmd, parent_dir)


@tool 
def list_project_dependencies(rust_project_path: str) -> str:
    """List dependencies of Rust project."""
    # 调用 bash -i -c 保证加载 .bashrc 并执行函数
    project_name = os.path.basename(rust_project_path)
    parent_dir = os.path.dirname(rust_project_path)
    cmd = f"bash -i -c 'docker-sgx-cargo-tree {project_name} {os.path.basename(parent_dir)}'"
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    output_lines = []
    for line in process.stdout:
        print(line, end='')  # 实时输出
        output_lines.append(line)
    process.stdout.close()
    process.wait()
    output = ''.join(output_lines)
    return output

@tool
def initiate_forge_rust_library(rust_project_path: str) -> str:
    """Start to forge a Rust library from the given Rust project path."""
    # Here you would implement the actual forging logic.
    # For demonstration purposes, we'll just return a placeholder message.
    try:
        upstream_branch = get_upstream_branch(repo_path=rust_project_path)  # Just to avoid unused import warning
        fork_point = get_fork_point(repo_path=rust_project_path, upstream_branch=upstream_branch)  # Just to avoid unused import warning
        print(f"Fork point is {fork_point}")
    except Exception as e:
        return "Failure for start forging process due to 'failed to get fork point'"
    # copy the rust project to a new directory and then checkout the repsository to the fork point
    new_project_path = rust_project_path + "_forged"
    if os.path.exists(new_project_path):
        subprocess.run(f"rm -rf {new_project_path}", shell=True)
    subprocess.run(f"cp -r {rust_project_path} {new_project_path}", shell=True)
    
    subprocess.run(f"git checkout {fork_point}", shell=True, cwd=new_project_path)
    
    return "Success for start forging process"

async def main(agent):
    parent_dir = "/workspaces/TEE-Forge-It/forked_repo"
    compilation_env_init(parent_dir)
    for project in os.listdir(parent_dir):
        project_path = os.path.join(parent_dir, project)
        if not os.path.isdir(project_path) or not project.endswith("-sgx"):
            continue
        print("*" * 20)
        print(f"Analyzing {project}")
        # Stream fine-grained events (nodes, tool calls, tokens)
        async for event in agent.astream_events({"messages": [{"role": "user", "content": f"Please help me compile the Rust project {project_path}, and then start to forge the Rust library project if both standard and cross compilation succeed."}]} ,
                                    version="v1"):
            kind = event["event"]            # e.g., "on_tool_start", "on_tool_end", "on_chat_model_stream"
            if kind == "on_tool_start":
                print(f"\n[tool→] {event['name']} {event['data'].get('input')}")
            elif kind == "on_tool_end":
                out = event["data"].get("output", "")
                print(f"\n[tool✓] {event['name']} -> {str(out)[:100]}")
            elif kind == "on_chat_model_stream":
                # print("\n"+str(event["data"]["chunk"])[:50], end="", flush=True)  # token stream
                pass 
            
    compilation_env_destroy()
    
if __name__ == "__main__":
    # 示例用法
    model = ChatOpenAI(
        model="Qwen3-coder:30b", 
        api_key="hanruidong95",
        base_url="http://10.193.104.96:30000/v1",
        temperature=0.2
    )

    agent = create_react_agent(
        model=model,
        tools=[compile_xargo, compile_cargo, list_project_dependencies, initiate_forge_rust_library],
        prompt= """You are a helpful compilation assistant for Rust projects
        Your task is to help users compile Rust projects using Xargo or Cargo, and list project dependencies.      
        - Use the provided tools to perform these tasks as needed.
        - Always think step by step and provide detailed reasoning before giving the final answer.
        - Do not allow parallel execution of tools.
        - When you use a tool, make sure to provide the correct arguments as specified in the tool descriptions.
        """
    )
    asyncio.run(main(agent))