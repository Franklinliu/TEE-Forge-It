import re
import json
from typing import List, Dict, Any

RULE_RE = re.compile(r"^(?P<op>Substitute|Insert|Remove|Replace)\s*\((?P<args>.*)\)\s*$")

def parse_id(tok: str) -> Dict[str, str]:
    # expecting 'name:Type' or 'const:Type'
    tok = tok.strip()
    if ':' in tok:
        name, typ = tok.split(':', 1)
        return {"name": name.strip(), "type": typ.strip()}
    return {"name": tok, "type": ""}

def split_args(argstr: str) -> List[str]:
    # naive split by commas but allow commas inside backticks
    parts = []
    cur = []
    depth = 0
    for ch in argstr:
        if ch == '`':
            depth ^= 1
            cur.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append(''.join(cur).strip())
    return parts

def unquote_node(s: str) -> str:
    s = s.strip()
    if s.startswith('`') and s.endswith('`'):
        return s[1:-1]
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s

def parse_rule(line: str) -> Dict[str, Any]:
    m = RULE_RE.match(line.strip())
    if not m:
        raise ValueError(f"Invalid rule syntax: {line}")
    op = m.group('op')
    args = split_args(m.group('args'))
    # Map args depending on op
    if op == 'Substitute':
        if len(args) != 3:
            raise ValueError('Substitute needs 3 args')
        return {"op": op, "from": parse_id(args[0]), "to": parse_id(args[1]), "scope": args[2].strip()}
    if op == 'Insert':
        if len(args) != 2:
            raise ValueError('Insert needs 2 args')
        return {"op": op, "node": unquote_node(args[0]), "scope": args[1].strip()}
    if op == 'Remove':
        if len(args) != 2:
            raise ValueError('Remove needs 2 args')
        return {"op": op, "node": unquote_node(args[0]), "scope": args[1].strip()}
    if op == 'Replace':
        if len(args) != 3:
            raise ValueError('Replace needs 3 args')
        return {"op": op, "from": unquote_node(args[0]), "to": unquote_node(args[1]), "scope": args[2].strip()}
    if op == 'RenameFunc':
        if len(args) != 2:
            raise ValueError('RenameFunc needs 2 args')
        return {"op": op, "Func1": args[0].strip(), "Func2": args[1].strip()}
    if op == "Move":
        if len(args) != 3:
            raise ValueError('Move needs 3 args')
        return {"op": op, "node": unquote_node(args[0]), "scope1": args[1].strip(), "scope2": args[2].strip()}
    raise ValueError('Unknown op')

def parse_strategy(text: str) -> Dict[str, Any]:
    """Parse a Strategy text into structured dict {strategy: [rules...]}.
    Accepts either JSON (already structured) or newline separated rules following grammar.
    """
    text = text.strip()
    # Try JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and 'strategy' in obj:
            return obj
    except Exception:
        pass

    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        rules.append(parse_rule(line))
    return {"strategy": rules}
