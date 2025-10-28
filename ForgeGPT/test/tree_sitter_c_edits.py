#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tree-sitter-c source-to-source example:
- Wrap single-statement `if` bodies with braces.
- Wrap return expressions in parentheses if not already wrapped.

Usage:
  python ts_c_s2s.py input.c > output.c
"""

from tree_sitter import Parser
import tree_sitter
from tree_sitter_languages import get_language
import sys
import re
from dataclasses import dataclass
from packaging import version
import importlib.metadata
tree_sitter_version = importlib.metadata.version("tree_sitter")
print("tree_sitter_version: ", tree_sitter_version)

LANG_C = get_language("c")

def query(pattern_str):
    if version.parse(tree_sitter_version) >= version.parse("0.20.4"):
    # 0.21+ API
        q = LANG_C.query(pattern_str)      # takes str
    else:
        # 0.20.x API
        from tree_sitter import Query
        q = Query(LANG_C, pattern_str.encode("utf-8"))  # needs bytes
    return q      
@dataclass
class Edit:
    start: int
    end: int
    replacement: bytes

def parse(src: bytes):
    parser = Parser()
    parser.set_language(LANG_C)
    return parser.parse(src)

def get_indent_before(src: bytes, pos: int) -> bytes:
    """
    Return the indentation (spaces/tabs) on the current line up to 'pos'.
    """
    line_start = src.rfind(b'\n', 0, pos) + 1
    line = src[line_start:pos]
    m = re.match(br"[ \t]*", line)
    return m.group(0) if m else b""

def is_compound_stmt(node) -> bool:
    return node.type == "compound_statement"  # '{ ... }'

def collect_if_brace_edits(tree, src: bytes):
    """
    For each if_statement whose consequence is a single non-compound statement,
    wrap it into a block { ... } with reasonable formatting.
    """
    q = query("""
      (if_statement
         condition: (_)
         consequence: (_) @then)
    """)
    cur = tree.walk()
    captures = q.captures(tree.root_node)
    edits = []
    for node, name in captures:
        if name != "then":
            continue
        # Skip if already a compound block
        if is_compound_stmt(node):
            continue
        # Also skip if it's an 'if_statement' (avoid changing `if (...) if (...) ...`)
        if node.type == "if_statement":
            continue

        # We replace the exact bytes of the 'then' node with a braced block.
        # Preserve indentation from the 'if' line.
        indent = get_indent_before(src, node.start_byte)
        stmt_bytes = src[node.start_byte:node.end_byte].rstrip()
        # Add one indentation level inside braces
        inner_indent = indent + b"    "
        # If the statement ends with ';', keep as is inside braces.
        body = stmt_bytes
        # Construct replacement:
        # Keep on the same line if it's short; otherwise newline format.
        # We'll choose a newline style for clarity and robustness.
        replacement = b"{\n" + inner_indent + body + b"\n" + indent + b"}"
        edits.append(Edit(node.start_byte, node.end_byte, replacement))
    return edits

def collect_return_paren_edits(tree, src: bytes):
    """
    For each return_statement, ensure the argument is parenthesized:
    `return x + y;` -> `return (x + y);`
    (Skip if already `return ( ... );`)
    """
    q = query("""
      (return_statement) @ret
    """)
    captures = q.captures(tree.root_node)
    edits = []
    for node, name in captures:
        start = node.start_byte
        end = node.end_byte
        text = src[start:end]

        # Heuristic: find the 'return' keyword and semicolon inside this node’s slice.
        # NOTE: Tree-sitter doesn't give us token spans directly, so we search.
        m = re.match(br"\s*return\b", text)
        if not m:
            continue
        after_return = m.end()  # index in 'text'
        # Find the last ';' (should be the statement terminator)
        semi = text.rfind(b';')
        if semi == -1 or semi <= after_return:
            continue

        arg = text[after_return:semi]  # between `return` and `;`
        # Skip if already parenthesized (ignoring whitespace)
        if re.match(br"\s*\(.*\)\s*$", arg, flags=re.S):
            continue

        # Wrap in parentheses, preserve inner spacing
        new_arg = b" (" + arg.strip() + b") "
        new_text = text[:after_return] + new_arg + text[semi:]
        edits.append(Edit(start, end, new_text))
    return edits

def apply_edits(src: bytes, edits):
    """
    Apply non-overlapping edits in reverse start order.
    """
    edits_sorted = sorted(edits, key=lambda e: e.start, reverse=True)
    out = bytearray(src)
    for e in edits_sorted:
        out[e.start:e.end] = e.replacement
    return bytes(out)

def transform(src: bytes) -> bytes:
    tree = parse(src)
    edits = []
    edits += collect_if_brace_edits(tree, src)
    # Reparse after first set of edits to keep node byte ranges valid for subsequent passes
    if edits:
        src = apply_edits(src, edits)
        tree = parse(src)
    edits2 = collect_return_paren_edits(tree, src)
    if edits2:
        src = apply_edits(src, edits2)
    return src

def main():
    if len(sys.argv) != 2:
        print("Usage: python ts_c_s2s.py input.c", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], "rb") as f:
        src = f.read()
    out = transform(src)
    sys.stdout.buffer.write(out)

if __name__ == "__main__":
    main()