# This code is an MVP implementation of decompose and patch backporting using LLMs.
# It may not cover all edge cases and is intended for demonstration purposes only.
import os 
import json 
from typing import Union, List
from langchain.tools import tool

from langgraph.prebuilt import create_react_agent

from langchain import hub
from langchain import hub
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, stop_after_attempt, wait_random

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from src.patch_backporting.code_transformer import InsertArgs, RemoveArgs, MoveArgs, ReplaceArgs, insert

parser = JsonOutputParser()
fmt = parser.get_format_instructions()

from src.model.qwen import qwen3coder_30b as model 


def create_user_messages(prompt: str) -> List[dict]:
    """Create user messages for agent invocation."""
    return [{"role": "user", "content": prompt}]

def add_retry_to_tool(tool, max_attempts=3):
    """Wrap a Tool's callable with retry logic."""
    original_func = tool.func

    @retry(stop=stop_after_attempt(max_attempts), wait=wait_random(1, 3))
    def retried_func(*args, **kwargs):
        return original_func(*args, **kwargs)

    tool.func = retried_func
    return tool

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


@tool("insert_statements_in_codebase", args_schema=InsertArgs)
def insert_statements_in_codebase(codebase: str, statements: str, destination_function: str, destination_location_prev_statement:str, destination_location_next_statement: str) -> str:
    """Insert statements into the codebase; return modified code."""
    if destination_location_prev_statement == "" and destination_location_next_statement == "":
        return "Error: Either destination_location_prev_statement or destination_location_next_statement must be provided."
    if destination_location_prev_statement == destination_location_next_statement:
        return "Error: destination_location_prev_statement and destination_location_next_statement cannot be the same."
    # agent = create_normal_agent()
    # prompt = (
    #     "STRICTLY follow the instructions:  "
    #     f"Insert:\n`{statements}`\ninto codebase:\n`{codebase}` at destination_location_description: between `{destination_location_prev_statement}` and `{destination_location_next_statement}` inside function `{destination_function}`\nOutput ONLY the modified codebase."
    #     "CANNOT modify and remove other parts of the codebase."
    #     )
    # result = agent.invoke({"messages":create_user_messages(prompt)})
    # return result.get("output", str(result))
    obj = InsertArgs(
        codebase=codebase,
        statements=statements,
        destination_function=destination_function,
        destination_location_prev_statement=destination_location_prev_statement,
        destination_location_next_statement=destination_location_next_statement
    )
    result = insert(obj)
    print("Statements to insert:", statements)
    print("Insert Result:", result)
    return result


@tool("remove_statements_from_codebase", args_schema=RemoveArgs)
def remove_statements_from_codebase(codebase: str, statements: str, source_location_description: str) -> str:
    """Remove statements from the codebase; return modified code."""
    agent = create_normal_agent()
    prompt = (
        "STRICTLY follow the instructions to  "
        f"Remove:\n`{statements}` at source_location_description:`{source_location_description}` \nfrom codebase:\n`{codebase}`\nOutput ONLY the modified codebase."
        "CANNOT modify and remove other parts of the codebase."
        )
    result = agent.invoke({"input": prompt})
    return result.get("output", str(result))



@tool("move_statements_in_codebase", args_schema=MoveArgs)
def move_statements_in_codebase(codebase: str, statements: str, old_location: str, new_location: str) -> str:
    """Move statements within the codebase to a new location; return modified code."""
    agent = create_normal_agent()
    prompt = (
        "STRICTLY follow the instructions to  "
        f"Move:\n`{statements}` at `{old_location}` \nwithin codebase:\n`{codebase}`\nto:\n new_location_description:`{new_location}`\nOutput ONLY the modified codebase."
        "CANNOT modify and remove other parts of the codebase."
        )
    result = agent.invoke({"messages":create_user_messages(prompt)})
    return result.get("output", str(result))


@tool("replace_statements_in_codebase", args_schema=ReplaceArgs)
def replace_statements_in_codebase(codebase: str, old_statements: str, new_statements: str) -> str:
    """Replace old statements with new statements in the codebase; return modified code."""
    agent = create_normal_agent()
    prompt = (
        "STRICTLY follow the instructions to  "
        "Replace the following old statements:\n"
        f"`{old_statements}`\n"
        "in the codebase:\n"
        f"`{codebase}`\n"
        "with the new statements:\n"
        f"`{new_statements}`\n"
        "CANNOT modify and remove other parts of the codebase."
        "Output ONLY the modified codebase."
    )
    result = agent.invoke({"messages":create_user_messages(prompt)})
    return result.get("output", str(result))

class IfGuardArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    statements: Union[str, List[str]] = Field(description="Snippet(s) to guard with checks")
    guard: Union[str, List[str]] = Field(description="Guard condition(s) to apply")

    @field_validator("statements", "guard")
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v

@tool("ifguard_statements_in_codebase", args_schema=IfGuardArgs)
def ifguard_statements_in_codebase(codebase: str, statements: str, guard: str) -> str:
    """Sanic check statements with newly-introduced conditions in the codebase; return modified code."""
    agent = create_normal_agent()
    prompt = (
        "STRICTLY follow the instructions to  "
        "Guard the following statements:\n"
        f"`{statements}`\n"
        "in the codebase:\n"
        f"`{codebase}`\n"
        "with the if-guard condition(s):\n"
        f"`{guard}`\n"
        "Output ONLY the modified codebase."
    )
    result = agent.invoke({"messages":create_user_messages(prompt)})
    return result.get("output", str(result))


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
        ifguard_statements_in_codebase
    ]
    tools = [add_retry_to_tool(t) for t in tools]
    prompt = "You are a helpful patch backporting agent."
    # create a patch backporting planner agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt = prompt
    )
    return agent

# given an existing codebase and its patched version, reverse engineer the patch steps
def reverse_engineer_patches(original_codebase_path: str, patched_codebase_path: str) -> str:
    agent = create_patching_agent()
    prompt = PromptTemplate(
        template="""You are a patch agent. Given the original codebase:\n  `{original_codebase}` and its patched version:\n`{patched_codebase}`, your task is to reverse engineer the patch steps taken to transform the original codebase into the patched version.
        Please provide a detailed list comprise one or more patch steps. 
        
        NOTE the order of operations matters; the output codebase of earlier steps is the input codebase of the latter ones.
        
        Strictly follows the tool selection criteria:
        1. ONLY If statements (denoted as X) in the original codebase turn to be inside an if-condition-related statement (denoted as if (...){{X}}) in its patched codebase, USE ifguard_statements_in_codebase tool.
        2. ONLY If a statement is located at different places in the original and patched codebase respectively, USE move_statements_in_codebase tool, where statement MUST be expression statements, where statement MUST be expression statements or if-statement or if-else-statement..
        3. ONLY If a statement (X) in the original codebase is replaced by another statement (Y) in its patched version, USE replace_statements_in_codebase tool. Note this tool only supports one-to-one replacement, where old_statements and new_statements (X and Y) MUST be expression statements.
        4. ONLY If a statement in the original codebase is removed entirely in its patched version, USE remove_statements_from_codebase tool, where statement MUST be expression statements or if-statement or if-else-statement.
        5. ONLY If a statement (denoted as X) is added in the patched codebase and X is not included in the original codebase, USE insert_statements_in_codebase tool, where statement MUST be expression statements or if-statement or if-else-statement that has never be seen in the original codebase. destination_location_prev_statement and destination_location_next_statement MUST refer to declaration/expression/return statements and MUST be provided to indicate the insertion location.
        6. For other complex/ambiguous cases, select the other proper tools accordingly.
        
        Instructions:
        1. The tool selection priority: ifguard_statements_in_codebase > move_statements_in_codebase > replace_statements_in_codebase > other tools. 
        2. First Check comprehensively whether ifguard_statements_in_codebase tool can be used at each round of patch step decision process.
        3. Do not invent any patch steps that are not supported by the provided tools.
        4. The ordered execution of the resulting patch steps MUST address all differences between the original and patched codebases.
        
        The patch steps MUST be defined by the provided tools, their payloads, and their output.
        Output the patch steps in JSON format.
        """,
        input_variables=["original_codebase", "patched_codebase"],
        # partial_variables={"format_instructions": fmt},
        )
    raw_prompt = prompt.format(original_codebase = open(original_codebase_path).read(), patched_codebase = open(patched_codebase_path).read())
    response = agent.invoke({"messages":create_user_messages(raw_prompt)})
    return response


# our command-line interface for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Patch Backporting Agent")
    parser.add_argument("original_codebase_path", type=str, help="Path to the original codebase")
    parser.add_argument("patched_codebase_path", type=str, help="Path to the patched codebase")
    args = parser.parse_args()

    response = reverse_engineer_patches(args.original_codebase_path, args.patched_codebase_path)
    print("Reverse Engineered Patch Steps:")
    # get the last message content (support dicts or objects)
    if isinstance(response, dict):
        msgs = response.get("messages", []) or []
    elif hasattr(response, "messages"):
        msgs = getattr(response, "messages") or []
    else:
        msgs = []

    last_msg = msgs[-1] if msgs else None

    if last_msg is None:
        patch_steps = str(response)
    else:
        if isinstance(last_msg, dict):
            patch_steps = last_msg.get("content") or last_msg.get("text") or str(last_msg)
        else:
            patch_steps = getattr(last_msg, "content", getattr(last_msg, "text", str(last_msg)))

    try:
        patch_steps_json = json.loads(patch_steps)
        print(json.dumps(patch_steps_json, indent=2))
    except json.JSONDecodeError:
        print(patch_steps)