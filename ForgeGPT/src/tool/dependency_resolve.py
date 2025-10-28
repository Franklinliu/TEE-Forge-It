import os 
import glob
import json
import asyncio
from langchain.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

from src.diff.diff_hunk_read import parse_diff_hunks, DiffHunk

forked_repo_dir = "/workspaces/TEE-Forge-It/forked_repo"
changes_dir = "/workspaces/TEE-Forge-It/changes"

@tool
def resolve_dependency(dependency_lib:str) -> str: 
    """get the TEE-compatible version of a dependency library."""
    
    sgx_repos = os.listdir(forked_repo_dir)
    
    for repo in sgx_repos:
        if repo == dependency_lib + "-sgx" or repo.endswith("-"+dependency_lib + "-sgx"):
          git_location = f"https://github.com/mesalock-linux/{repo}"
          return f"Dependency {dependency_lib} should be replaced with its TEE-compatible version {repo} located at {git_location}"

    # otherwise, we need to check if the dependency library itself comes from repo with members in Cargo.toml
    """
    /workspaces/TEE-Forge-It/forked_repo/rustcrypto-traits-sgx_forged/Cargo.toml:
    [workspace]
    members = [
    "aead",
    "block-cipher-trait",
    "crypto-mac",
    "digest",
    "stream-cipher",
    "universal-hash",
    ]
    """
    for repo in sgx_repos:
        repo_path = os.path.join(forked_repo_dir, repo)
        cargo_toml_path = os.path.join(repo_path, "Cargo.toml")
        if not os.path.exists(cargo_toml_path):
            continue
        with open(cargo_toml_path, "r") as f:
            cargo_toml_content = f.read()
            if "[workspace]" in cargo_toml_content and "members" in cargo_toml_content:
                members_start = cargo_toml_content.index("members") + len("members")
                members_end = cargo_toml_content.index("]", members_start) + 1
                members_str = cargo_toml_content[members_start:members_end]
                members = [m.strip().strip('"') for m in members_str.strip("[]").split(",")]
                if dependency_lib in members:
                    git_location = f"https://github.com/mesalock-linux/{repo}"
                    return f"Dependency {dependency_lib} should be replaced with its TEE-compatible version {repo} located at {git_location}"
        
    return f"Dependency {dependency_lib} probably does not have a TEE-compatible version in the forked_repo. Please check in the expert knowledge using the tool `check_dependency_in_expert_knowledge`."

@tool
def check_dependency_in_expert_knowledge(dependency_lib:str) -> str:
    """Check in the expert knowledge to know if there is a TEE-compatible version of the depedency library when having not yet found a TEE-compatible version using the tool `resolve_dependency`."""
    
    knowleges: list[DiffHunk] = []
    change_jsons = glob.glob(os.path.join(changes_dir, "*.json"))
    
    assert "/workspaces/TEE-Forge-It/changes/mio-sgx.json" in change_jsons, "mio-sgx.json should be in the changes directory for testing purpose."
    for project_change_json in change_jsons:
        with open(project_change_json, "r") as f:
            all_file_change_content = json.load(f)
            for _changed_file in all_file_change_content:
                if _changed_file.endswith("Cargo.toml") == False:
                    continue
                if "git_diff" not in all_file_change_content[_changed_file]:
                    continue
                git_diff = all_file_change_content[_changed_file]["git_diff"]
               
                if dependency_lib in git_diff:
                    # there is a change related to the dependency library
                    # we need to split git diff into chunks and check if there is a change related to the dependency library
                    try:
                        chunks = parse_diff_hunks(git_diff)
                        for chunk in chunks:
                            if f"{dependency_lib}" in str(chunk):
                                knowleges.append(chunk)
                    except Exception as e:
                        print(f"Failed to parse diff hunks for {project_change_json}: {e}")
                        continue
    
    if len(knowleges) == 0:
        return f"No knowledge about TEE-compatible version of dependency {dependency_lib} in the expert knowledge."
    else:
        knowledge_str = "\n\n".join([str(k) for k in knowleges])
        return f"Found knowledge about TEE-compatible version of dependency {dependency_lib} in the following expert knowledge:\n{knowledge_str}\n\nPlease check the knowledge and find the TEE-compatible version of the dependency library."
    


async def main(agent):
    final_output = None
    token_buffer = []  # fallback accumulator
    async for event in agent.astream_events({"messages": [{"role": "user", "content": f"Please find the TEE-compatible version of the Rust library `net2`"}]} ,
                                    version="v1"):
            kind = event["event"]            # e.g., "on_tool_start", "on_tool_end", "on_chat_model_stream"
            if kind == "on_tool_start":
                print(f"\n[tool→] {event['name']} {event['data'].get('input')}")
            elif kind == "on_tool_end":
                out = event["data"].get("output", "")
                print(f"\n[tool✓] {event['name']} -> {str(out.content)}")
            elif kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                token_buffer.append(chunk)
                # print(chunk, end="", flush=True)
        
            # (Optional) Some stacks expose a final message on model end:
            elif kind == "on_chat_model_end" and not final_output:
                gens = event["data"].get("generations") or []
                if gens and gens[0] and gens[0][0].get("text"):
                    final_output = gens[0][0]["text"]
                   
    # 3) Fallback if no structured final arrived
    if final_output is None and token_buffer:
        final_output = "".join([msg.content for msg in token_buffer])   
    
    print("\n\n[FINAL OUTPUT]", final_output)     
    
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
        tools=[resolve_dependency, check_dependency_in_expert_knowledge],
        prompt= """You are an expert developer for Rust third-party libraries. Your task is to identify the TEE-compatible version of a given library.      
        - Use the provided tools to perform these tasks as needed.
        - Always think step by step and provide detailed reasoning before giving the final answer.
        - Do not allow parallel execution of tools.
        - When you use a tool, make sure to provide the correct arguments as specified in the tool descriptions.
        - Please give a short and concise final answer.
        """
    )
    asyncio.run(main(agent))