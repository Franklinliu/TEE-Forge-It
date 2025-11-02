import os
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import trace
from typing import Optional
import editdistance
import difflib
import logging 

from numpy import save
from .agentic_backport import patch_backport, setup_logging
from .fcu import FunctionCompareUtilities
vim_neovim_file_path = "/workspaces/TEE-Forge-It/baseline/dataset/PPatHF/Neovim-Vim/vim_neovim_test_all.json"


mylogger: logging.Logger = setup_logging(os.path.dirname(vim_neovim_file_path))

fcu = FunctionCompareUtilities()
def run_eval(max_workers: Optional[int] = None, model_name: str = "gpt4o", min_workers: int = 1, sample_size: Optional[int] = None, case_id: Optional[int] = None, restore_eval: bool = True ):
    """Load json_data and run main_impl for each item in parallel using threads.

    Results are collected and written to two files:
      - <input>_exp1_raw_result.json : raw response objects (incrementally updated)
      - <input>_exp1_result.json : formatted generated results (keeps original input order)
    """
    json_data = json.load(open(vim_neovim_file_path))
    
    min_workers = min_workers
    
    total = len(json_data)
    mylogger.debug(f"Loaded {total} items from {vim_neovim_file_path}")
    if sample_size is None:
        sample_size = total
    if case_id is not None:
        json_data = [json_data[case_id]]
    else:
        json_data = json_data[:sample_size]
    
    raw_results = [None] * total
    gen_results = [None] * total
    output_path = vim_neovim_file_path.replace(".json", "_" + model_name + "_agentic_backport_result.txt")
    output_raw_path = vim_neovim_file_path.replace(".json", "_" + model_name +  "_agentic_backport_raw_result.json")
    
    saved_results: list = []
    if os.path.exists(output_raw_path):
        saved_results = json.load(open(output_raw_path))

    if max_workers is None:
        cpu = os.cpu_count() or 1
        max_workers = min(min_workers, cpu * 5)

    def worker(i, item):
        """Worker that executes main_impl for a single item and returns a structured dict.

        Returns: {"index": i, "raw": res_or_none, "result": final_result_str}
        """
        mylogger.debug(f"======== Submitting item {i+1}/{total}: {item.get('commit_id_target')} ========")
        func_before_source = item.get('func_before_source')
        func_before_target = item.get('func_before_target')
        func_after_source = item.get('func_after_source')
        func_after_target = item.get('func_after_target')
        
        try:
            if restore_eval:
                matched_results = list(filter(lambda x: "vim_code" in x and x.get("vim_code").strip() == func_before_source.strip() and "neovim_code" in x and x.get("neovim_code").strip() == func_before_target.strip(), saved_results))
                if len(matched_results) > 0:
                    mylogger.debug(f"Found cached result for item {i+1}.")
                    saved_res = matched_results[0]
                    patched_result = saved_res.get("patched")
                    return {"index": i, "raw": saved_res, "result": patched_result}
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

                vim_before_path = _write_temp(func_before_source, suffix='.c')
                vim_after_path = _write_temp(func_after_source, suffix='.c')
                neovim_before_path = _write_temp(func_before_target, suffix='.c')

                res = patch_backport(
                    original_vim_codebase_path=vim_before_path,
                    patched_vim_codebase_path=vim_after_path,
                    original_neovim_codebase_path=neovim_before_path,
                    model_name=model_name,
                )
            finally:
                # cleanup temp files
                for p in tmp_files:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
            if isinstance(res, dict) and "patched" in res:
                result = res.get("patched", "")
                expected_tokens = fcu.get_cleaned_tokens(func_after_target)
                patched_tokens = fcu.get_cleaned_tokens(result)
                distance = editdistance.eval(expected_tokens, patched_tokens)
                similarity = 1 - distance / max(len(expected_tokens), len(patched_tokens))
                exact_match = distance == 0
                res["similarity"] = similarity
                res["exact_match"] = exact_match
                res["vim_code"] = func_before_source
                res["neovim_code"] = func_before_target
                res["commit_id_target"] = item.get('commit_id_target')
                
                return {"index": i, "raw": res, "result": result}
            else:
                return {"index": i, "raw": res, "result": func_before_target}
        except Exception as e:
            import traceback
            traceback.print_exc()
            mylogger.debug(f"Error processing item {i+1}: {e}")
            exit(-1)
            # return {"index": i, "raw": {"error": str(e)}, "result": func_before_target}

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
            key_str_before_diff = "### Diff:"
            key_str_before_target = "### Function After (neovim):"
            key_str_after_target = "\n###"
            # attempt to fetch original after_src_code for the header; fall back to result
            
            func_after_target:str = json_data[idx].get('func_after_target', '')
            
            diff = difflib.unified_diff(a=func_after_target.splitlines(), b = result.splitlines(), fromfile="groundtruth", tofile="generation")
            diff_text = "\n".join(diff)
          
            final_result = key_str_before_target + "\n" + func_after_target + "\n" +  key_str_after_target + "\n" + key_str_before_target + "(Generation) \n" + result + key_str_after_target + "\n" + key_str_before_diff + "\n" + diff_text + "\n" + key_str_before_target
            gen_results[idx] = final_result
            raw_results[idx] = raw

            mylogger.debug(f"Completed item {idx+1}/{total}")
            
            # Append raw result (order of completion)
            with open(output_raw_path, 'w') as f:
                json.dump([r for r in raw_results if r is not None], f, indent=4)

            # persist intermediate overall results (preserves original index order)
            with open(output_path, 'w') as f:
                # json.dump([r for r in gen_results if r is not None], f, indent=4)
                f.write("\n".join([r for r in gen_results if r is not None]))

    mylogger.debug(f"Saved raw results to {output_raw_path}")
    mylogger.debug(f"Saved results to {output_path}")
   

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="gpt4o", help="Model to use for evaluation. Options: gpt4o, gpt4o_mini, qwen3coder_30b")
    parser.add_argument("--max_workers", type=int, default=1, help="Maximum number of workers to use")
    parser.add_argument("--sample_size", type=int, default=None, help="Sample size to use for evaluation")
    parser.add_argument("--case_id", type=int, default=None, help="Specific case id for evaluation")
    # add a switch to control whether run the evaluation from the scratch.
    parser.add_argument("--restore_eval", action="store_true", default=False)
    
    args = parser.parse_args()
    run_eval(model_name=args.model, min_workers=args.max_workers, sample_size=args.sample_size, case_id=args.case_id, restore_eval=args.restore_eval)