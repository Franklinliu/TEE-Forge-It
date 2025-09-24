import os
import glob
import json
import sys 


# 使用 langchain_community.embeddings.OllamaEmbeddings
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import FAISS

from src.diff.git_util import get_original_file_content, get_git_diff

def get_all_error_texts(changes_dir):
	"""
	遍历所有deltacompile.json，提取所有 cargo_error 和 xargo_error 文本。
	返回 [(project, rel_file, hunk_index, error_type, error_text), ...]
	"""
	error_entries = []
	for json_path in glob.glob(os.path.join(changes_dir, '*.deltacompile.json')):
		project = os.path.basename(json_path).replace('.deltacompile.json', '')
		with open(json_path, 'r') as f:
			data = json.load(f)
		for rel_file, hunks in data.items():
			# 项目级错误
			if isinstance(hunks, dict) and 'error' in hunks:
				error_entries.append((project, rel_file, None, 'project_error', hunks['error']))
			# 逐hunk错误
			if isinstance(hunks, list):
				for hunk_info in hunks:
					for err_type in ['cargo_error', 'xargo_error']:
						if err_type in hunk_info:
							error_entries.append((project, rel_file, hunk_info.get('hunk_index'), err_type, hunk_info[err_type]))
			elif isinstance(hunks, dict):
				for hunk_info in hunks.values():
					if isinstance(hunk_info, list):
						for hi in hunk_info:
							for err_type in ['cargo_error', 'xargo_error']:
								if err_type in hi:
									error_entries.append((project, rel_file, hi.get('hunk_index'), err_type, hi[err_type]))
	return error_entries


def get_embedding_fn():
	return OllamaEmbeddings(model="nomic-embed-text", base_url="http://localhost:11434")


def get_hunk_from_metadata(metadata):
    """
    从 metadata 中提取 hunk 信息
    metadata 结构示例: {"project": "proj1", "file": "src/lib.rs", "hunk_index": 0}
    返回 (rust_code, hunk) 或 (None, None)
    """
    project = metadata.get("project")
    rel_file = metadata.get("file")
    hunk_index = metadata.get("hunk_index")
    if project and rel_file and hunk_index is not None:
        # read /workspaces/TEE-Forge-It/changes/*.deltacompile.json to get the hunk text
        work_dir = "/workspaces/TEE-Forge-It"
        changes_dir = os.path.join(work_dir, "changes")
        json_path = os.path.join(changes_dir, f"{project}.deltacompile.json")
        if os.path.isfile(json_path):
            with open(json_path, 'r') as f:
                data = json.load(f)
            if rel_file in data:
                hunks = data[rel_file]
                # hunks is a list of hunk info dicts
                # we need to find the one with matching hunk_index
                if isinstance(hunks, list):
                    for hunk_info in hunks:
                        if hunk_info.get('hunk_index') == hunk_index:
                            hunk =  hunk_info.get('hunk')
                            rust_code = open(os.path.join(work_dir, "forked_repo", project, rel_file), 'r').read()
                            return rust_code, hunk
                        
    return None, None

def get_reference_example_from_metadata(metadata):
    """
    从 metadata 中提取 hunk 信息
    metadata 结构示例: {"project": "proj1", "file": "src/lib.rs", "hunk_index": 0}
    返回 (rust_code, hunk) 或 (None, None)
    """
    project = metadata.get("project")
    rel_file = metadata.get("file")
    hunk_index = metadata.get("hunk_index")
    if project and rel_file and hunk_index is not None:
        # read /workspaces/TEE-Forge-It/changes/*.deltacompile.json to get the hunk text
        work_dir = "/workspaces/TEE-Forge-It"
        changes_dir = os.path.join(work_dir, "changes")
        json_path = os.path.join(changes_dir, f"{project}.deltacompile.json")
        if os.path.isfile(json_path):
            with open(json_path, 'r') as f:
                data = json.load(f)
            if rel_file in data:
                hunks = data[rel_file]
                # hunks is a list of hunk info dicts
                # we need to find the one with matching hunk_index
                if isinstance(hunks, list):
                    for hunk_info in hunks:
                        if hunk_info.get('hunk_index') == hunk_index:
                            hunk =  hunk_info.get('hunk')
                            rust_code = open(os.path.join(work_dir, "forked_repo", project, rel_file), 'r').read()
                            repo_path = os.path.join(work_dir, "forked_repo", project)
                            original_code = get_original_file_content(repo_path, rel_file)
                            # save original_code to a temp file
                            # save rust_code to a temp file
                            import tempfile
                            with tempfile.NamedTemporaryFile(delete=False) as tmp_original:
                                tmp_original_path = tmp_original.name
                                with open(tmp_original_path, 'w') as f:
                                    f.write(original_code)
                            with tempfile.NamedTemporaryFile(delete=False) as tmp_rust:
                                tmp_rust_path = tmp_rust.name
                                with open(tmp_rust_path, 'w') as f:			
                                    f.write(rust_code)
                            # get git diff between the two temp files
                            diff_text = get_git_diff(tmp_original_path, tmp_rust_path)
                            return original_code, diff_text
                        
    return None, None


def main():
	changes_dir = "/workspaces/TEE-Forge-It/changes"
	error_entries = get_all_error_texts(changes_dir)
	if not error_entries:
		print("No compiler errors found.")
		return
	documents = []
	metadata = []
	embedder = get_embedding_fn()
	for project, rel_file, hunk_index, err_type, error_text in error_entries:
		if not error_text.strip():
			continue
		documents.append(error_text)
		metadata.append({"project": project, "file": rel_file, "hunk_index": hunk_index})
	if not documents:
		print("No error documents to embed.")
		return
	vectordb_path = os.path.join(changes_dir, "compiler_error_faiss_db")
	vectordb = FAISS.from_texts(documents, embedder, metadatas=metadata)
	vectordb.save_local(vectordb_path)
	print(f"Saved {len(documents)} error embeddings to FAISS vector db at {vectordb_path}")

if __name__ == "__main__":
	main()
