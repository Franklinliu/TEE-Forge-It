import json 
import os 
import difflib 

data = "/workspaces/TEE-Forge-It/baseline/dataset/PPatHF/Neovim-Vim/finetune_training_dataset_gen_raw_result.json"
output_dir = "/workspaces/TEE-Forge-It/ForgeGPT/examples/backporting/edit_test"
items = json.load(open(data))

for i, item in enumerate(items):
    passed = item["passed"]
    output_item_dir = os.path.join(output_dir, str(i))
    
    if passed:
        pre_transform = item["pre_transfrom"]
        post_tranform = item["post_transform"]
        dsl_edit = item["generated"].get("dsl")
        
        unified_diff = difflib.unified_diff(a = pre_transform.splitlines(), b=post_tranform.splitlines(), fromfile="pre_transform.c", tofile="post_transform.c", lineterm="")
        if not os.path.exists(output_item_dir):
            os.mkdir(output_item_dir)
        
        with open(os.path.join(output_item_dir, "pre_tranform.c"), "w") as f:
            f.write(pre_transform)
            
        with open(os.path.join(output_item_dir, "post_tranform.c"), "w") as f:
            f.write(post_tranform)
        
        with open(os.path.join(output_item_dir, "diff.txt"), "w") as f:
            f.write("\n".join(unified_diff))
            
        with open(os.path.join(output_item_dir, "dsl_edit.json"), "w") as f:
            json.dump(dsl_edit, f, indent=4)
        