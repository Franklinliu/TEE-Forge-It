import os 
import json 
import re 
import numpy as np 
from .dsl_transformer import transform_c_code_with_dsl
from .fcu import FunctionCompareUtilities

fcu = FunctionCompareUtilities()

def equivalent_test(src, target):
    src_tokens = fcu.get_cleaned_tokens(src)
    target_tokens = fcu.get_cleaned_tokens(target)
    # print(src_tokens)
    # print("\n")
    # print(target_tokens)
    return np.array_equal(src_tokens, target_tokens)

def preprocessing_nodes(node1, node2):
    node1 = node1.strip()
    node2 = node2.strip()
    if node1.endswith("{"):
        node1 = node1[:-1].strip()
    
    if node2.endswith("{"):
        node2 = node2[:-1].strip()
    
    m1 = re.search(r"(\w+)\s*\((.*)\)$", node1)
    m2 = re.search(r"(\w+)\s*\((.*)\)$", node2)
    # print(node1)
    # print(node2)     
    if m1 is not None and m2 is not None:
        # print(m1.groups())
        # print(m2.groups())
        prefix1, exp1 = m1.groups()
        prefix2, exp2 = m2.groups()
        if prefix1 == prefix2:
            node1 = exp1 
            node2 = exp2
    else:
        # m1 = re.search(r"^\((.*)\)$", node1)
        # m2 = re.search(r"^\((.*)\)$", node2)
        # if m1 is not None and m2 is not None:
        #     exp1 = m1.groups()
        #     exp2 = m2.groups()
        #     node1 = exp1 
        #     node2 = exp2
        pass 
    return node1, node2

def preprocesing_dsl(content):
    dsl = json.loads(content)
    if isinstance(dsl, str):
        content = dsl.replace('(\"','(\\"').replace('\")','\\")').replace("\'", '\"') 
        try:
            dsl = json.loads(content) 
        except: 
            # 1) pull out the action objects inside the strategy array
            inner = re.search(r'\{"strategy"\s*:\s*\[(.*)\]\s*\}$', content).group(1)
            # print(inner)
            
            # split top-level {...} blocks (no nested braces in your format)
            objs = re.findall(r'\{[^{}]*\}', inner)
            

            out = {"strategy": []}

            for o in objs:
                # Which action?
                m_act = re.search(r'"(Replace|Remove|Insert|Move)"\s*:', o)
                if not m_act:
                    continue
                act = m_act.group(1)

                # Replace has 3 payloads: "Replace":"node1","node2","(before|after: ...)"
                if act == "Replace":
                    m = re.search(r'"Replace"\s*:\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"((?:before|after):[^"]*)"', o)
                    if not m:
                        m = re.search(r'"Replace"\s*:\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,"Location"\s*:"((?:before|after):[^"]*)"', o)
                        if not m: 
                            raise ValueError("Replace pattern not found")
                        else:
                            node1, node2, loc = m.groups()
                            
                            out["strategy"].append({
                                "Replace": {"Node1": node1, "Node2": node2, "Location": loc}
                            })
                    else:
                        node1, node2, loc = m.groups()
                        out["strategy"].append({
                            "Replace": {"Node1": node1, "Node2": node2, "Location": loc}
                        })
                elif act == "Move":
                    m = re.search(r'"Move"\s*:\s*"([^"]*)"\s*,\s*((?:before|after):[^"]*)\s*,\s*"((?:before|after):[^"]*)"', o)
                    if not m:
                        raise ValueError("Move pattern not found")
                    node, loc1, loc2 = m.groups()
                    out["strategy"].append({
                        "Move": {"Node": node, "Node2": loc1, "Location": loc2}
                    })

                # Remove / Insert have 2 payloads: "X":"node","(before|after: ...)"
                else:
                    m = re.search(rf'"{act}"\s*:\s*"([^"]*)"\s*,\s*"((?:before|after):[^"]*)"', o)
                    if not m:
                        m = re.search(rf'"{act}"\s*:\s*"([^"]*)"\s*,,"Location"\s*:"((?:before|after):[^"]*)"', o)
                        if not m:
                            raise ValueError(f"{act} pattern not found")
                        else:
                            node, loc = m.groups()
                            out["strategy"].append({
                                act: {"Node": node, "Location": loc}
                            })
                    else:
                        node, loc = m.groups()
                        out["strategy"].append({
                            act: {"Node": node, "Location": loc}
                        })

            dsl = out 
    
    for i, rule in enumerate(dsl.get("strategy", [])):
        if "Replace" in rule:
            if isinstance(rule["Replace"], dict):
                # print(rule)
                node1 = rule["Replace"].get("Node1")
                node2 = rule["Replace"].get("Node2")
                node1, node2 = preprocessing_nodes(node1, node2)
                rule["Replace"].update([("Node1", node1), ("Node2", node2)])
            else:
                if "Replace" in rule and  "with" in rule and "Location" in rule:
                    node1 = rule["Replace"]
                    node2 = rule["with"]
                    loc = rule["Location"]
                    node1, node2 = preprocessing_nodes(node1, node2)
                    dsl.get("strategy")[i] = {
                            "Replace": {"Node1": node1, "Node2": node2, "Location": loc}
                        }
                elif "Replace" in rule and  "Node1" in rule and "Node2" in rule and "Location" in rule:
                    node1 = rule["Node1"]
                    node2 = rule["Node2"]
                    loc = rule["Location"]
                    node1, node2 = preprocessing_nodes(node1, node2)
                    dsl.get("strategy")[i] = {
                            "Replace": {"Node1": node1, "Node2": node2, "Location": loc}
                        }
                elif "Replace" in rule and  "Node2" in rule and "Location" in rule:
                    node1 = rule["Replace"]
                    node2 = rule["Node2"]
                    loc = rule["Location"]
                    node1, node2 = preprocessing_nodes(node1, node2)
                    dsl.get("strategy")[i] = {
                            "Replace": {"Node1": node1, "Node2": node2, "Location": loc}
                        }
                
                elif "Replace" in rule and  "Node1" in rule and "Location" in rule:
                    node1 = rule["Replace"]
                    node2 = rule["Node1"]
                    loc = rule["Location"]
                    node1, node2 = preprocessing_nodes(node1, node2)
                    dsl.get("strategy")[i] = {
                            "Replace": {"Node1": node1, "Node2": node2, "Location": loc}
                        }
            
        elif "Remove" in rule:
            if "Remove" in rule and "Location" in rule:
                # print(rule)
                node = rule["Remove"]
                loc = rule["Location"]
                dsl.get("strategy")[i] = {
                            "Remove": {"Node": node,
                                       "Location": loc}
                        }
            
                
    return dsl 

def batch_test():
    test_dir = "/workspaces/TEE-Forge-It/ForgeGPT/examples/backporting/edit_test"
    correct_results = []
    wrong_results = []
    wrong_format_dsls = []
    for item in os.listdir(test_dir):
        # if item!="4783":
        #     continue
        item_dir = os.path.join(test_dir, item)
        pre_transform = open(os.path.join(item_dir, "pre_tranform.c")).read()
        post_transform = open(os.path.join(item_dir, "post_tranform.c")).read()
        try:
            json_f = open(os.path.join(item_dir, "dsl_edit.json"))
            content = json_f.read()
            dsl = preprocesing_dsl(content)
            assert isinstance(dsl, dict)
            json.dump(dsl, open(os.path.join(item_dir, "dsl_edit.json"), "w"), indent=4)
        except:
            wrong_format_dsls.append(content)
            continue
        
        # print(dsl, type(dsl))
        # preprocesing_dsl(dsl)
        try:
            result = transform_c_code_with_dsl(src= pre_transform.encode(), dsl=dsl)
            open(os.path.join(item_dir, "transformed_auto.c"), "w").write(result.decode())
            if equivalent_test(src=result.decode(), target=post_transform):
                correct_results.append(item)
                open(os.path.join(item_dir, "true.flag"), "w").write("correct!")
            else:
                wrong_results.append(item)
                open(os.path.join(item_dir, "wrong.flag"), "w").write("wrong!")
        except Exception as e:
            # import traceback
            # traceback.print_exc() 
            wrong_results.append(item)
    print("Summary")
    print("Correct results:", len(correct_results))
    print("Wrong result:", len(wrong_results))
    print("Wrong format result:", len(wrong_format_dsls))
    # save checking results
    json.dump({"correct": correct_results, "wrong": wrong_results}, open("dsl_edits_check.json", "w"), indent=4)
    
    open("dsl_wrong_formats.json", "w").write("\n".join(map(str, wrong_format_dsls))) 

batch_test()
        
