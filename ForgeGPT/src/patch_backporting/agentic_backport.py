# This code is an MVP implementation of decompose and patch backporting using LLMs.
# It may not cover all edge cases and is intended for demonstration purposes only.
from ctypes.wintypes import BOOLEAN
import os 
import json 
import copy 
from typing import Union, List
from venv import create
from git import Optional
import logging
from langchain.tools import tool
from langgraph.prebuilt import create_react_agent

from langchain import hub
from langchain import hub
from langchain.schema import HumanMessage, AIMessage
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, stop_after_attempt, wait_random

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from src.patch_backporting.llm_usage import LLMUsageRecorder

from src.patch_backporting.code_transformer import InsertArgs, RemoveArgs, MoveArgs, ReplaceArgs, IfGuardArgs, IfGuardModArgs, IfGuardSimArgs, RenameArgs
from src.patch_backporting.code_transformer import insert, remove, move, replace, rename, if_guard, ifguard_modify, equivalent_test, get_edit_distance
from src.patch_backporting.code_cutter import trim_code_containing_diff, compute_diff

parser = JsonOutputParser()
fmt = parser.get_format_instructions()

# from src.model.qwen import qwen3coder_30b as model 
# from src.model.chatgpt import gpt4o_mini as model
# from src.model.chatgpt import gpt4o as model 

model = None

def set_model(model_name: str):
    global model
    if model_name == "gpt4o":
        from src.model.chatgpt import gpt4o as selected_model
    elif model_name == "gpt4o_mini":
        from src.model.chatgpt import gpt4o_mini as selected_model
    elif model_name == "qwen3coder_30b":
        from src.model.qwen import qwen3coder_30b as selected_model
    else:
        from src.model.chatgpt import gpt4o as selected_model
    model = selected_model

import json, re

def strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s

def escape_ctrl_in_strings(s: str) -> str:
    """
    Escape raw control chars inside quoted JSON strings.
    Handles \\n, \\t, \\r; leaves already-escaped sequences alone.
    """
    out, in_str, esc = [], False, False
    for ch in s:
        if not in_str:
            out.append(ch)
            if ch == '"': in_str = True
            continue
        # in string:
        if esc:
            out.append(ch); esc = False; continue
        if ch == '\\':
            out.append(ch); esc = True; continue
        if ch == '"':
            out.append(ch); in_str = False; continue
        # control chars need escaping
        code = ord(ch)
        if ch == '\n': out.extend(['\\','n'])
        elif ch == '\t': out.extend(['\\','t'])
        elif ch == '\r': out.extend(['\\','r'])
        elif code < 0x20:
            # generic escape
            out.extend(['\\','u'] + list(f"{code:04x}"))
        else:
            out.append(ch)
    return "".join(out)

def coerce_json(s: str):
    s = strip_code_fences(s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return json.loads(escape_ctrl_in_strings(s))
    
def create_user_messages(prompt: str) -> List[dict]:
    """Create user messages for agent invocation."""
    return [create_user_message(prompt)]

def create_user_message(prompt: str) -> dict:
    """Create user messages for agent invocation."""
    print("[USER]", prompt)
    return {"role": "user", "content": prompt}

def create_assistant_message(prompt: str) -> dict:
    """Create assistant messages for agent invocation."""
    print("[ASSISTANT]", prompt)
    return {"role": "assistant", "content": prompt}

def add_retry_to_tool(tool, max_attempts=3):
    """Wrap a Tool's callable with retry logic."""
    original_func = tool.func

    @retry(stop=stop_after_attempt(max_attempts), wait=wait_random(1, 3))
    def retried_func(*args, **kwargs):
        return original_func(*args, **kwargs)

    tool.func = retried_func
    return tool


def get_text(response: object, llm_usage_recorder: LLMUsageRecorder):
        # extract text content
        if isinstance(response, dict):
            msgs = response.get("messages", []) or []
        elif hasattr(response, "messages"):
            msgs = getattr(response, "messages") or []
        else:
            msgs = []
        
        for msg in msgs:
            if isinstance(msg, AIMessage):
                try:
                    llm_usage_recorder.record_usage(model, msg)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    raise e 

        text = None
        if msgs:
            last = msgs[-1]
            if isinstance(last, dict):
                text = last.get("content") or last.get("text")
            else:
                text = getattr(last, "content", getattr(last, "text", None))
        if text is None:
            text = str(response)
        return text
    
def get_plan(response: object, llm_usage_recorder: LLMUsageRecorder):
    text = get_text(response, llm_usage_recorder)
    # parse plan JSON
    try:  
        json_text = text.replace("<tool_call>", "").strip()
        plan = coerce_json(json_text)
        last_msg = create_assistant_message(json.dumps(plan, indent=2))
        # print("[PLAN] Parsed plan:", json.dumps(plan, indent=2))
    except Exception as e:
        raise Exception(f"[ERROR]Plan should be a JSON array object. Parsing error: {e}")
    return plan, last_msg
       
def get_code(response: object, llm_usage_recorder: LLMUsageRecorder):
    text = get_text(response, llm_usage_recorder)
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.strip().split("\n")[1:-1])
    code = text.strip()
    return code

def preprocess(step):
    tool_name = step.get("tool")
    args = step.get("payload", {})

    if tool_name == "insert_statements_in_codebase":
        statements = args.get("statements")
        if isinstance(statements, str):
            statements = statements.strip()
            if statements == "{" or statements == "}":
                raise Exception(f"[ERROR] Cannot insert `{statements}` because it is not a statement.")
            
            # when the statements is a exp, it will raise Exception
            if not (statements.endswith(";") or statements.endswith("}")):
                raise Exception(f"[ERROR] Cannot insert `{statements}` because it is not a statement.")
            
        else:
            for statement in statements:
                if isinstance(statement, str):
                    statement = statement.strip()
                    if statement == "{" or statement == "}":
                        raise Exception(f"[ERROR] Cannot insert `{statement}` because it is not a statement.")
        return step 
        
    elif tool_name == "remove_statements_from_codebase":
        statements = args.get("statements")
        if isinstance(statements, str):
            statements = statements.strip()
            if statements == "{" or statements == "}":
                raise Exception(f"[ERROR] Cannot remove `{statements}` because it is not a statement.")
            
            # when the statements is a exp, it will raise Exception
            if not (statements.endswith(";") or statements.endswith("}")):
                raise Exception(f"[ERROR] Cannot remove `{statements}` because it is not a statement.")
            
        else:
            for statement in statements:
                if isinstance(statement, str):
                    statement = statement.strip()
                    if statement == "{" or statement == "}":
                        raise Exception(f"[ERROR] Cannot remove `{statement}` because it is not a statement.")
        return step 
    elif tool_name == "replace_statements_in_codebase":
        old_statement = args.get("old_statement")
        new_statement = args.get("new_statement")
        if isinstance(old_statement, list):
            old_statement = "\n".join(old_statement)
        if isinstance(new_statement, list):
            new_statement = "\n".join(new_statement)
        
        old_statement = old_statement.strip()
        new_statement = new_statement.strip()
        
        if old_statement == new_statement:
            raise Exception("[ERROR] Cannot replace the same statement with itself")
        if old_statement.strip().startswith("if") and new_statement.strip().startswith("if"):
            if not old_statement.endswith("}"):
                # write re pattern match to get condition of old if-statement
                import re
                match = re.search(r'if\s*\((.*)\)', old_statement, re.DOTALL)
                old_condition = match.group(1) if match else None
                match = re.search(r'if\s*\((.*)\)', new_statement, re.DOTALL)
                new_condition = match.group(1) if match else None
                print("Attempt to replace: ", old_condition, new_condition)
                if old_condition and new_condition and old_condition.strip() != new_condition.strip():
                    step["tool"] = "ifguard_modify_in_codebase"
                    args["if_statement"] = old_statement
                    args["new_guard"] = new_condition
                    # drop other keys in args
                    args.pop("old_statement", None)
                    args.pop("new_statement", None)
                    args.pop("destination_function", None)
                    args.pop("destination_location_prev_statement", None)
                    args.pop("destination_location_next_statement", None)
                    step["payload"] = args
                    return step  
            
        return step 
    elif tool_name == "move_statements_in_codebase":
        return step
    elif tool_name == "ifguard_statements_in_codebase":
        guard = args.get("guard").strip()
        import re
        match = re.search(r'if\s*\((.*)\)', guard, re.DOTALL)
        guard = match.group(1) if match else guard
        args["guard"] = guard
        step["payload"] = args
        return step
    elif tool_name == "ifguard_modify_in_codebase":
        new_guard = args.get("new_guard").strip()
        import re
        match = re.search(r'if\s*\((.*)\)', new_guard, re.DOTALL)
        new_guard = match.group(1) if match else new_guard
        args["new_guard"] = new_guard
        step["payload"] = args
        return step
    elif tool_name == "ifguard_condition_simplify_in_codebase":
        return step 
    elif tool_name == "rename_in_codebase":
        return step 
    else:
        return step 



def get_user_error_feedback(step: dict):
    # error occurs in tool selection
    # we need to return different error feedback according to different tool selection
    
    tool_name = step.get("tool")
    args = step.get("payload", {})

    if tool_name == "insert_statements_in_codebase":
        return ""
    elif tool_name == "remove_statements_from_codebase":
        return ""
    elif tool_name == "replace_statements_in_codebase":
        if args.get("old_statement") == args.get("new_statement"):
            return "[ERROR] Cannot replace the same statement with itself"
        else:
            old_statement = args.get("old_statement").strip()
            new_statement = args.get("new_statement").strip()
            # when old_statement and new_statement is if-statement
            # consider use ifguard_modify_in_codebase tool
            if old_statement.startswith("if") and new_statement.startswith("if"):
                if not old_statement.endswith("}"):
                    return "[ERROR] Cannot replace if-statement with if-statement. [FIX] MUST Use ifguard_modify_in_codebase tool in the new plan."
                else:
                    return ""
            else:
                return ""
    elif tool_name == "move_statements_in_codebase":
        return ""
    elif tool_name == "ifguard_statements_in_codebase":
        return ""
    elif tool_name == "ifguard_modify_in_codebase":
        return ""
    elif tool_name == "ifguard_condition_simplify_in_codebase":
        return ""
    elif tool_name == "rename_in_codebase":
        return ""
    else:
        return ""


@tool
def read_file(file_path: str) -> str:
    """Read the content of a file and return it as a string."""
    # use subprocess to read file content to avoid encoding issues
    import subprocess
    try:
        result = subprocess.run(['cat', file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error reading file: {e.stderr}"

@tool 
def compute_code_diff(src: str, target: str):
    """Compute the code diff to grasp the changes"""
    code_diff = compute_diff(src, target)
    return code_diff

@tool("insert_statements_in_codebase", args_schema=InsertArgs)
def insert_statements_in_codebase(codebase: str, statements: str, destination_function: str, destination_location_prev_statement:str, destination_location_next_statement: str) -> str:
    """Insert statements into the codebase; return modified code. If a new statement (denoted as X) is added in the patched codebase, USE insert_statements_in_codebase tool. destination_location_prev_statement and destination_location_next_statement MUST refer to declaration/expression/return statements and MUST be provided to indicate the insertion location."""
    
    if isinstance(statements, str):
        statements = statements.strip()
        if statements == "{" or statements == "}":
            return codebase 
    
    destination_location_prev_statement = destination_location_prev_statement.strip().strip("{")
    destination_location_next_statement = destination_location_next_statement.strip().strip("}")
    if destination_location_prev_statement == "" and destination_location_next_statement == "":
        return codebase  # No insertion needed if both locations are empty
    if destination_location_prev_statement == destination_location_next_statement:
        return codebase  # No insertion needed if both locations are the same

    obj = InsertArgs(
        codebase=codebase,
        statements=statements,
        destination_function=destination_function,
        destination_location_prev_statement=destination_location_prev_statement,
        destination_location_next_statement=destination_location_next_statement
    )
    result = insert(obj)
    if isinstance(result, bytes):
        result = result.decode()

    return result


@tool("remove_statements_from_codebase", args_schema=RemoveArgs)
def remove_statements_from_codebase(codebase: str, statements: str, destination_function: str, destination_location_prev_statement:str,  destination_location_next_statement: str) -> str:
    """Remove statements from the codebase; return modified code. ONLY If a statement in the original codebase is removed entirely in its patched version, USE remove_statements_from_codebase tool, where statement MUST be expression statements or if-statement or if-else-statement."""
    if isinstance(statements, str):
        statements = statements.strip()
        if statements == "{" or statements == "}":
            return codebase 
        
    destination_location_prev_statement = destination_location_prev_statement.strip().strip("{")
    destination_location_next_statement = destination_location_next_statement.strip().strip("}")
    if destination_location_prev_statement == "" and destination_location_next_statement == "":
        return codebase  # No insertion needed if both locations are empty
    if destination_location_prev_statement == destination_location_next_statement:
        return codebase  # No insertion needed if both locations are the same
    
    obj = RemoveArgs(
        codebase=codebase,
        statements=statements,
        destination_function=destination_function,
        destination_location_prev_statement=destination_location_prev_statement,
        destination_location_next_statement=destination_location_next_statement
    )
    result = remove(obj)
    if isinstance(result, bytes):
        result = result.decode()

    return result



@tool("move_statements_in_codebase", args_schema=MoveArgs)
def move_statements_in_codebase(codebase: str, statements: str,  destination_function: str, destination_location_prev_statement:str,  destination_location_next_statement: str) -> str:
    """Move statements within the codebase to a new location; return modified code. ONLY If a statement is located at different places in the original and patched codebase respectively, USE move_statements_in_codebase tool, where statement MUST be expression statements, where statement MUST be expression statements or if-statement or if-else-statement.."""
    destination_location_prev_statement = destination_location_prev_statement.strip().strip("{")
    destination_location_next_statement = destination_location_next_statement.strip().strip("}")
    if destination_location_prev_statement == "" and destination_location_next_statement == "":
        return codebase  # No insertion needed if both locations are empty
    if destination_location_prev_statement == destination_location_next_statement:
        return codebase  # No insertion needed if both locations are the same

    obj = MoveArgs(codebase=codebase, statements=statements, 
                   destination_function=destination_function,
                   destination_location_next_statement = destination_location_next_statement,
                   destination_location_prev_statement=destination_location_prev_statement)
    result = move(obj)
    if isinstance(result, bytes):
        result = result.decode()

    return result 


@tool("replace_statements_in_codebase", args_schema=ReplaceArgs)
def replace_statements_in_codebase(codebase: str, old_statement: str, new_statement: str,  destination_function: str, destination_location_prev_statement:str,  destination_location_next_statement: str) -> str:
    """Replace old statements with new statements in the codebase; return modified code. ONLY If a statement (X) in the original codebase is replaced by another statement (Y) in its patched version, USE replace_statements_in_codebase tool. Note this tool only supports one-to-one replacement, where old_statement and new_statement (X and Y) MUST be of the same statement type, e.g., both are expression statements or both are if-statements. Note we CANNOT use this tool to replace a statement with multiple statements or vice versa. We CANNOT use this tool to replace a function definition with another function definition."""
    destination_location_prev_statement = destination_location_prev_statement.strip().strip("{")
    destination_location_next_statement = destination_location_next_statement.strip().strip("}")
    if destination_location_prev_statement == "" and destination_location_next_statement == "":
        return codebase  # No insertion needed if both locations are empty
    if destination_location_prev_statement == destination_location_next_statement:
        return codebase  # No insertion needed if both locations are the same
    
    if old_statement.strip() == new_statement.strip():
        return codebase 
    

    obj = ReplaceArgs(
        codebase=codebase,
        new_statement=new_statement,
        old_statement=old_statement,
        destination_function=destination_function,
        destination_location_next_statement=destination_location_next_statement,
        destination_location_prev_statement = destination_location_prev_statement
    )
    result = replace(obj)
    if isinstance(result, bytes):
        result = result.decode()

    return result 

@tool("rename_in_codebase", args_schema=RenameArgs)
def rename_in_codebase(codebase: str, old_name: str, new_name: str) -> str:
    """Rename an identifier, a variable, an API, or a member field across the codebase; return modified code. The new name must be different from the old name. Names ONLY contain [a-z|A-Z|_] charateristics"""
   
    obj = RenameArgs(
        codebase=codebase,
        old_name=old_name,
        new_name=new_name,
    )
    result = rename(obj)
    if isinstance(result, bytes):
        result = result.decode()

    return result 

@tool("ifguard_statements_in_codebase", args_schema=IfGuardArgs)
def ifguard_statements_in_codebase(codebase: str, statements: str, guard: str) -> str:
    """Sanic check statements with newly-introduced conditions in the codebase; return modified code. ONLY If statements (denoted as X) in the original codebase turn to be inside an if-condition-related statement (denoted as if (...){{X}}) in its patched codebase, USE ifguard_statements_in_codebase tool."""
    
    obj = IfGuardArgs(
        codebase = codebase,
        statements = statements,
        guard = guard 
    )
    
    result = if_guard(obj)
    return result

@tool("ifguard_modify_in_codebase", args_schema=IfGuardModArgs)
def ifguard_modify_in_codebase(codebase: str, if_statement: str, new_guard: str) -> str:
    """Sanic check statements with modified guard conditions in the codebase; return modified code. ONLY If if-statement (denoted as if (X){{...}}) in the original codebase changes to be if (Y){{...}} in its patched codebase (X and Y are different expressions), USE ifguard_modify_in_codebase tool. new_guard MUST be condition expression"""
    
    # preprocess new_guard
    new_guard = new_guard.strip()
    # if new_guard containing code like "...(exp)..."
    # I want to extract exp as the new_guard
    if new_guard.find("if (")!=-1 and new_guard.find(")")!=-1:
        new_guard = new_guard[new_guard.find("if (")+1: new_guard.rfind(")")]
        
    if_statement = if_statement.strip()
    if if_statement.startswith("else"):
        if_statement = if_statement.replace("else", "")
    
    obj = IfGuardModArgs(
        codebase=codebase,
        if_statement=if_statement,
        new_guard=new_guard
    )
    # Call the ifguard_modify_in_codebase tool with the constructed object
    result = ifguard_modify(obj)
    return result

@tool("ifguard_condition_simplify_in_codebase", args_schema=IfGuardSimArgs)
def ifguard_condition_simplify_in_codebase(codebase: str, if_statement: str) -> str:
    """Sanic check statements with simplified guard conditions in the codebase; return modified code. ONLY If if-statement (denoted as `if (X:complex_expression){{...}}`) in the original codebase changes to be a sequence of statements like `bool a; a = X; if (a){{...}}` or `bool a = X; if (a){{...}}` in its patched codebase, USE ifguard_condition_simplify_in_codebase tool."""
    agent = create_normal_agent()
    prompt = (
        "STRICTLY follow the instructions to  "
        "Simplify guard condition in the following if-statements:\n"
        f"{if_statement}\n"
        "in the codebase:\n"
        f"{codebase}\n"
        "following the equivalence transformation pattern:\n"
        "`if (X:complex_expression){{...}}`  ->  `bool a; a = X; if (a){{...}}`  OR  `bool a = X; if (a){{...}}`\n"
        "Please make sure to follow the equivalence transformation pattern strictly and also follow the programming style of the codebase.\n"
        "Output ONLY the modified codebase."
    )
    result = agent.invoke({"messages":create_user_messages(prompt)})
    last_msg = result.get("messages", [])[-1]
    return last_msg.content

def create_normal_agent(tools=[]):
    # create a patch backporting planner agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt = "You are a helpful code editing agent."
    )
    return agent


def create_patching_agent():
    tools = [
        insert_statements_in_codebase,
        remove_statements_from_codebase,
        replace_statements_in_codebase,
        move_statements_in_codebase,
        ifguard_statements_in_codebase,
        ifguard_modify_in_codebase,
        ifguard_condition_simplify_in_codebase,
        rename_in_codebase,
        compute_code_diff
    ]
    tools = [add_retry_to_tool(t) for t in tools]
    prompt = "You are a helpful patch agent."
    # create a patch backporting planner agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt = prompt
    )
    return agent

def create_patch_backporting_agent():
    tools = []
    prompt = "You are a helpful patch backporting agent that will migrate original patches from vim to neovim."
    # create a patch backporting planner agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt = prompt
    )
    return agent

# given an existing codebase and its patched version, reverse engineer the patch steps
def reverse_engineer_patches(original_codebase_path: str, patched_codebase_path: str, llm_usage_recorder: LLMUsageRecorder = LLMUsageRecorder()) -> dict:
    # Plan / Execute / Decision / Replan loop
    max_iterations = 5
    original_code = open(original_codebase_path).read()
    target_code = open(patched_codebase_path).read()
    
    # trim code to only the parts containing diffs

    # helper: map tool name -> callable
    tool_map = {
        "insert_statements_in_codebase": insert_statements_in_codebase,
        "remove_statements_from_codebase": remove_statements_from_codebase,
        "replace_statements_in_codebase": replace_statements_in_codebase,
        "move_statements_in_codebase": move_statements_in_codebase,
        "ifguard_statements_in_codebase": ifguard_statements_in_codebase,
        "ifguard_modify_in_codebase": ifguard_modify_in_codebase,
        "ifguard_condition_simplify_in_codebase": ifguard_condition_simplify_in_codebase,
        "rename_in_codebase": rename_in_codebase
    }

    current_code = original_code
    executed_plan = []
    last_msg = None
    user_error_feedback = None
    planner = create_patching_agent()
    left_prefix = ""
    left_suffix = ""
    right_prefix = ""
    right_suffix = ""
    for iteration in range(max_iterations):
        trimmed = trim_code_containing_diff(current_code, target_code)
        
        left_start_byte: int  = trimmed["left_code"]["start_byte"]
        left_end_byte: int  = trimmed["left_code"]["end_byte"]
        right_start_byte: int  = trimmed["right_code"]["start_byte"]
        right_end_byte: int  = trimmed["right_code"]["end_byte"]
        
        left_prefix += current_code[:left_start_byte]
        left_suffix += current_code[left_end_byte:]
        right_prefix += target_code[:right_start_byte]
        right_suffix += target_code[right_end_byte:]
        
        current_code = trimmed["left_code"]["code"]
        target_code = trimmed["right_code"]["code"]
        
        
        current_edit_distance = get_edit_distance(current_code, target_code)
        # print("Current codebase:\n ", current_code)
        # print("Target codebase:\n", target_code)
        diff_text = compute_diff(current_code, target_code)
        print("Code diff:\n", diff_text)
        print(f"[PLAN] Iteration {iteration+1}: generating plan from current codebase")
        plan_prompt = PromptTemplate(
            template=(
                "You are a patch planning agent. Given the original codebase and its patched codebase,"
                "Follow the tool-selection rules and output only valid patch steps.\n" 
                "Excluding compute_code_diff, the patch steps MUST be defined by the provided tools, and their payloads."
                """
                Instructions:
                0. Compute the text difference between the original codebase and its patched codebase to understand the code changes.
                1. For small changes including insertion/deletion of statements, USE insert_statements_in_codebase, remove_statements_from_codebase tools.
                2. For statements moving from one place to another place in the codebase, USE move_statements_in_codebase tool.
                3. For statement replacement satisfying the pattern: `if (X){{...}})` -> `if (Y){{...}})`, USE ifguard_modify_in_codebase tool.
                4. For statement replacement satisfying the pattern: `X` -> `if (...){{X}})`, USE ifguard_statements_in_codebase tool. 
                5. For statement changes satisfying the pattern: `if (X:complex_expression){{...}}` -> `bool a; a = X; if (a){{...}}` OR `bool a = X; if (a){{...}}`, USE ifguard_condition_simplify_in_codebase tool. 
                
                ### Original codebase:\n`{current}`\n
                ### Patched codebase:\n`{target}`\n
                ### Patch steps: `?`
             
                Output requirements:
                MUST output a sequence of valid patch steps (up to TWO steps) with the following JSON format of array object:
                [{{"tool": <tool_name>, "payload": {{ ... }}}}, ...., {{"tool": <tool_name>, "payload": {{ ... }}}}]
                Make sure the payload fields strictly follow the tool argument names and types.
                """
                "All code content must be valid JSON strings (escape newlines \\n, tabs \\t) "
                "No explanations. No fences."
            ),
            input_variables=["current", "target"],
        )
        raw_prompt = plan_prompt.format(current=current_code, target=target_code)
        # print("[PLAN PROMPT]\n", raw_prompt)
        if user_error_feedback is not None and last_msg is not None:
            error_prompt = f"The previous plan failed. {user_error_feedback}.\n Please generate new plan."
            print("Error prompt: ", error_prompt)
            plan_resp = planner.invoke({"messages": [create_user_message(raw_prompt), last_msg, create_user_message(error_prompt)]}, config={"recursion_limit": 50})
            user_error_feedback = None  # reset after adding to prompt
            last_msg = None # reset last message after using it
        else:
            plan_resp = planner.invoke({"messages": create_user_messages(raw_prompt)}, config={"recursion_limit": 50})
            
        # parse plan JSON
        try:  
            plan, last_msg = get_plan(response=plan_resp, llm_usage_recorder=llm_usage_recorder)
        except Exception as e:
            user_error_feedback = str(e)
            import traceback
            traceback.print_exc()
            continue  # skip to next iteration for replanning
        
        if not isinstance(plan, list):
            user_error_feedback = "[ERROR]Plan should be a JSON array object."
            continue  

        # Execute phase
        any_change: bool = False
        step = None 
        for step in plan:
            any_change = False
            last_msg = create_assistant_message(json.dumps([step], indent=2))
            tool_name = step.get("tool")
            args = step.get("payload", {})
            if tool_name.startswith("functions."):
                tool_name = tool_name.replace("functions.", "")
            step["tool"] = tool_name
            
            try:
                step = preprocess(step)
                tool_name = step.get("tool")
                args = step.get("payload", {})
            except Exception as e:
                user_error_feedback = f"[ERROR] {str(e)}"
                import traceback
                traceback.print_exc()
                break 
                        
            func = tool_map.get(tool_name)
            if func is None:
                print(f"[ERROR] unknown tool: {tool_name}")
                user_error_feedback = f"[ERROR]unknown tool: {tool_name}"
                break # skip to next iteration for replanning
            
            # ensure codebase passed is the current_code when tool expects it
            if current_code == args["codebase"] or equivalent_test(src=current_code, target=args["codebase"]):
                pass 
            else:
                args["codebase"] = current_code
            
            try:
                print(f"[EXECUTE] Calling {tool_name} with args {json.dumps(args, indent=2)}")
                res = func.invoke(args)
            except TypeError as e:
                print(f"[ERROR] Tool invocation failed: {e}")
                user_error_feedback = f"[ERROR]Tool invocation failed: {e}"
                break # skip to next iteration for replanning

            # Normalize result to string codebase if possible
            if isinstance(res, dict):
                if getattr(res, "messages", None) is not None:
                    last_msg = res["messages"][-1]
                    new_code = last_msg.content
                else:
                    new_code = res.get("output") or res.get("codebase") or str(res)
            elif isinstance(res, HumanMessage):
                new_code = res.content
            else:
                new_code = str(res)

            if new_code.startswith("```"):
                # strip code block markers if present
                new_code = "\n".join(new_code.strip().split("\n")[1:-1])
            if new_code != current_code and not equivalent_test(src=current_code, target=new_code):
                    future_distance = get_edit_distance(new_code, target_code)
                    if future_distance < current_edit_distance:
                        any_change = True
                        assert isinstance(args, dict)
                        # args.pop("codebase")
                        executed_plan.append({"action": tool_name, "args": args, "output": new_code, "prefix": left_prefix, "suffix": left_suffix})
                        current_code = new_code
                    else:
                        user_error_feedback = get_user_error_feedback(step) 
                        print(user_error_feedback)
                        break # skip to next iteration for replanning
            else:
                user_error_feedback = get_user_error_feedback(step) 
                print(user_error_feedback)
                break # skip to next iteration for replanning
            # Decision phase: check if target reached
            if current_code == target_code or equivalent_test(src=current_code, target=target_code):
                print("[DONE] Target codebase reached.")
                return {"executed": executed_plan, "target_code": target_code}

        # Replan decision
        if not any_change:
            print("[REPLAN] No changes applied by plan; aborting to avoid infinite loop.")
        else:
            print("[REPLAN] Changes applied; generating new plan in next iteration.")

    print("[COMPLETE] Max iterations reached or loop terminated. Returning executed plan and diff status.")
    return {"executed": executed_plan, "current_code_equals_target": current_code == target_code,  "target_code": target_code}


# given an existing codebase and its patched version, reverse engineer the patch steps
def patch_backport(original_vim_codebase_path: str, patched_vim_codebase_path: str, original_neovim_codebase_path: str, model_name: str = "gpt4o") -> dict:
    set_model(model_name)
    llm_usage_recorder = LLMUsageRecorder()
    
    # Decompose original patches into executable steps
    # Traverse each patch step and migrate it to the new subject
    vim_code = open(original_vim_codebase_path).read()
    vim_patched_code = open(patched_vim_codebase_path).read()
    neovim_code = open(original_neovim_codebase_path).read()

    try:
        patched_plan = reverse_engineer_patches(original_vim_codebase_path, patched_vim_codebase_path, llm_usage_recorder)
    except Exception as e:
        import traceback 
        traceback.print_exc()
        print("Error: ", str(e))
        return {
            "error": True,
            "success": False,
        }
    
    backporter = create_patch_backporting_agent()
    
    fully_executed = True 
    future_target_code = vim_patched_code
    if "current_code_equals_target" in patched_plan:
        fully_executed = False 
        future_target_code = patched_plan.get("target_code")
    
    executed_plan: dict = patched_plan.get("executed", {})
    
    BACKPORT_PATCH_PROMPT = PromptTemplate(
        template="""You are expert at patch backporting. Your task is to backport the original patch from upstream codebase (vim) to the downstream codebase (neovim).
        Original patch from upstream (vim) codebase: \n
        ###Patch action: `{patch}`,\n
        ###Upstream codebase: `{vim_old}`,\n
        \n\n
        
        Backport the above patch to the downstream (neovim) codebase:\n
        ###Patch action: `?`,\n
        ###Downstream codebase: `{neovim_old}`,\n
        \n
        
        Instruction:
        1. Compute and understand the code changes between upstream and downstream codebases.
        2. Backport the original patch action according to the identified code changes between upstream and downstream codebases.
        3. Generate the downstream patch action.
        
        Output Requirement: 
        MUST output the backported patch action with the following JSON format of array object:
        [{{"tool": <tool_name>, "args": {{ ... }}}}, ...., {{"tool": <tool_name>, "args": {{ ... }}}}]
        No explanations. No fence.
        """,
        input_variables=["patch", "vim_old", "neovim_old"],
    )
    
    BACKPORT_PROMPT = PromptTemplate(
        template="""You are expert at patch backporting. Your task is to backport the original patch from upstream codebase (vim) to the downstream codebase (neovim).
        Original patch from upstream (vim) codebase: \n
        ###Patch action: `[{patch}]`,\n
        ###Original code: `{vim_old}`,\n
        ###Patched code: `{vim_patched}`\n
        \n\n
        Backport the above patch to the downstream (neovim) codebase:\n
        ###Patch action: `{neovim_patched}`,\n
        ###Original code: `{neovim_old}`,\n
        ###Patched code: `?` \n
        \n
        
        Instruction:
        * First, adapt the original patch action from upstream (vim) codebase to the downstream (neovim) codebase. There may need some modification to the original patch to accomodate the coding context or style of the downstream (neovim) codebase
        * Second, STRICTLY implement the adapted patch action to the downstream (neovim) codebase.
       
        Output Requirement: 
        MUST output the patched code. No explanations. No fence.
        """,
        input_variables=["patch", "vim_old", "vim_patched", "neovim_old"],
    )
    BACKPORT_PROMPT_Default = PromptTemplate(
        template="""You are expert at patch backporting. Your task is to backport the original patch from upstream codebase to the downstream codebase.
        Original patch from upstream(vim) codebase: \n
        ###Original code: `{vim_old}`,\n
        ###Patched code: `{vim_patched}`\n
        \n\n
        Backport the above patch to the downstream(neovim) codebase:\n
        ###Original code: `{neovim_old}`,\n
        ###Patched code: `?`,
        
        Output Requirement: 
        MUST output the patched code. No explanations. No fence.
        """,
        input_variables=["vim_old", "vim_patched", "neovim_old"],
    )
     
    vim_old = vim_code
    neovim_old = neovim_code
    if fully_executed:
        for patch in copy.deepcopy(executed_plan):
            assert isinstance(patch, dict)
            vim_old = patch.get("args", {}).get("codebase")
            vim_new = patch.get("output")
            prefix = patch.get("prefix")
            suffix = patch.get("suffix")
            patch.pop("prefix")
            patch.pop("suffix")
            if prefix is not None:
                vim_old = prefix + vim_old
                vim_new = prefix + vim_new
            if suffix is not None:
                vim_old = vim_old + suffix
                vim_new = vim_new + suffix
        
            assert vim_old is not None
            assert vim_new is not None 
            patch.pop("output")
            patch.get("args", {}).pop("codebase")
            try:
                # Option1: Two-phases inference (Patch action adaption + Patch Generation)
                raw_prompt = BACKPORT_PATCH_PROMPT.format(patch=json.dumps(patch, indent=2), vim_old = vim_old, vim_patched = vim_new, neovim_old=neovim_old)
                response = backporter.invoke({"messages": create_user_messages(raw_prompt)}, config={"recursion_limit": 50})
                
                plan, _ = get_plan(response=response, llm_usage_recorder=llm_usage_recorder)
                
                raw_prompt = BACKPORT_PROMPT.format(patch=json.dumps(patch, indent=2), vim_old = vim_old, vim_patched = vim_new, neovim_patched = json.dumps(plan, indent=2),neovim_old=neovim_old)
                response = backporter.invoke({"messages": create_user_messages(raw_prompt)}, config={"recursion_limit": 50})
                
                # extract text content
                code = get_code(response, llm_usage_recorder)
                
                neovim_old = code 
                vim_old = vim_new
                neovim_patched = neovim_old
            
            except:
                # Option1: One-phase inference (Patch Generation)
                raw_prompt = BACKPORT_PROMPT.format(patch=json.dumps(patch, indent=2), vim_old = vim_old, vim_patched = vim_new, neovim_patched = "?",neovim_old=neovim_old)
                response = backporter.invoke({"messages": create_user_messages(raw_prompt)}, config={"recursion_limit": 50})
                
                # extract text content
                code = get_code(response, llm_usage_recorder)
                neovim_old = code 
                vim_old = vim_new
                neovim_patched = neovim_old
                
        return {
                    "vim_code": vim_code,
                    "vim_patch_plan": patched_plan,
                    "neovim_code": neovim_code,
                    "patched": neovim_patched,
                    "llm_report": llm_usage_recorder.report()
                }
    else:
        raw_prompt = BACKPORT_PROMPT_Default.format(vim_old = vim_old, vim_patched = vim_patched_code,  neovim_old=neovim_old)
        response = backporter.invoke({"messages": create_user_messages(raw_prompt)}, config={"recursion_limit": 50})
        
        # extract text content
        code = get_code(response, llm_usage_recorder)
       
        neovim_patched = code
            
        return {
            "vim_code": vim_code,
            "vim_patch_plan": patched_plan,
            "neovim_code": neovim_code,
            "patched": neovim_old,
            "llm_report": llm_usage_recorder.report()
            }

# our command-line interface for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Patch Backporting Agent")
    parser.add_argument("original_codebase_path", type=str, help="Path to the original codebase")
    parser.add_argument("patched_codebase_path", type=str, help="Path to the patched codebase")
    parser.add_argument("new_codebase_path", type=str, help="Path to the downstream codebase")
    args = parser.parse_args()
    
    try:
        result = patch_backport(args.original_codebase_path, args.patched_codebase_path, args.new_codebase_path)
        print(json.dumps(result))
    except Exception as e:
        import traceback
        traceback.print_exc()

    # response = reverse_engineer_patches(args.original_codebase_path, args.patched_codebase_path)