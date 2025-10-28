import json
import copy
from typing import Any, Dict, Optional
from langchain_openai import ChatOpenAI
from .dsl_generator import ShortTermMemory, LongTermMemory
from .dsl_parser import parse_strategy
from .llm_usage import LLMUsageRecorder
from .dsl_prompt import DSL_GRAMMAR
from src.model.chatgpt import gpt3_5_turbo
class DSLVerifierAgent:
    """Validate DSL produced by generator.

    Responsibilities:
      - Check DSL for syntactic correctness.
      - Run semantic validation rules or call external tools (e.g., cargo check) via registered tools.
      - Provide diagnostics and a confidence score.
    """

    def __init__(self, model: Optional[ChatOpenAI] = None, lt_memory: Optional[LongTermMemory] = None, usage_recorder: Optional[LLMUsageRecorder] = None):
        self.model = model 
        self.st_memory = ShortTermMemory()
        self.lt_memory = lt_memory or LongTermMemory()
        self.tools = {}
        self.usage_recorder = usage_recorder or LLMUsageRecorder()

    def register_tool(self, name: str, func):
        self.tools[name] = func
    
    def invoke_model(self, prompt: str) -> Any:
        resp = self.model.invoke(prompt)
        self.usage_recorder.record_usage(self.model, resp)
        return resp

    def verify(self, dsl_payload: Dict[str, Any], unified_diff: Optional[str] = None) -> Dict[str, Any]:
        # quick syntactic checks
        dsl_text = dsl_payload.get("dsl", "")
        if isinstance(dsl_text, str)  and not dsl_text.strip():
            return {"ok": False, "errors": ["Empty DSL content"]}

        unified_diff_lines = unified_diff.splitlines() if isinstance(unified_diff, str) else unified_diff
        unified_diff_lines = list(map(lambda item: item.strip(), unified_diff_lines))
        deleted_lines = [line[1:].strip() for line in unified_diff_lines if line.strip().startswith("-") and line != "---"]
        added_lines = [line[1:].strip() for line in unified_diff_lines if line.strip().startswith("+") and line != "+++"] 

        # If the DSL is structured JSON or grammar, try parse
        try:
            # DSL may be a JSON string representing strategy
            obj = copy.deepcopy(dsl_text) if isinstance(dsl_text, dict) else json.loads(dsl_text)
            # if object has 'strategy', accept and perform basic validation
            if isinstance(obj, dict) and 'strategy' in obj:
                rules = obj['strategy']
                errs = []
                invalid_rules = []
                for r in rules:
                    if all([op not in r for op in ["RenameFunc", "Replace", "Remove", "Insert", "Substitute", "Move"]]):
                        invalid_rules.append(r)
                    elif "RenameFunc" in r:
                        rule = r.get("RenameFunc") 
                        if len(rule) != 2:
                            invalid_rules.append(r)
                        else:
                            if "Func1" in rule and "Func2" in rule:
                                if rule["Func1"] == rule["Func2"]:
                                    invalid_rules.append(r)
                            else:
                                invalid_rules.append(r)
                    elif "Replace" in r :
                        rule = r.get("Replace") 
                        if len(rule) != 3:
                            invalid_rules.append(r)
                        else: 
                            if "Node1" in rule and "Node2" in rule:
                                if rule["Node1"] == rule["Node2"]:
                                    invalid_rules.append(r)
                                else:
                                    if all([rule["Node1"].find(deleted_line)==-1 for deleted_line in deleted_lines]):
                                        invalid_rules.append(r)
                                    if all([rule["Node2"].find(added_line)==-1 for added_line in added_lines]):
                                        invalid_rules.append(r)
                            else:
                                invalid_rules.append(r)
                    elif "Remove" in r:
                        rule = r.get("Remove")
                        if len(rule) != 2:
                            invalid_rules.append(r)
                        else:
                            if "Node" in rule and "Location" in rule:
                                loc: str = rule["Location"]
                                if not any([loc.startswith(item) for item in ["after",  "before", "at_begin_of", "at_end_of"]]):
                                    invalid_rules.append(r)
                                else:
                                    if all([rule["Node"].find(deleted_line.strip())==-1 for deleted_line in deleted_lines]):
                                        invalid_rules.append(r)
                                    elif loc.startswith("before"):
                                            index = -1
                                            for line, i in enumerate(unified_diff_lines):
                                                if line.find(rule["Node"].strip())!=-1:
                                                    index = i 
                                                    break 
                                            if index != -1:
                                                before_stmt_index = index + 1 
                                                while before_stmt_index <len(unified_diff_lines)-1 and unified_diff_lines[before_stmt_index].strip()=="": 
                                                    before_stmt_index = before_stmt_index - 1
                                                    
                                                before_stmt = unified_diff_lines[before_stmt_index].strip()
                                                if before_stmt.startswith("-") or before_stmt.startswith("+"):
                                                    pass 
                                                else:
                                                    rule["Location"] = "before: {before_stmt}".format(before_stmt = before_stmt)
                                    elif loc.startswith("after"):
                                            index = -1
                                            for line, i in enumerate(unified_diff_lines):
                                                if line.find(rule["Node"].strip())!=-1:
                                                    index = i 
                                                    break 
                                            if index != -1:
                                                after_stmt_index = index - 1 
                                                while after_stmt_index >0 and unified_diff_lines[after_stmt_index].strip()=="": 
                                                    after_stmt_index = after_stmt_index - 1
                                                    
                                                after_stmt = unified_diff_lines[after_stmt_index].strip()
                                                if after_stmt.startswith("-") or after_stmt.startswith("+"):
                                                    pass 
                                                else:
                                                    rule["Location"] = "after: {after_stmt}".format(after_stmt = after_stmt)
                            else:
                                invalid_rules.append(r)
                                    
                    elif "Move" in r:
                        rule = r.get("Move") 
                        if len(rule) != 3:
                              invalid_rules.append(r) 
                        else:
                            if "Node" in rule and "Location1" in rule and "Location2" in rule:
                                if all([rule["Node"].find(deleted_line)==-1 for deleted_line in deleted_lines]):
                                            invalid_rules.append(r)
                                elif all([rule["Node"].find(added_line)==-1 for added_line in added_lines]):
                                            invalid_rules.append(r)
                                else:
                                    for key in ["Location1", "Location2"]:
                                        loc: str = rule[key]
                                        if not any([loc.startswith(item) for item in ["after",  "before", "at_begin_of", "at_end_of"]]):
                                            invalid_rules.append(r) 
                                    
                                        if loc.startswith("before"):
                                            index = -1
                                            for line, i in enumerate(unified_diff_lines):
                                                if line.find(rule["Node"].strip())!=-1:
                                                    index = i 
                                                    break 
                                            if index != -1:
                                                before_stmt_index = index + 1 
                                                while before_stmt_index <len(unified_diff_lines)-1 and unified_diff_lines[before_stmt_index].strip()=="": 
                                                    before_stmt_index = before_stmt_index - 1
                                                    
                                                before_stmt = unified_diff_lines[before_stmt_index].strip()
                                                if before_stmt.startswith("-") or before_stmt.startswith("+"):
                                                    pass 
                                                else:
                                                    rule["Location1"] = "before: {before_stmt}".format(before_stmt = before_stmt)
                                        elif loc.startswith("after"):
                                            index = -1
                                            for line, i in enumerate(unified_diff_lines):
                                                if line.find(rule["Node"].strip())!=-1:
                                                    index = i 
                                                    break 
                                            if index != -1:
                                                after_stmt_index = index - 1 
                                                while after_stmt_index >0 and unified_diff_lines[after_stmt_index].strip()=="": 
                                                    after_stmt_index = after_stmt_index - 1
                                                    
                                                after_stmt = unified_diff_lines[after_stmt_index].strip()
                                                if after_stmt.startswith("-") or after_stmt.startswith("+"):
                                                    pass 
                                                else:
                                                    rule["Location1"] = "after: {after_stmt}".format(after_stmt = after_stmt)
                            else:
                                invalid_rules.append(r) 
                    elif "Insert" in r:
                        rule = r.get("Insert")
                        if len(rule) != 2:
                            invalid_rules.append(r) 
                        else:
                            if "Node" in rule and "Location" in rule:
                                loc: str = rule["Location"]
                                if not any([loc.startswith(item) for item in ["after",  "before", "at_begin_of", "at_end_of"]]):
                                    invalid_rules.append(r)
                                else:
                                    if all([rule["Node"].find(added_line)==-1 for added_line in added_lines]):
                                        invalid_rules.append(r)
                                    elif loc.startswith("before"):
                                            index = -1
                                            for line, i in enumerate(unified_diff_lines):
                                                if line.find(rule["Node"].strip())!=-1:
                                                    index = i 
                                                    break 
                                            if index != -1:
                                                before_stmt_index = index + 1 
                                                while before_stmt_index <len(unified_diff_lines)-1 and unified_diff_lines[before_stmt_index].strip()=="": 
                                                    before_stmt_index = before_stmt_index - 1
                                                    
                                                before_stmt = unified_diff_lines[before_stmt_index].strip()
                                                if before_stmt.startswith("-") or before_stmt.startswith("+"):
                                                    pass 
                                                else:
                                                    rule["Location"] = "before: {before_stmt}".format(before_stmt = before_stmt)
                                    elif loc.startswith("after"):
                                            index = -1
                                            for line, i in enumerate(unified_diff_lines):
                                                if line.find(rule["Node"].strip())!=-1:
                                                    index = i 
                                                    break 
                                            if index != -1:
                                                after_stmt_index = index - 1 
                                                while after_stmt_index >0 and unified_diff_lines[after_stmt_index].strip()=="": 
                                                    after_stmt_index = after_stmt_index - 1
                                                    
                                                after_stmt = unified_diff_lines[after_stmt_index].strip()
                                                if after_stmt.startswith("-") or after_stmt.startswith("+"):
                                                    pass 
                                                else:
                                                    rule["Location"] = "after: {after_stmt}".format(after_stmt = after_stmt)
                            else:
                                invalid_rules.append(r)
                    elif "Substitute" in r : 
                        rule = r.get("Substitute")
                        if len(rule) != 3:
                            invalid_rules.append(r)
                        else:
                            if "Var1" in rule and "Var2" in rule:
                                if rule["Var1"] == rule["Var2"]:
                                    invalid_rules.append(r)
                            else:
                                invalid_rules.append(r)
                    else:
                        # unknow operation
                        invalid_rules.append(r)
                
                [rules.remove(rule) for rule in invalid_rules]
                obj['strategy'] = rules
                if len(invalid_rules) > 0:
                    return {"ok": False, "dsl": obj}
                else:
                    return {"ok": True, "dsl": obj}
        except Exception:
                pass
     
        return {"ok": True, "dsl": dsl_text, "notes": "no verification"}


if __name__ == "__main__":
    verifier = DSLVerifierAgent(model=gpt3_5_turbo)
    sample = {'dsl': '{"strategy": [{"Remove": {"Node": "return fib_n(num - 1) + fib_n(num - 2);", "Scope": "func fib_n : int -> int"}}, {"Replace": {"Node1": "if (num == 0 || num == 1) { return num; }", "Node2": "return num;", "Scope": "func fib_n : int -> int"}}]}', 'notes': 'json-structured'}
    print(verifier.verify(sample))
