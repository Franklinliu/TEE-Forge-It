from langchain_core.runnables import RunnableLambda
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.schema import Document
from langchain.chains import create_retrieval_chain
from langchain_core.documents import Document
import os
from langchain.vectorstores import FAISS
from langchain.embeddings import OllamaEmbeddings
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.llms import Ollama
from typing import List, Tuple

from langchain_openai import ChatOpenAI
from extract_code_change import get_upstream_branch, get_fork_point
import subprocess
import random


# Step 1: Embedding Rust code files and mapping to code changes
def embed_rust_files(repo_dirs: str, code_change_dir: str, vectordb_path: str) -> None:
    """
    Embed Rust code files and store them in a vector database, while maintaining a mapping
    between Rust files and their corresponding code change files.

    Args:
        repo_dirs (str): Directory containing Rust code files.
        code_change_dir (str): Directory containing pre-calculated code change files.
        vectordb_path (str): Path to store the vector database.
    """
    embeddings = OllamaEmbeddings(
        model="nomic-embed-text", base_url="http://localhost:11435")  # Use an open-source embedding model
    documents = []
    metadata = []

    for repo_path in repo_dirs:
        repo_name = os.path.basename(repo_path)
        if os.path.isdir(repo_path) and os.path.exists(os.path.join(repo_path, ".git")):
            try:
                current_branch = None
                print(f"Processing repository: {repo_name}")

                # Get the upstream branch and fork point
                upstream_branch = get_upstream_branch(repo_path)
                fork_point = get_fork_point(repo_path, upstream_branch)

                # Save the current branch
                current_branch = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=repo_path,
                    text=True
                ).strip()

                # Soft checkout to the fork point
                subprocess.check_call(
                    ["git", "checkout", fork_point], cwd=repo_path)
                print(
                    f"Checked out to fork point {fork_point} for repository {repo_name}")

                # Process Rust files in the repository
                for root, _, files in os.walk(repo_path):
                    for file in files:
                        if file.endswith(".rs"):
                            rust_file_path = os.path.join(root, file)
                            with open(rust_file_path, "r") as f:
                                rust_code = f.read()[:15000]
                                # Add the Rust code and metadata
                                if os.path.exists(os.path.join(code_change_dir, f"{repo_name}_changes.txt")):
                                    code_changes = open(os.path.join(
                                        code_change_dir, f"{repo_name}_changes.txt"), "r").read()
                                    code_changes = list(filter(lambda code_change: code_change.find(os.path.basename(rust_file_path)) != -1,
                                                               code_changes.split("================================================================================")))

                                    if len(code_changes) > 0:
                                        documents.append(rust_code)
                                        metadata.append({
                                            "repo_name": repo_name,
                                            "file_path": rust_file_path,
                                            "code_change_file": os.path.join(code_change_dir, f"{repo_name}_changes.txt")
                                        })

            except Exception as e:
                pass
            finally:
                if current_branch is not None:
                    # Checkout back to the original branch
                    subprocess.check_call(
                        ["git", "checkout", current_branch], cwd=repo_path)
                    print(
                        f"Checked back to branch {current_branch} for repository {repo_name}")

    print(f"Embedding {len(documents)} Rust files...")
    # Create and save the vector database
    vectordb = FAISS.from_texts(documents, embeddings, metadatas=metadata)
    vectordb.save_local(vectordb_path)
    print(f"Vector database saved at {vectordb_path}")

# Step 2: Search for similar Rust files and fetch relevant code changes


def fetch_similar_code_and_changes(vectordb: object, new_rust_file: str, top_k: int = 3) -> List[Tuple[str, str]]:
    """
    Search for the most similar Rust files and fetch their relevant code changes.

    Args:
        vectordb (str): the vector database.
        new_rust_file (str): Path to the new Rust code file.
        top_k (int): Number of similar files to retrieve.

    Returns:
        List[Tuple[str, str]]: A list of tuples containing similar Rust code and their code changes.
    """
    # # Allow dangerous deserialization since the vector database is trusted
    # vectordb = FAISS.load_local(vectordb_path, OllamaEmbeddings(model="nomic-embed-text"), allow_dangerous_deserialization=True)

    print(f"Loading new Rust file: {new_rust_file}")
    with open(new_rust_file, "r") as f:
        new_rust_code = f.read()[:15000]

    # Perform similarity search
    results = vectordb.similarity_search(new_rust_code, k=top_k)

    similar_code_and_changes = []
    for result in results:
        # print(result)
        rust_code = result.page_content
        code_change_file = result.metadata["code_change_file"]
        matched_code_file = result.metadata["file_path"]
        with open(code_change_file, "r") as f:
            code_changes = f.read()

        code_changes = list(filter(lambda code_change: code_change.find(os.path.basename(matched_code_file)) != -1,
                                   code_changes.split("================================================================================")))
        if len(code_changes) > 0:
            code_changes = "\n".join(code_changes)
        else:
            code_changes = "No relevant code changes found."

        similar_code_and_changes.append((rust_code, code_changes))

    return similar_code_and_changes


def create_my_retriever_function(vectordb_path):
    vectordb = FAISS.load_local(vectordb_path, OllamaEmbeddings(
        model="nomic-embed-text", base_url="http://localhost:11435"), allow_dangerous_deserialization=True)

    def my_retriever_function(query):
        query_file = query["input"]
        print(f"Querying vector database for: {query_file}")
        # Replace with your specific retrieval logic
        similar_code_and_changes = fetch_similar_code_and_changes(
            vectordb, query["input"], top_k=1)
        reference_context = "\n\n".join(
            f"Similar Rust Code:\n{code[:15000]}...\n\nReference Code Changes:\n{changes}"
            for code, changes in similar_code_and_changes
        )
        print(f"Reference context:\n {reference_context}\n")
        # return reference_context
        # Return the reference context wrapped in a Document object
        # Return the reference context wrapped in a Document object
        return [Document(page_content=reference_context)]

    return my_retriever_function

# custom_retriever = RunnableLambda(my_retriever_function)


# Step 3: Generate revision recommendations


def generate_revision(new_rust_file: str, custom_retriever: RunnableLambda) -> str:
    """
    Generate revision recommendations for the new Rust code file using reference code changes.

    Args:
        new_rust_file (str): Path to the new Rust code file.
        similar_code_and_changes (List[Tuple[str, str]]): Similar Rust code and their code changes.

    Returns:
        str: The revised Rust code.
    """
    with open(new_rust_file, "r") as f:
        # Limit to 1000 characters for the prompt
        new_rust_code = f.read()[:15000]

    # Define the prompt template
    prompt_template = PromptTemplate.from_template(
        "You are an expert Rust developer. Now we are working on migrating Rust library code to make it compatible for Rust-SGX SDK. Based on the following reference context:\n{context}\n\n "
        "Please recommend code revision/addition/removal for the given Rust code file {input}\n,"
        "having code: \n{new_rust_code}\n\n"
        "MUST output only code revisions/additions/removals in pure text format like those of 'git diff' on file versions. Do not include any explanation in the output. The generated code revisions/additions/removals MUST be given after the annotation 'CODE MIGRATION:'\n"
    )

    # Initialize the LLM using Ollama's qwen2.5:32b model
    llm = ChatOpenAI(
        model="Qwen3-coder:30b", 
        api_key="hanruidong95",
        base_url="http://10.193.104.96:30000/v1",
        temperature=0.7
    )

    combine_docs_chain = create_stuff_documents_chain(
        llm, prompt_template
    )
    # Create the retrieval chain
    chain = create_retrieval_chain(
        retriever=custom_retriever,
        combine_docs_chain=combine_docs_chain
    )

    # Generate the revised Rust code
    revised_code = chain.invoke(
        {"input": new_rust_file, "new_rust_code": new_rust_code})
    return revised_code["answer"]


if __name__ == "__main__":
    # Paths and configurations
    base_dir = "/workspaces/TEE-Forge-It/forked_repo"
    code_change_dir = "/workspaces/TEE-Forge-It/automerge/sgx-world/extracted_changes"
    vectordb_path = "/workspaces/TEE-Forge-It/automerge/sgx-world/vectordb"

    # Split repositories into training (70%) and testing (30%)
    all_repos = [os.path.join(base_dir, repo) for repo in os.listdir(
        base_dir) if os.path.isdir(os.path.join(base_dir, repo))]
    # all_repos = all_repos[:20]  # Limit to 10 repositories for testing
    random.shuffle(all_repos)
    split_index = int(0.7 * len(all_repos))
    training_repos = all_repos[:split_index]
    testing_repos = all_repos[split_index:]

    print(f"Training repositories: {len(training_repos)}")
    print("List of training repositories:")
    for repo in training_repos:
        print(repo)
    print(f"Testing repositories: {len(testing_repos)}")
    print("List of testing repositories:")
    for repo in testing_repos:
        print(repo)

    # Step 1: Embed Rust files and map to code changes (training set)
    embed_rust_files(training_repos, code_change_dir, vectordb_path)

    # Step 2: Test the RAG approach (testing set)
    retriever_function = create_my_retriever_function(vectordb_path)
    for repo_path in testing_repos:
        if os.path.isdir(repo_path) and os.path.exists(os.path.join(repo_path, ".git")):
            repo_name = os.path.basename(repo_path)

            if not os.path.exists(os.path.join(code_change_dir, f"{repo_name}_changes.txt")):
                continue
            try:
                current_branch = None
                print(f"Testing repository: {repo_name}")
                # Get the upstream branch and fork point
                upstream_branch = get_upstream_branch(repo_path)
                fork_point = get_fork_point(repo_path, upstream_branch)

                # Save the current branch
                current_branch = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=repo_path,
                    text=True
                ).strip()

                # Soft checkout to the fork point
                subprocess.check_call(
                    ["git", "checkout", fork_point], cwd=repo_path)
                print(
                    f"Checked out to fork point {fork_point} for repository {repo_name}")

                # Process Rust files in the testing repository
                for root, _, files in os.walk(repo_path):
                    for file in files:
                        if file.endswith(".rs"):
                            rust_file_path = os.path.join(root, file)
                            print(f"Testing Rust file: {rust_file_path}")
                            revised_code = generate_revision(
                                rust_file_path, RunnableLambda(retriever_function))
                            print(
                                f"Recommended Code Changes for {rust_file_path}:\n{revised_code}")
            except Exception as e:
                pass
            finally:
                if current_branch is not None:
                    # Checkout back to the original branch
                    subprocess.check_call(
                        ["git", "checkout", current_branch], cwd=repo_path)
                    print(
                        f"Checked back to branch {current_branch} for repository {repo_name}")
