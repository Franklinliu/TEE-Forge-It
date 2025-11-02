import os
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import editdistance
import difflib

from sqlalchemy import true
from .agentic_backport import reverse_engineer_patches, set_model
from .fcu import FunctionCompareUtilities

vim_neovim_file_path = "/workspaces/TEE-Forge-It/baseline/dataset/PPatHF/Neovim-Vim/finetune.json"

fcu = FunctionCompareUtilities()
def run_eval_training_dataset_gen(max_workers: Optional[int] = None, model_name: str = "gpt4o", min_workers: int = 1):
    """Load json_data and run main_impl for each item in parallel using threads.

    Results are collected and written to two files:
      - <input>_exp1_raw_result.json : raw response objects (incrementally updated)
      - <input>_exp1_result.json : formatted generated results (keeps original input order)
    """
    json_data = json.load(open(vim_neovim_file_path))
    total = len(json_data)
    print(f"Loaded {total} items from {vim_neovim_file_path}")
    
    sample_size = 10
    json_data = json_data[:sample_size]
   
    raw_results = [None] * total
    output_raw_path = vim_neovim_file_path.replace(".json", "_agentic_backport_training_dataset_gen_raw_result.json")

    if max_workers is None:
        cpu = os.cpu_count() or 1
        max_workers = min(min_workers, cpu * 5)
    
    set_model(model_name)

    def worker(i, item):
        """Worker that executes main_impl for a single item and returns a structured dict.

        Returns: {"index": i, "raw": res_or_none, "result": final_result_str}
        """
        print(f"======== Submitting item {i+1}/{total}: {item.get('commit_id_target')} ========")
        func_before_source = item.get('func_before')
        func_after_source = item.get('func_after')
        commit_hash = item.get("commit_hash")
        try:
            # Persist in-memory source strings to temporary files and pass paths
            tmp_files = []
            try:
                def _write_temp(content, suffix='.c'):
                    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='w', encoding='utf-8')
                    f.write(content or '')
                    f.flush()
                    f.close()
                    tmp_files.append(f.name)
                    return f.name

                before_patch = _write_temp(func_before_source, suffix='.c')
                after_patch = _write_temp(func_after_source, suffix='.c')
               
                res = reverse_engineer_patches(
                    original_codebase_path=before_patch,
                    patched_codebase_path=after_patch
                )
            finally:
                # cleanup temp files
                for p in tmp_files:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
            if isinstance(res, dict) and "executed" in res:
                return {"index": i, "raw": res, "commit_hash": commit_hash}
            else:
                return {"index": i, "error": True, "commit_hash": commit_hash}
        except Exception as e:
            print(f"Error processing item {i+1}: {e}")
            return {"index": i, "error": True, "commit_hash": commit_hash}

    # Submit all tasks
    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for i, item in enumerate(json_data):
            fut = ex.submit(worker, i, item)
            futures[fut] = i

        # Collect as they complete; write raw_results incrementally, but keep final results ordered
        for fut in as_completed(futures):
            info = fut.result()
            idx = info["index"]
            raw = info.get("raw")
            raw["commit_hash"] = info.get("commit_hash")
            
            raw_results[idx] = raw

            print(f"Completed item {idx+1}/{total}")
            
            # Append raw result (order of completion)
            with open(output_raw_path, 'w') as f:
                json.dump([r for r in raw_results if r is not None], f, indent=4)

    print(f"Saved raw results to {output_raw_path}")
   

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="gpt4o", help="Model to use for evaluation. Options: gpt4o, gpt4o_mini, qwen3coder_30b")
    parser.add_argument("--max_workers", type=int, default=1, help="Maximum number of workers to use")

    args = parser.parse_args()
    run_eval_training_dataset_gen(model_name=args.model, min_workers=args.max_workers)