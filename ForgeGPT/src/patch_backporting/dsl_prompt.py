import os 

DSL_GRAMMAR = """
DSL Grammar:\n 
                Strategy ::= Rule*
                Rule ::=  Move(Node, Location1, Location2) || Insert(Node, Location)  || Remove(Node, Location) || Replace(Node1, Node2, Location)
                Modifier ::= static || const
                Var  ::=  Identifier : Modifier? Type
                Exp  ::= Identifier || Constant || Exp op Exp
                Stmt ::= Exp || Break || Continue ||If {Exp} Block ||If {Exp} Block else Block
                        || While {Exp} Block || For {Exp1, Exp2, Exp3} Block
                        || Return Exp || Goto Identifier
                Block ::= Stmt || { Stmt * } || #ifdef Identifier Block #endif || #ifdef Identifier Block #elif Block #endif 
                Node ::= Stmt || Block 
                Location :: =  (after || before): Stmt
            
            Explanation of data types:
            - Var is a variable with its type.
            - Node can be either expression, statement or block. Note #ifdef, #elif, #endif are macros used in C program.
            - op is a binary operator like +, -, *, /, %, &&, ||, etc.
            - Location is a unique program point that developers can easily refer to. Note "after", "before" are the location attributes attached with specific statement, respectively. 
             
            Explanation of actions:
            - `Remove` removes a code snippet (Node/Var) at a given location.
            - `Move` shifts a code snippet (Node) from the original location (Location1) to a different location (Location2). Location1 and Location2 CANNOT be identical.
            - `Insert` adds a code snippet (Node) at a program location (Location).
            - `Replace` replaces one code snippet (Node1) with another code snippet (Node2) at a program location (Location). Node1 and Node2 CANNOT be identical.
            
            For better readability, consider using more precise actions in the DSL code. 
            Use the following heuristic rules:
            (1) Use Move(x, y1, y2) instead of having both Remove(x, y1) and Insert(x, y2). 
            (2) Use Replace(x1, x2, z) instead of having both Remove(x1, y) and Insert(x2, y). 
            (3) Use Insert({x1, x2}, y) instead of having both Insert(x1, y) and Insert(x2, y)
            (3) Use Remove({x1, x2}, y) instead of having both Remove(x1, y) and Remove(x2, y)
"""


# Generate seed DSL code from given unified_diff between two programs using difflib

def parse_unified_diff(diff_lines: list[str]) -> list[dict]:
    """Parse unified diff format into structured changes.
    
    Args:
        diff_lines: The unified diff lines (from difflib.unified_diff)
        
    Returns:
        List of changes, each containing:
        {
            "type": "context"|"add"|"remove",
            "line": str,  # the actual code line
            "line_no": Optional[int],  # line number in original/new file
        }
    """
    changes = []
    total_diff_len = len(diff_lines)
    for chunk_index, line in enumerate(diff_lines):
        if not line:
            continue
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
            
        change_type = None
        if line.startswith("+"):
                if any([line[1:].strip().strip("\t").startswith(delim) for delim in ["(", ")", "{", "}"]]):
                        pass 
                elif chunk_index == 0 :
                        change_type = "add" 
                        code_line = line[1:]
                else:
                        if diff_lines[chunk_index-1].startswith("-") and diff_lines[chunk_index-1][1:].strip().strip("\t") == line[1:].strip().strip("\t"):
                                pass 
                        else:
                                change_type = "add" 
                                code_line = line[1:]
        elif line.startswith("-") :
            if any([line[1:].strip().strip("\t").startswith(delim) for delim in ["(", ")", "{", "}"]]):
                pass 
            elif chunk_index + 1 == total_diff_len  :
                change_type = "remove" 
                code_line = line[1:]
            else:
                   if diff_lines[chunk_index+1].startswith("+") and diff_lines[chunk_index+1][1:].strip().strip("\t") == line[1:].strip().strip("\t"):
                           pass 
                   else:
                        change_type = "remove" 
                        code_line = line[1:]
                                
        else:
            change_type = "context"
            code_line = line[1:] if line.startswith(" ") else line
            
        changes.append({
            "type": change_type,
            "line": code_line.rstrip(),
            "line_no": chunk_index  # Could parse @@ lines to get actual numbers if needed
        })
    
    return changes

def extract_code_changes(changes: list[dict]) -> list[dict]:
    """Extract meaningful code changes from the parsed diff.
    
    This function looks for patterns of changes (add/remove/modify) and groups
    related changes together.
    
    Args:
        changes: List of parsed changes from parse_unified_diff
        
    Returns:
        List of code change blocks, each with:
        {
            "type": "replace"|"insert"|"remove"|"move",
            "old_code": str,  # for replace/remove/move
            "new_code": str,  # for replace/insert 
            "old_location": str,  # for move
            "new_location": str,  # for move/insert
            "context": str,  # surrounding context if available
        }
    """
    blocks = []
    i = 0
    while i < len(changes):
        # Look for move pattern (remove + add of same code)
        if i + 1 < len(changes):
            curr = changes[i]
            next_ = changes[i + 1]
            
            if (curr["type"] == "remove" and next_["type"] == "add" and 
                curr["line"] == next_["line"]) and curr["line_no"] +1 != next_["line_no"]:
                blocks.append({
                    "type": "move",
                    "old_code": curr["line"].strip().strip("\t"),
                    "old_location": _get_context(changes, i),
                    "new_location": _get_context(changes, i+1),
                    "context": _get_context(changes, i)
                })
                i += 2
                continue
                
            # Look for replace pattern (remove followed by add)
            if curr["type"] == "remove" and next_["type"] == "add" and curr["line_no"] != next_["line_no"]:
                blocks.append({
                    "type": "replace",
                    "old_code": curr["line"].strip().strip("\t"),
                    "new_code": next_["line"].strip().strip("\t"),
                    "location": _get_context(changes, i)
                })
                i += 2
                continue
                
        # Single line changes
        if changes[i]["type"] == "add":
            blocks.append({
                "type": "insert",
                "new_code": changes[i]["line"].strip().strip("\t"),
                "new_location": _get_context(changes, i),
                "context": _get_context(changes, i)
            })
        elif changes[i]["type"] == "remove":
            blocks.append({
                "type": "remove",
                "old_code": changes[i]["line"].strip().strip("\t"),
                "old_location": _get_context(changes, i),
                "context": _get_context(changes, i)
            })
            
        i += 1
        
    return blocks

def _get_context(changes: list[dict], pos: int, context_lines: int = 10) -> str:
    """Get surrounding context lines for a change position."""
    context = []
    
    # Look back for context
    start = max(0, pos - context_lines)
    for i in range(start, pos):
        if changes[i]["type"] == "context":
            context.append(changes[i]["line"])
    
    if len(context) > 0:
        if not any([context[-1].strip().strip("\t").startswith(delim) for delim in ["(", ")", "{", "}"]]):  
                return "after: "+ context[-1] 
    from_len = len(context)        
    # Look ahead for context
    end = min(len(changes), pos + context_lines + 1)
    for i in range(pos +1, end):
        if changes[i]["type"] == "context":
            context.append(changes[i]["line"])

    if len(context) > from_len:
        return "before: "+ context[from_len].strip().strip("\t") 
    
    return "Unknown"

def infer_scope(context: str, line: str) -> str:
    """Try to infer the scope of a change based on context and the changed line.
    
    Returns: A scope string matching the DSL grammar, e.g.:
    - "Func foo: (int num) -> (int)"  
    - "Block"
    - "Stmt"
    """
    import re
    
    # Look for function definitions
    func_match = re.search(r"(?:int|void|char\s*\*?)\s+(\w+)\s*\((.*?)\)", context)
    if func_match:
        func_name = func_match.group(1)
        params = func_match.group(2)
        # Simplified - assumes int return type
        return f"Func {func_name}: ({params}) -> (int)" 
    
    # Look for block structures    
    block_start = re.search(r"(?:if|while|for|else)\s*[({]", context)
    if block_start:
        return "Block"
        
    # Default to statement scope
    return "Stmt"

def generate_seed_dsl(unified_diff: list[str]) -> str:
    """Generate initial DSL code from unified diff format.
    
    The DSL follows the grammar defined in DSL_GRAMMAR:
    Strategy ::= Rule*
    Rule ::= Substitute || Move || Insert || Remove || Replace 
    
    Args:
        unified_diff: List of lines in unified diff format
        
    Returns:
        DSL code as a JSON-formatted string
    """
    import json
    
    # Parse and extract changes
    changes = parse_unified_diff(unified_diff)
    blocks = extract_code_changes(changes)
    
    # Convert changes to DSL rules
    rules = []
    for block in blocks:
        if block["type"] == "move":
            rules.append({
                "Move": {
                    "Node": block["old_code"].strip().strip("\t"),
                    "Location1": block["old_location"],
                    "Location2": block["new_location"]
                }
            })
        elif block["type"] == "replace":
            rules.append({
                "Replace": {
                    "Node1": block["old_code"].strip().strip("\t"),
                    "Node2": block["new_code"].strip().strip("\t"), 
                    "Location": block["location"]
                }
            })
        elif block["type"] == "insert":
            rules.append({
                "Insert": {
                    "Node": block["new_code"].strip().strip("\t"),
                    "Location": block["new_location"]
                }
            })
        elif block["type"] == "remove":
            rules.append({
                "Remove": {
                    "Node": block["old_code"].strip().strip("\t"),
                    "Location": block["old_location"]
                }
            })
            
    return json.dumps({"strategy": rules}, indent=2)

if __name__ == "__main__":
    # Example usage
    program1 = '''
int fib_n(int num)
{
    int a = 0;
    return num;
}  
'''

    program2 = '''
int fib_n(int num)
{
    int b = 0;
    int c = 0;
    return num;
}  
'''
    
    import difflib
    diff = list(difflib.unified_diff(
        program1.splitlines(),
        program2.splitlines(),
        fromfile='program1',
        tofile='program2', 
        lineterm=''
    ))
    print("Unified diff:\n", "\n".join(diff))
    
    dsl = generate_seed_dsl(diff)
    print("Generated DSL:\n", dsl)