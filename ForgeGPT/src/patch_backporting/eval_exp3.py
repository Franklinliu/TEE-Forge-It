import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from .main import main_impl_baseline

vim_neovim_file_path = "/workspaces/TEE-Forge-It/baseline/dataset/PPatHF/Neovim-Vim/vim_neovim_test_all.json"


def run_eval_exp3(max_workers: int = None):
    """Load json_data and run main_impl for each item in parallel using threads.

    Results are collected and written to two files:
      - <input>_exp1_raw_result.json : raw response objects (incrementally updated)
      - <input>_exp1_result.json : formatted generated results (keeps original input order)
    """
    json_data = json.load(open(vim_neovim_file_path))
    total = len(json_data)
    print(f"Loaded {total} items from {vim_neovim_file_path}")
    min_workers = 1
    
    sample_size = total
    json_data = json_data[:sample_size]
   

    raw_results = [None] * total
    gen_results = [None] * total
    output_path = vim_neovim_file_path.replace(".json", "_baselin_exp3_result.json")
    output_raw_path = vim_neovim_file_path.replace(".json", "_baselin_exp3_raw_result.json")

    if max_workers is None:
        cpu = os.cpu_count() or 1
        max_workers = min(min_workers, cpu * 5)

    def worker(i, item):
        """Worker that executes main_impl for a single item and returns a structured dict.

        Returns: {"index": i, "raw": res_or_none, "result": final_result_str}
        """
        print(f"======== Submitting item {i+1}/{total}: {item.get('commit_id_target')} ========")
        func_before_source = item.get('func_before_source')
        func_before_target = item.get('func_before_target')
        func_after_source = item.get('func_after_source')
        func_after_target = item.get('func_after_target')

        try:
            res = main_impl_baseline(
                repo=None,
                pre_transform_code=func_before_source,
                post_transform_code=func_after_source,
                target_code=func_before_target,
                expected_post_transform_target_code=func_after_target,
                dry_run=True,
                log_path="/workspaces/TEE-Forge-It/tmp",
            )
            if isinstance(res, dict) and "patched" in res:
                result = res.get("patched")
                return {"index": i, "raw": res, "result": result}
            else:
                return {"index": i, "raw": res, "result": after_src_code}
        except Exception as e:
            print(f"Error processing item {i+1}: {e}")
            return {"index": i, "raw": {"error": str(e)}, "result": after_src_code}

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
            result = info.get("result")

            # Prepare formatted final result following previous format
            key_str_before_target = "### Function After (neovim):"
            key_str_after_target = "\n###"
            # attempt to fetch original after_src_code for the header; fall back to result
            
            after_src_code = json_data[idx].get('func_after_source', '')
          
            final_result = after_src_code + key_str_before_target + "\n" + result + key_str_after_target + "\n"
            gen_results[idx] = final_result
            raw_results[idx] = raw

            print(f"Completed item {idx+1}/{total}")
            
            # Append raw result (order of completion)
            with open(output_raw_path, 'w') as f:
                json.dump([r for r in raw_results if r is not None], f, indent=4)

            # persist intermediate overall results (preserves original index order)
            with open(output_path, 'w') as f:
                json.dump([r for r in gen_results if r is not None], f, indent=4)

    print(f"Saved raw results to {output_raw_path}")
    print(f"Saved results to {output_path}")
   

if __name__ == "__main__":
    run_eval_exp3()