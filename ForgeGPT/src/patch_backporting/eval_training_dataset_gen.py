import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from .main import main_impl_training_dataset_gen

vim_neovim_file_path = "/workspaces/TEE-Forge-It/baseline/dataset/PPatHF/Neovim-Vim/finetune.json"


def run_eval_training_dataset_gen(max_workers: int = None):
    """Load json_data and run main_impl for each item in parallel using threads.

    Results are collected and written to two files:
      - <input>_exp1_raw_result.json : raw response objects (incrementally updated)
      - <input>_exp1_result.json : formatted generated results (keeps original input order)
    """
    json_data = json.load(open(vim_neovim_file_path))
    total = len(json_data)
    print(f"Loaded {total} items from {vim_neovim_file_path}")
    min_workers = 50
    
    sample_size = total
    json_data = json_data[:sample_size]
   

    raw_results = [None] * total
    output_raw_path = vim_neovim_file_path.replace(".json", "_training_dataset_gen_raw_result.json")

    if max_workers is None:
        cpu = os.cpu_count() or 1
        max_workers = min(min_workers, cpu * 5)

    def worker(i, item):
        """Worker that executes main_impl for a single item and returns a structured dict.

        Returns: {"index": i, "raw": res_or_none, "result": final_result_str}
        """
        print(f"======== Submitting item {i+1}/{total}: {item.get('commit_id_target')} ========")
        func_before_source = item.get('func_before')
        func_after_source = item.get('func_after')
        commit_hash = item.get("commit_hash")
        try:
            res = main_impl_training_dataset_gen(
                repo=None,
                pre_transform_code=func_before_source,
                post_transform_code=func_after_source,
                log_path="/workspaces/TEE-Forge-It/tmp",
            )
            if isinstance(res, dict) and "generated" in res:
                return {"index": i, "raw": res, "commit_hash": commit_hash}
            else:
                return {"index": i, "raw":  {"error":str(res)}, "commit_hash": commit_hash}
        except Exception as e:
            print(f"Error processing item {i+1}: {e}")
            return {"index": i, "raw": {"error": str(e)}, "commit_hash": commit_hash}

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
    run_eval_training_dataset_gen()