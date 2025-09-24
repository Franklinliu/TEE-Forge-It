
import os
import json
import subprocess
import sys
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.llms import Ollama
from langchain_core.messages.ai import AIMessage
from src.compilation.compile import xargo_compile_sgx_project, cargo_compile_sgx_project
from src.compilation.format import remove_ansi_colors
# Import helpers from knowledge and diff modules
from src.diff.git_util import get_rust_files, get_original_file_content_with_upstream_branch, get_original_file_content, get_git_diff
from src.embed.error_embed import get_hunk_from_metadata, get_reference_example_from_metadata
from src.diff.diff_hunk_read import parse_diff_hunks
from src.diff.apply_diff_hunk import apply_hunk_on_new_file
from src.model.chatgpt import gpt3_5_turbo
from src.model.qwen import qwen3coder_30b
from src.migration.prompt import prompt_hunk_gen, prompt_code_gen, prompt_git_diff_summary

def analyze_forked_repo(repo_path: str, vectordb, embedder, llm):
    """
    Analyze a forked repo, retrieve changed rust files since fork point, and compute semantic change groups for each file.
    """
    import tempfile
    import subprocess
    result = {}
    changed_rust_files, upstream_branch,fork_point = get_rust_files(repo_path)
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
                content = get_original_file_content_with_upstream_branch(repo_path, upstream_branch, rust_file)
                if content is None:
                    print(f"Skipping {rust_file}: could not retrieve original content.")
                    continue
                f.write(content)
        diff_text = get_git_diff(tmp_upstream_path, file_path)
        if diff_text.strip() == "":
            os.remove(tmp_upstream_path)
            continue
        
        # copy rust_file to temp_file
        rust_file_content = open(file_path).read()
        try:
            code = rag_guided_code_modification(open(tmp_upstream_path).read(),repo_path, rust_file, vectordb, embedder, llm)
        except Exception as e:
            print(f"Failed to modify {rust_file}: {e}")
            os.remove(tmp_upstream_path)
        # write back to original file
        with open(file_path, 'w') as f:
            f.write(rust_file_content)
            
    return result

def rag_guided_code_modification(rust_code, repo_path, rel_file, vectordb, embedder, llm, depth=0):
    # generate_code(rust_code, repo_path, rel_file, vectordb, embedder, llm, depth)
    generate_hunk(rust_code, repo_path, rel_file, vectordb, embedder, llm, depth)

# set recusive call depth limit
def generate_code(rust_code, repo_path, rel_file, vectordb, embedder, llm, depth=0):
    if depth > 1:
        print("Maximum recursion depth reached, stopping further modifications.")
        raise RuntimeError("Maximum recursion depth reached")

    # write rust_code to rel_file with suffix depth 
    rel_file_with_depth = f"{rel_file}.mod_depth_{depth}"
    with open(os.path.join(repo_path, rel_file_with_depth), 'w') as f:
        f.write(rust_code)
        
 
    # 0. Copy rust_code to rel_file and compile to get errors
    with open(os.path.join(repo_path, rel_file), 'w') as f:
        f.write(rust_code)
    try:
        xargo_compile_sgx_project(os.path.dirname(repo_path), os.path.basename(repo_path))
        print(f"xargo build success for {rel_file}!")
        cargo_compile_sgx_project(os.path.dirname(repo_path), os.path.basename(repo_path))
        print(f"cargo build success for {rel_file}!")
        return rust_code  # Compilation successful, return original code
    except Exception as e:
        print(f"build failed for {rel_file}: {e}")
        # Assume error output is in e.args[0], adjust as needed
        error_text = str(e)

 
        # 1. Retrieve relevant knowledge
        context_docs = []
        docs = vectordb.similarity_search(error_text, k=4)
        context_docs.extend(docs)
        
        # 2. Build prompt
        context_text = '\n\n'.join(["[Compilation error]:"+d.page_content + "\n" + "[Code Modification]:"+get_hunk_from_metadata(d.metadata) for d in context_docs])
       
        prompt = prompt_code_gen.format(rust_code=rust_code, error_text=error_text, context_text=context_text)
        # 3. LLM generation
        try:
            result = llm(prompt)
            return rag_guided_code_modification(rust_code=result, repo_path=repo_path, rel_file=rel_file, vectordb=vectordb, embedder=embedder, llm=llm, depth=depth+1)  # Recursive call to verify new code
        except Exception as e:
            print(f"LLM failed to generate code modification: {e}")
            raise RuntimeError("LLM generation failed")


# set recusive call depth limit
def generate_hunk(rust_code, repo_path, rel_file, vectordb, embedder, llm, depth=0):
   
    # write rust_code to rel_file with suffix depth 
    rel_file_with_depth = f"{rel_file}.mod_depth_{depth}"
    with open(os.path.join(repo_path, rel_file_with_depth), 'w') as f:
        f.write(rust_code)
    
    if depth > 2:
        print("Maximum recursion depth reached, stopping further modifications.")
        raise RuntimeError("Maximum recursion depth reached")
    
 
    # 0. Copy rust_code to rel_file and compile to get errors
    with open(os.path.join(repo_path, rel_file), 'w') as f:
        f.write(rust_code)
    try:
        xargo_compile_sgx_project(os.path.dirname(repo_path), os.path.basename(repo_path))
        print(f"xargo build success for {rel_file}!")
        cargo_compile_sgx_project(os.path.dirname(repo_path), os.path.basename(repo_path))
        print(f"cargo build success for {rel_file}!")
        return rust_code  # Compilation successful, return original code
    except Exception as e:
        print(f"build failed for {rel_file}: {e}")
        # Assume error output is in e.args[0], adjust as needed
        error_text = remove_ansi_colors(str(e))

 
        # 1. Retrieve relevant knowledge
        context_docs = []
        docs = vectordb.similarity_search(error_text, k=1, threshold=0.7)
        context_docs.extend(docs)
        
        # 2. Build prompt
        # context_text = '\n\n'.join(["[Compilation error]:\n```\n"+d.page_content + "\n```\n" + "[Corresponding Code Modification]:\n```\n"+get_hunk_from_metadata(d.metadata) + "\n```\n" for d in context_docs])
        assert len(context_docs) >= 1, "No context docs found"
        context_text = []
        for index, doc in enumerate(context_docs):
            reference_original_code, git_diff = get_reference_example_from_metadata(doc.metadata)
            git_diff_summary = llm.invoke(prompt_git_diff_summary.format(git_diff=git_diff))
            context_text.append(f"Reference#{index}: original Rust code:\n```\n{reference_original_code}\n```\n was migrated into TEE-compatible code by the changes:\n```\n{git_diff_summary}\n```")
        context_text = '\n\n'.join(context_text)
       
        prompt = prompt_hunk_gen.format(rust_code=rust_code, context_text=context_text)
        # 3. LLM generation
        try:
            result = llm.invoke(prompt)
            if isinstance(result,str):
                result = result.replace("```", "").replace("diff", "").replace("git diff", "").strip()
            elif isinstance(result, AIMessage):
                result = result.content.replace("```", "").replace("diff", "").replace("git diff", "").strip()
                
            print(f"LLM returned hunk:\n{result}")
            hunks = parse_diff_hunks(result)  # Verify it's a valid hunk
            for hunk in hunks:
                rust_code = apply_hunk_on_new_file(hunk, rust_code)
            # save prompt, result, and modified code to a log file
            with open(os.path.join(repo_path, f"{rel_file}.mod_log.txt"), 'a') as logf:
                # write timestamp
                import time
                logf.write(f"=== Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                logf.write(f"=== Depth {depth} ===\n")
                logf.write(f"Rust file path: {rel_file_with_depth}\n")
                
                logf.write("Used expert knowledge:\n{}\n".format(context_text))
                logf.write("=== LLM Result ===\n")
                logf.write("Suggested modification:\n" + result + "\n")
                logf.write(f"modified Rust file path: {rel_file}.mod_depth_{depth+1}\n")
             
            return rag_guided_code_modification(rust_code=rust_code, repo_path=repo_path, rel_file=rel_file, vectordb=vectordb, embedder=embedder, llm=llm, depth=depth+1)  # Recursive call to verify new code
        except Exception as e:
            print(f"LLM failed to generate code modification: {e}")
            raise RuntimeError("LLM generation failed")


def migrate_project_to_tee(project_path, vectordb_path):
        """
        Iteratively compile and fix a Rust library for TEE compatibility using RAG and LLM, until no compiler errors remain.
        """
        # docker-sgx-xargo-create
        subprocess.run(f"bash -i -c 'docker-sgx-xargo-create {os.path.basename(os.path.dirname(project_path))}'", shell=True)
        # docker-sgx-cargo-create
        subprocess.run(f"bash -i -c 'docker-sgx-cargo-create {os.path.basename(os.path.dirname(project_path))}'", shell=True)
    
        # change directory to project_path 
        os.chdir(project_path)
        # git reset --hard to discard any local changes
        subprocess.run("git reset --hard", shell=True, cwd=project_path)
        
        # Load vector DB and LLM
        embedder = OllamaEmbeddings(model="nomic-embed-text", base_url="http://localhost:11434")
        vectordb = FAISS.load_local(vectordb_path, embedder, allow_dangerous_deserialization=True)
        # llm = Ollama(model="qwen2.5:32b", base_url="http://localhost:11434")
        llm =  qwen3coder_30b
        analyze_forked_repo(project_path, vectordb, embedder, llm)
        
        #docker-sgx-xargo-destroy
        subprocess.run("bash -i -c 'docker-sgx-xargo-destroy'", shell=True)
        #docker-sgx-cargo-destroy
        subprocess.run("bash -i -c 'docker-sgx-cargo-destroy'", shell=True)

	
# Example usage
if __name__ == "__main__":
	# Set your project path, name, and vector DB path here
	project_path = "/workspaces/TEE-Forge-It/forked_repo/anyhow-sgx"
	vectordb_path = "/workspaces/TEE-Forge-It/changes/compiler_error_faiss_db"
	migrate_project_to_tee(project_path, vectordb_path)
