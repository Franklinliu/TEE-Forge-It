"""
DSL Transformer for C code edits using tree-sitter.
Supports Move, Insert, Remove, Replace actions as described in DSL grammar.
"""
import re
import sys
from typing import Union, List
from tree_sitter import Parser
from tree_sitter_languages import get_language
import os
import re
from .code_transformer import equivalent_test
from .diff import unified_diff_ignore_whitespace

HUNK_HEADER_RE = re.compile(r'^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@')

DEBUG = False

class DiffHunk:
    def __init__(self, old_start, old_count, new_start, new_count, lines):
        self.old_start = int(old_start)
        self.old_count = int(old_count) if old_count else 1
        self.new_start = int(new_start)
        self.new_count = int(new_count) if new_count else 1
        self.lines = lines  # List of lines in the hunk

    def __repr__(self):
        return (f"<DiffHunk -{self.old_start},{self.old_count} "
                f"+{self.new_start},{self.new_count} lines={len(self.lines)}>")
    def __str__(self):
        return (f"@@ -{self.old_start},{self.old_count} +{self.new_start},{self.new_count} @@\n" +
                "\n".join(self.lines))

def parse_diff_hunks(diff_text) -> list[DiffHunk]:
    """
    Parses hunks from a git diff text.
    Returns a list of DiffHunk objects.
    """
    lines = diff_text.splitlines()
    hunks: list [DiffHunk] = []
    i = 0
    # 跳过所有非 hunk 头部的内容
    while i < len(lines) and not HUNK_HEADER_RE.match(lines[i]):
        i += 1
    # 开始解析 hunk
    while i < len(lines):
        match = HUNK_HEADER_RE.match(lines[i])
        if match:
            old_start, old_count, new_start, new_count = match.groups()
            hunk_lines = []
            i += 1
            while i < len(lines) and not HUNK_HEADER_RE.match(lines[i]):
                hunk_lines.append(lines[i])
                i += 1
            hunks.append(DiffHunk(old_start, old_count, new_start, new_count, hunk_lines))
        else:
            i += 1
    return hunks

def compute_diff(old_code: str, new_code: str) -> str:
    # use difflib to compute the diff
    # import difflib
    # diff = difflib.unified_diff(
	# 	old_code.splitlines(),
	# 	new_code.splitlines(),
	# 	lineterm='',
	# )	
    # diff_text = '\n'.join(diff)
    diff_text = unified_diff_ignore_whitespace(a = old_code,
	b = new_code, fromfile= "original", tofile="patched", context=3)
    return diff_text
    
def compute_diff_hunks(old_code: str, new_code: str) -> list[DiffHunk]:
    """
	Computes the diff hunks between old_code and new_code using git diff.
	Returns a list of DiffHunk objects.
	"""
    diff_text = compute_diff(old_code, new_code)
    if DEBUG:
       print("Diff text "+ diff_text)
    return parse_diff_hunks(diff_text)	

def parse(src: bytes):
	LANG_C = get_language("c")
	parser = Parser()
	parser.set_language(LANG_C)
	return parser.parse(src)

def find_nodes_by_code(tree, src: bytes, code: str, loc_type: str = "exact"):
	"""Find all nodes in the tree whose source matches code (stripped).

	Returns a list of nodes in preorder.
	loc_type can be 'before' (node startswith code), 'after' (endswith code),
	or 'exact' (exact match). Default is 'exact'.
	"""
	code = " ".join(code.split())
	code = code.strip()
	if code.endswith("{"):
		code = code[:-1]
	code_bytes = code.strip().encode()
	matches = []

	def walk(node):
		try:
			node_bytes = src[node.start_byte:node.end_byte].strip()
			node_bytes =  (" ".join(node_bytes.decode().split())).encode()
		except Exception:
			node_bytes = b""
		
		if loc_type == "exact":
			if node_bytes == code_bytes:
				matches.append(node)
		else:
			# Restrict to assignment, expression, or conditional nodes
			allowed_types = {
				"expression_statement",
				"if_statement",
				"conditional_expression",
				# allow C preprocessor / macro definitions (#define, #if, etc.)
				"preproc_def",
				"preproc_directive",
				"preproc_include",
				# variable declaration related nodes
				"declaration",
				"init_declarator",
				"init_declarator_list",
				"type_specifier",
				"type_identifier",
				# assignment-related nodes
				"assignment_statement",
				"assignment_expression",
				"compound_assignment_expression",
				"binary_expression",
				# loop constructs
				"for_statement",
				"while_statement",
				"do_statement",
    			"return_statement",
			}
			if node_bytes.startswith(code_bytes) and node.type in allowed_types:
				matches.append(node)

		for child in node.children:
			walk(child)

	walk(tree.root_node)
	return matches

def cut_code(src: bytes, start_byte: int, end_byte: int) -> bytes:
	"""Cut code from src between start_byte and end_byte."""
	return src[start_byte:end_byte]

# return 
def trim_code_containing_diff(left_code:str, right_code:str) -> tuple[str, str]:
	"""Trim code to only the parts containing diffs (if-statements)."""
	if equivalent_test(left_code, right_code):
		return {
			"left_code": {
				"start_byte": 0,
				"end_byte": len(left_code),
				"code": left_code
			},
			"right_code": {
				"start_byte": 0,
				"end_byte": len(right_code),
				"code": right_code
			}}

	# Compute diff hunks
	hunks = compute_diff_hunks(left_code, right_code)
	if not hunks:
		return {
			"left_code": {
				"start_byte": 0,
				"end_byte": len(left_code),
				"code": left_code
			},
			"right_code": {
				"start_byte": 0,
				"end_byte": len(right_code),
				"code": right_code
			}}

	if len(left_code.splitlines()) < 50 or len(right_code.splitlines()) < 50:
		# If code is small enough, no need to trim
		return {
			"left_code": {
				"start_byte": 0,
				"end_byte": len(left_code),
				"code": left_code
			},
			"right_code": {
				"start_byte": 0,
				"end_byte": len(right_code),
				"code": right_code
			}}
  
	if len(hunks) > 1:
		# Find the first and last hunk
		first_hunk = hunks[0]
		last_hunk = hunks[-1]
		
		first_hunk_begin_offset = 0
		last_hunk_end_offset = 0
		while not first_hunk.lines[first_hunk_begin_offset].startswith("-") and not first_hunk.lines[first_hunk_begin_offset].startswith("+"):
			first_hunk_begin_offset += 1
		
		
		total = len(last_hunk.lines)-1
		while not last_hunk.lines[total - last_hunk_end_offset].startswith("-") and not last_hunk.lines[total -  last_hunk_end_offset].startswith("+"):
			last_hunk_end_offset += 1
		
		
		left_code_line_diff_start = first_hunk.old_start - 1 + first_hunk_begin_offset
		left_code_line_diff_end = last_hunk.old_start + last_hunk.old_count  - last_hunk_end_offset
		if DEBUG:
			print("Left code diff lines:", left_code_line_diff_start, left_code_line_diff_end)
	
		right_code_line_diff_start = first_hunk.new_start - 1 + first_hunk_begin_offset
		right_code_line_diff_end = last_hunk.new_start + last_hunk.new_count - last_hunk_end_offset
		
		if DEBUG:
			print("Right code diff lines:", right_code_line_diff_start, right_code_line_diff_end)
	else:
		left_code_line_diff_start = hunks[0].old_start - 1
		left_code_line_diff_end = hunks[0].old_start +  hunks[0].old_count-1
		if DEBUG:
			print("Left code diff lines:", left_code_line_diff_start, left_code_line_diff_end)
	
		right_code_line_diff_start = hunks[0].new_start - 1 
		right_code_line_diff_end = hunks[0].new_start +  hunks[0].new_count-1
 
	# get parse tree for left and right code
	left_tree = parse(left_code.encode())
	right_tree = parse(right_code.encode())
 
	# I want the minimal enclosing nodes that cover the diff lines
	def get_byte_range_code_for_lines(code: str, tree, start_line: int, end_line: int) -> tuple[int, int]:
		"""Get byte range for lines [start_line, end_line) in code."""
		lines = code.splitlines(keepends=True)
		if start_line < 0 or end_line > len(lines):
			return 0, 0
		# start line content cannot be empty
		while start_line < len(lines) and lines[start_line].strip() == "":
			start_line += 1
		while end_line > 0 and lines[end_line - 1].strip() == "":
			end_line -= 1
		if start_line >= end_line:
			return 0, 0
		start_byte = sum(len(lines[i]) for i in range(start_line))
		end_byte = sum(len(lines[i]) for i in range(end_line))
		if DEBUG:
			print("Start byte: ", start_byte)
			print("End byte: ", end_byte)
		

		# Find the two sibling nodes that encloses this byte range start_byte to end_byte respectively
		def find_enclosing_node(node, start_byte, end_byte):
			if node.start_byte <= start_byte and end_byte<= node.end_byte:
				for child in node.children:
					result = find_enclosing_node(child, start_byte, end_byte)
					if result:
						return result
				return node
			return None
		scope_node = find_enclosing_node(tree.root_node, start_byte, end_byte)
		if scope_node is None:
			return tree.root_node.start_byte, tree.root_node.end_byte
		if len(scope_node.children) > 1:
			total = len(scope_node.children)
			first_child_index = 0
			last_child_index = total - 1
			while first_child_index < total and scope_node.children[first_child_index].end_byte < start_byte:
				first_child_index += 1
			while last_child_index >= 0 and scope_node.children[last_child_index].start_byte > end_byte:
				last_child_index -= 1
			return scope_node.children[first_child_index].start_byte, scope_node.children[last_child_index].end_byte

		else:
			return scope_node.start_byte, scope_node.end_byte


	left_start_byte, left_end_byte = get_byte_range_code_for_lines(
		left_code, left_tree, left_code_line_diff_start, left_code_line_diff_end)
	right_start_byte, right_end_byte = get_byte_range_code_for_lines(
		right_code, right_tree, right_code_line_diff_start, right_code_line_diff_end)
	if DEBUG:
		print("Left byte range:", left_start_byte, left_end_byte)
		print("Right byte range:", right_start_byte, right_end_byte)
	trimmed_left_code = left_code[left_start_byte:left_end_byte]
	trimmed_right_code = right_code[right_start_byte:right_end_byte]
	if trimmed_left_code != "" and trimmed_right_code != "":
		return {
			"left_code": {
				"start_byte": left_start_byte,
				"end_byte": left_end_byte,
				"code": trimmed_left_code
			},
			"right_code": {
				"start_byte": right_start_byte,
				"end_byte": right_end_byte,
				"code": trimmed_right_code
			}}       		
	else:
		return {
			"left_code": {
				"start_byte": 0,
				"end_byte": len(left_code),
				"code": left_code
			},
			"right_code": {
				"start_byte": 0,
				"end_byte": len(right_code),
				"code": right_code
			}}

if __name__ == "__main__":
	DEBUG = True 
	left_code = open("/workspaces/TEE-Forge-It/baseline/dataset/PPatHF/Neovim-Vim/test-patch-classified/1/15/before_source.c").read()
	right_code = open("/workspaces/TEE-Forge-It/baseline/dataset/PPatHF/Neovim-Vim/test-patch-classified/1/15/after_source.c").read()
	result = trim_code_containing_diff(left_code, right_code)
	print("Trimmed Left Code:\n", result["left_code"]["code"])
	print("byte range:", result["left_code"]["start_byte"], result["left_code"]["end_byte"])
	print("-------------------")
	print("Trimmed Right Code:\n", result["right_code"]["code"])
	print("byte range:", result["right_code"]["start_byte"], result["right_code"]["end_byte"])