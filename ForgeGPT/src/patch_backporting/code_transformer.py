"""
DSL Transformer for C code edits using tree-sitter.
Supports Move, Insert, Remove, Replace actions as described in DSL grammar.
"""
from os import close
import re
import sys
from typing import Union, List
from dataclasses import dataclass
from torch import norm
from tree_sitter import Parser, TreeCursor
from tree_sitter_languages import get_language
from pydantic import BaseModel, Field, field_validator
import numpy as np 
import editdistance
from git import Optional
from .fcu import FunctionCompareUtilities

fcu = FunctionCompareUtilities()

IS_preceding_statement = "IS_preceding_statement"
IS_NEXT_STATEMENT = "IS_NEXT_STATEMENT"
LOC_EXACT = "LOC_EXACT"
LOC_ROUGH = "LOC_ROUGH"


def equivalent_test(src, target):
    src_tokens = fcu.get_cleaned_tokens(src)
    target_tokens = fcu.get_cleaned_tokens(target)
    return np.array_equal(src_tokens, target_tokens)

def get_edit_distance(src, target):
    src_tokens = fcu.get_cleaned_tokens(src)
    target_tokens = fcu.get_cleaned_tokens(target)
    return editdistance.eval(src_tokens, target_tokens)

def is_adjacent(src: bytes, tree_node1: TreeCursor, tree_node2: TreeCursor):
	# test if tree_node1 is nodes immediately before tree_node2
	end_byte = tree_node1.node.end_byte
	start_byte = tree_node2.node.start_byte
	if end_byte == start_byte:
		return True 
	else:
		if end_byte >= start_byte and src[end_byte: start_byte].strip() == b"":
			return True 
		else:
			return False 

def contain_test(tree_node1: TreeCursor, tree_node2: TreeCursor):
	# test if tree_node1 contains tree_node2. In other words, tree_node2 is a child node of tree_node1
	return tree_node1.node.start_byte < tree_node2.node.start_byte and tree_node2.node.end_byte < tree_node1.node.end_byte

class InsertArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    statements: Union[str, List[str]] = Field(description="Snippet(s) to insert")
    destination_function: Optional[str] = Field(description="The name of function where the insertion occurs, default \"\"")
    destination_location_preceding_statement: Optional[str] = Field(description="The preceding statements immediately before the `statements`. Use \"\" by default")
    destination_location_next_statement: Optional[str] = Field(description="The next statements immediately after the `statements`. Use \"\" by default")
    @field_validator("statements")	
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v

class RemoveArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    statements: Union[str, List[str]] = Field(description="Snippet(s) to remove")
    destination_function: Optional[str] = Field(description="The name of function where the removal occurs, default \"\"")
    destination_location_preceding_statement: Optional[str] = Field(description="The preceding statements immediately before the `statements`. Use \"\" by default")
    destination_location_next_statement: Optional[str] = Field(description="The next statements immediately after the `statements`. Use \"\" by default")
    @field_validator("statements")	
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v

class MoveArgs(BaseModel):
	codebase: str = Field(description="The full source text to edit")
	statements: Union[str, List[str]] = Field(description="Snippet(s) to move")
	# source_function: str = Field(description="The name of function where the statements come from, default \"\"")
	# source_location_preceding_statement: str = Field(description="Snippets before the statements before moving")
	# source_location_next_statement: str = Field(description="Snippets after the statements before moving")
	destination_function: Optional[str] = Field(description="The name of function where the statements move to, default \"\"")
	destination_location_preceding_statement: Optional[str] = Field(description="The preceding statements immediately before the `statements` in its new location. Use \"\" by default")
	destination_location_next_statement: Optional[str] = Field(description="The next statements immediately after the `statements` in its new location. Use \"\" by default.")
	@field_validator("statements")	
	@classmethod
	def _normalize_str_or_list(cls, v):
		if isinstance(v, list):
			return "\n".join(v)
		return v

class ReplaceArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    old_statement: Union[str, List[str]] = Field(description="Statement to replace")
    new_statement: Union[str, List[str]] = Field(description="Replacement statement")
    destination_function: Optional[str] = Field(description="The name of function where the replacement occurs, default \"\"")
    destination_location_preceding_statement: Optional[str] = Field(description="The preceding statements immediately before the `old_statement`. Use \"\" by default")
    destination_location_next_statement: Optional[str] = Field(description="The next statements immediately after the `old_statement`. Use \"\" by default")

    @field_validator("old_statement", "new_statement")
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v
    
class RenameArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    old_name: str = Field(description="Old name of an identifier, a variable, an API, or a member field")
    new_name: str = Field(description="New name of an identifier, a variable, an API, or a member field")

class IfGuardArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    statements: Union[str, List[str]] = Field(description="The statements to guard with checks")
    guard: str = Field(description="Boolean guard condition to apply")

    @field_validator("statements", "guard")
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v

class IfGuardModArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    if_statement: str = Field(description="an if-statement to modify")
    new_guard: str = Field(description="New guard condition to apply")

    @field_validator("if_statement", "new_guard")
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v

class IfGuardSimArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    if_statement: Union[str, List[str]] = Field(description="an if-statement to modify")
   
    @field_validator("if_statement")
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v
    
@dataclass
class Edit:
	start: int
	end: int
	replacement: bytes

def parse(src: bytes):
	LANG_C = get_language("c")
	parser = Parser()
	parser.set_language(LANG_C)
	return parser.parse(src)

def find_nodes_by_code(tree, src: bytes, code: str, loc_type: str = LOC_EXACT) -> List[TreeCursor]:
	"""Find all nodes in the tree whose source matches code (stripped).

	Returns a list of nodes in preorder.
	loc_type can be 'before' (node startswith code), 'after' (endswith code),
	or 'exact' (exact match). Default is 'exact'.
	"""
	# print("code:", code)
	# print("loc_type:", loc_type)
	code_bytes = code.strip().encode()
	matches = []
	
	def cursor_walk(cursor: TreeCursor):
		nonlocal code_bytes
		try:
			node = cursor.node 
			node_bytes = src[node.start_byte:node.end_byte].strip()
			node_bytes = b" ".join(node_bytes.split())
			code_bytes = b" ".join(code_bytes.split())
		except Exception:
			node_bytes = b""
		
		if loc_type == LOC_EXACT:
			if node_bytes == code_bytes:
				matches.append(cursor.copy())
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
				"case_statement",
				"switch_statement",
				"labeled_statement",
				"goto_statement"
			}
			if loc_type == IS_preceding_statement:
				if node_bytes.endswith(code_bytes) and (node.type in allowed_types or node.type.endswith("_statement")):
					matches.append(cursor.copy())
					return 
     
			if loc_type == IS_NEXT_STATEMENT or loc_type == IS_preceding_statement or loc_type == LOC_ROUGH:
				# if node.type == "if_statement":
				# 	print(node.type, node.text, code_bytes.decode())
				if node_bytes.startswith(code_bytes) and (node.type in allowed_types or node.type.endswith("_statement")):
					matches.append(cursor.copy())
					return 
			else:
				return  

		if cursor.goto_first_child():
			cursor_walk(cursor)
			while cursor.goto_next_sibling():
				cursor_walk(cursor)
			cursor.goto_parent()

	# walk(tree.root_node)
	cursor: TreeCursor = tree.walk()
	cursor_walk(cursor)
	return matches

def apply_edits(src: bytes, edits):
	"""Apply edits to src and return modified bytes.

	Improvements over the simple implementation:
	- Remove exact-duplicate edits.
	- Merge multiple insertions at the same position (start==end) by
	  concatenating their replacements in the original order.
	- Detect overlapping non-insert edits and raise ValueError to avoid
	  producing duplicated or unexpected output.

	The edits are applied from end->start to keep original byte offsets.
	"""
	if not edits:
		return src

	# Remove exact duplicates while preserving order
	seen = set()
	unique_edits = []
	for e in edits:
		key = (e.start, e.end, e.replacement)
		if key in seen:
			continue
		seen.add(key)
		unique_edits.append(e)

	# Group insertions (start==end) by position, preserving original order
	inserts = {}
	non_inserts = []
	for e in unique_edits:
		if e.start == e.end:
			inserts.setdefault(e.start, []).append(e.replacement)
		else:
			non_inserts.append(e)

	# Build merged edits list: non-inserts plus single inserts per position
	merged = list(non_inserts)
	for pos, reps in inserts.items():
		merged.append(Edit(pos, pos, b"".join(reps)))

	# Validate non-overlap among non-insert edits
	ranges = sorted([ (e.start, e.end) for e in merged if e.start != e.end ], key=lambda t: t[0])
	for i in range(len(ranges)-1):
		if ranges[i][1] > ranges[i+1][0]:
			raise ValueError(f"Overlapping edits detected: {ranges[i]} overlaps {ranges[i+1]}")

	# Apply edits from end to start
	edits_sorted = sorted(merged, key=lambda e: e.start, reverse=True)
	out = bytearray(src)
	for e in edits_sorted:
		out[e.start:e.end] = e.replacement
	return bytes(out)

def insert(dsl: InsertArgs) -> str:
	"""
	Apply DSL edits to C code source.
	DSL format: {"strategy": [Rule, ...]}
	"""
	src = dsl.codebase.encode()
	tree = parse(src)
	edits = []
	node_code = dsl.statements
	if isinstance(node_code, list):
		node_code = "\n".join(node_code)
	node_code = str(node_code).strip()

	prev_loc_nodes: List[TreeCursor] = []
	next_loc_nodes: List[TreeCursor] = []
	if dsl.destination_location_preceding_statement:
		prev_statement_code_src = str(dsl.destination_location_preceding_statement).strip().encode()
		prev_statements = parse(prev_statement_code_src).root_node.children
		if len(prev_statements) == 0:
			pass 
		else:
			prev_loc_nodes = find_nodes_by_code(tree, src, prev_statements[-1].text.decode(), loc_type=IS_preceding_statement)

	if dsl.destination_location_next_statement:
		next_statement_code_src = str(dsl.destination_location_next_statement).strip().encode()
		next_statements = parse(next_statement_code_src).root_node.children
		if len(next_statements) == 0:
			pass 
		else:
			next_loc_nodes = find_nodes_by_code(tree, src, next_statements[0].text.decode(),  loc_type=IS_NEXT_STATEMENT)
	
	
	if prev_loc_nodes and next_loc_nodes:
		for prev_node_cursor, next_node_cursor in zip(prev_loc_nodes, next_loc_nodes):
			if not contain_test(prev_node_cursor, next_node_cursor):
				# saved_prev_node_cursor = prev_node_cursor.copy()
				# if prev_node_cursor.goto_next_sibling():
				# 	if prev_node_cursor.node == next_node_cursor.node:
				# 		prev_node_cursor.reset_to(saved_prev_node_cursor)
				if is_adjacent(src, prev_node_cursor, next_node_cursor):
						edits.append(Edit(prev_node_cursor.node.end_byte, next_node_cursor.node.start_byte, b"\n" + node_code.encode() + b"\n"))
			else:
				edits.append(Edit(next_node_cursor.node.start_byte, next_node_cursor.node.start_byte, b"\n" + node_code.encode() + b"\n"))
    
	elif prev_loc_nodes:
		prev_node_code = dsl.destination_location_preceding_statement.strip()
		if prev_node_code == "{" or prev_node_code == "}":
			pass 
		else:
			for prev_node_cursor in prev_loc_nodes:
				edits.append(Edit(prev_node_cursor.node.end_byte, prev_node_cursor.node.end_byte, b"\n" + node_code.encode() + b"\n"))
	elif next_loc_nodes:
		next_node_code = dsl.destination_location_next_statement.strip()
		if next_node_code == "{" or next_node_code == "}":
			pass 
		else:
			for next_node_cursor in next_loc_nodes:
				edits.append(Edit(next_node_cursor.node.start_byte, next_node_cursor.node.start_byte, b"\n" + node_code.encode() + b"\n"))
    
	if edits:
		src = apply_edits(src, edits)
 
	return src.decode()


def remove(dsl: RemoveArgs) -> str:
	"""
	Apply DSL edits to C code source.
	DSL format: {"strategy": [Rule, ...]}
	"""
	src = dsl.codebase.encode()
	tree = parse(src)
	node_code = dsl.statements
	# node_code may comprise multiple statements separated by newlines
	if isinstance(node_code, list):
		node_code = "\n".join(node_code)
	node_code_src = str(node_code).strip().encode()
	statements = parse(node_code_src).root_node.children
	if len(statements) == 0:
		return src.decode()
	edits = []
	prev_loc_nodes: List[TreeCursor] = []
	next_loc_nodes: List[TreeCursor] = []
	
	if dsl.destination_location_preceding_statement:
		prev_statement_code_src = str(dsl.destination_location_preceding_statement).strip().encode()
		prev_statements = parse(prev_statement_code_src).root_node.children
		if len(prev_statements) == 0:
			pass 
		else:
			prev_loc_nodes = find_nodes_by_code(tree, src, prev_statements[-1].text.decode(), loc_type=IS_preceding_statement)

	if dsl.destination_location_next_statement:
		next_statement_code_src = str(dsl.destination_location_next_statement).strip().encode()
		next_statements = parse(next_statement_code_src).root_node.children
		if len(next_statements) == 0:
			pass 
		else:
			next_loc_nodes = find_nodes_by_code(tree, src, next_statements[0].text.decode(),  loc_type=IS_NEXT_STATEMENT)
	

	first_statement = statements[0]
	first_statement_candidates: List[TreeCursor] = find_nodes_by_code(tree, src, first_statement.text.decode(), loc_type=LOC_EXACT)
	
  
	if first_statement_candidates:
		# find matched code blocks of the removed statements
		matched_statement_nodes = []
		for first_statement_node_cursor in first_statement_candidates:
			statement_node_cursor = first_statement_node_cursor.copy()
			size = len(statements) 
			index = 1
			saved_statement_node_cursor = statement_node_cursor.copy()
			while statement_node_cursor.goto_next_sibling() and index < size:
				normalized_candidate_statement_code = " ".join(statement_node_cursor.node.text.decode().split())
				normalized_statement_code = " ".join(statements[index].text.decode().split())
				saved_statement_node_cursor = statement_node_cursor.copy()
				if normalized_candidate_statement_code != normalized_statement_code:
					break 
				index += 1
				if index == size:
					break
 
			if index == size:
				matched_statement_nodes.append([first_statement_node_cursor.copy(), saved_statement_node_cursor])
		
		
		if matched_statement_nodes:
			if prev_loc_nodes and next_loc_nodes:
				for prev_node_cursor, next_node_cursor in zip(prev_loc_nodes, next_loc_nodes):
					if not contain_test(prev_node_cursor, next_node_cursor):
						for matched_statement_node in matched_statement_nodes:
							first_statement_node_cursor = matched_statement_node[0]
							if contain_test(prev_node_cursor, first_statement_node_cursor) or is_adjacent(src, prev_node_cursor, first_statement_node_cursor):
									last_statement_node_cursor = matched_statement_node[1]
									if is_adjacent(src, last_statement_node_cursor, next_node_cursor):
											edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
           
						# if prev_node_cursor.goto_next_sibling():
						# 	for matched_statement_node in matched_statement_nodes:
						# 		first_statement_node_cursor = matched_statement_node[0]
						# 		if prev_node_cursor.node == first_statement_node_cursor.node:
						# 			last_statement_node_cursor = matched_statement_node[1]
						# 			saved_last_statement_node_cursor = last_statement_node_cursor.copy()
						# 			if last_statement_node_cursor.goto_next_sibling():
						# 				if last_statement_node_cursor.node == next_node_cursor.node:
						# 					last_statement_node_cursor.reset_to(saved_last_statement_node_cursor)
						# 					edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
					else:
						for matched_statement_node in matched_statement_nodes:
							first_statement_node_cursor = matched_statement_node[0]
							last_statement_node_cursor = matched_statement_node[1]
							# saved_last_statement_node_cursor = last_statement_node_cursor.copy()
							# if last_statement_node_cursor.goto_next_sibling():
							# 	if last_statement_node_cursor.node == next_node_cursor.node:
							# 		last_statement_node_cursor.reset_to(saved_last_statement_node_cursor)
							if is_adjacent(src, last_statement_node_cursor, next_node_cursor):
									edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
			
			elif prev_loc_nodes:
					for prev_node_cursor in prev_loc_nodes:
						# if prev_node_cursor.goto_next_sibling():
							for matched_statement_node in matched_statement_nodes:
								first_statement_node_cursor = matched_statement_node[0]
								last_statement_node_cursor = matched_statement_node[1]
								# if prev_node_cursor.node == first_statement_node_cursor.node:
								if is_adjacent(src, prev_node_cursor, first_statement_node_cursor) or contain_test(prev_node_cursor, first_statement_node_cursor):
									edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
			elif next_loc_nodes:
					for next_node_cursor in next_loc_nodes:
						for matched_statement_node in matched_statement_nodes:
							first_statement_node_cursor = matched_statement_node[0]
							last_statement_node_cursor = matched_statement_node[1]
							# saved_last_statement_node_cursor = last_statement_node_cursor.copy()
							# if last_statement_node_cursor.goto_next_sibling():
							# 	if last_statement_node_cursor.node == next_node_cursor.node:
							# 		last_statement_node_cursor.reset_to(saved_last_statement_node_cursor)
							if is_adjacent(src, last_statement_node_cursor, next_node_cursor):
									edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
			
	if edits:
		src = apply_edits(src, edits)
	
	return src.decode()

def move(dsl: MoveArgs) -> str:
    # Move a statement from one place to anther place in the codebase
	src = dsl.codebase.encode()
	tree = parse(src)
	node_code = dsl.statements
	# node_code may comprise multiple statements separated by newlines
	if isinstance(node_code, list):
		node_code = "\n".join(node_code)
	node_code_src = str(node_code).strip().encode()
	statements = parse(node_code_src).root_node.children
	if len(statements) == 0:
		return src.decode()

	edits = []
	prev_loc_nodes: List[TreeCursor] = []
	next_loc_nodes: List[TreeCursor] = []
	if dsl.destination_location_preceding_statement:
		prev_statement_code_src = str(dsl.destination_location_preceding_statement).strip().encode()
		prev_statements = parse(prev_statement_code_src).root_node.children
		if len(prev_statements) == 0:
			pass 
		else:
			prev_loc_nodes = find_nodes_by_code(tree, src, prev_statements[-1].text.decode(), loc_type=IS_preceding_statement)

	if dsl.destination_location_next_statement:
		next_statement_code_src = str(dsl.destination_location_next_statement).strip().encode()
		next_statements = parse(next_statement_code_src).root_node.children
		if len(next_statements) == 0:
			pass 
		else:
			next_loc_nodes = find_nodes_by_code(tree, src, next_statements[0].text.decode(),  loc_type=IS_NEXT_STATEMENT)
	
	
	# we require very precise destination location
	if not prev_loc_nodes and not next_loc_nodes:
		return src.decode()
	if prev_loc_nodes and next_loc_nodes:
		if len(prev_loc_nodes) != 1 or len(next_loc_nodes) != 1:
			return src.decode()
	elif prev_loc_nodes:
		if len(prev_loc_nodes) != 1:
			return src.decode()
	elif next_loc_nodes:
		if len(next_loc_nodes) != 1:
			return src.decode()

	first_statement = statements[0]
	first_statement_candidates: List[TreeCursor] = find_nodes_by_code(tree, src, first_statement.text.decode(), loc_type=LOC_EXACT)
	
	if first_statement_candidates:
		# find matched code blocks of the removed statements
		matched_statement_nodes = []
		for first_statement_node_cursor in first_statement_candidates:
			statement_node_cursor = first_statement_node_cursor.copy()
			size = len(statements) 
			index = 1
			saved_statement_node_cursor = statement_node_cursor.copy()
			while statement_node_cursor.goto_next_sibling() and index < size:
				normalized_candidate_statement_code = " ".join(statement_node_cursor.node.text.decode().split())
				normalized_statement_code = " ".join(statements[index].text.decode().split())
				saved_statement_node_cursor = statement_node_cursor.copy()
				if normalized_candidate_statement_code != normalized_statement_code:
					break 
				index += 1
				if index == size:
					break
 
			if index == size:
				matched_statement_nodes.append([first_statement_node_cursor.copy(), saved_statement_node_cursor])
		
		# we only allow one code block candidate
		if matched_statement_nodes:
			if len(matched_statement_nodes) != 1:
				pass 
			else:
				first_statement_node_cursor = matched_statement_nodes[0][0]
				last_statement_node_cursor = matched_statement_nodes[0][1]

				if prev_loc_nodes and next_loc_nodes:
					prev_loc_node = prev_loc_nodes[0]
					next_loc_node = next_loc_nodes[0]
					if not contain_test(prev_loc_node, first_statement_node_cursor):
						edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
						edits.append(Edit(prev_loc_node.node.end_byte, next_loc_node.node.end_byte, b"\n" + node_code_src + b"\n"))
					else:
						edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
						edits.append(Edit(next_loc_node.node.start_byte, next_loc_node.node.start_byte, b"\n" + node_code_src + b"\n"))
				elif prev_loc_nodes:
					prev_loc_node = prev_loc_nodes[0]
					edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
					edits.append(Edit(prev_loc_node.node.end_byte, prev_loc_node.node.end_byte, b"\n" + node_code_src + b"\n"))
				elif next_loc_nodes:
					next_loc_node = next_loc_nodes[0]
					edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n"))
					edits.append(Edit(next_loc_node.node.start_byte, next_loc_node.node.start_byte, b"\n" + node_code_src + b"\n"))
	
	if edits:
		src = apply_edits(src, edits)
	
	return src.decode()

def replace(dsl: ReplaceArgs):
	"""Replace old_statement(s) with new_statement(s) near the designated location."""
	src = dsl.codebase.encode()
	tree = parse(src)
	node_code = dsl.old_statement
	new_code = dsl.new_statement
	if isinstance(new_code, list):
		new_code = "\n".join(new_code)
	
	# replace = remove old_stmt + insert new_stmt
	# node_code may comprise multiple statements separated by newlines
	if isinstance(node_code, list):
		node_code = "\n".join(node_code)
	node_code_src = str(node_code).strip().encode()
	statements = parse(node_code_src).root_node.children
	if len(statements) == 0:
		return src.decode()
	edits = []
	prev_loc_nodes: List[TreeCursor] = []
	next_loc_nodes: List[TreeCursor] = []
	if dsl.destination_location_preceding_statement:
		prev_statement_code_src = str(dsl.destination_location_preceding_statement).strip().encode()
		prev_statements = parse(prev_statement_code_src).root_node.children
		if len(prev_statements) == 0:
			pass 
		else:
			prev_loc_nodes = find_nodes_by_code(tree, src, prev_statements[-1].text.decode(), loc_type=IS_preceding_statement)

	if dsl.destination_location_next_statement:
		next_statement_code_src = str(dsl.destination_location_next_statement).strip().encode()
		next_statements = parse(next_statement_code_src).root_node.children
		if len(next_statements) == 0:
			pass 
		else:
			next_loc_nodes = find_nodes_by_code(tree, src, next_statements[0].text.decode(),  loc_type=IS_NEXT_STATEMENT)
	

	first_statement = statements[0]
	first_statement_candidates: List[TreeCursor] = find_nodes_by_code(tree, src, first_statement.text.decode(), loc_type=LOC_EXACT)
	
	# print("len(prev_loc_nodes):", len(prev_loc_nodes))
	# print("len(next_loc_nodes):", len(next_loc_nodes))
	# print("len(first_statement_candidates):", len(first_statement_candidates))
  
	if first_statement_candidates:
		# find matched code blocks of the removed statements
		matched_statement_nodes = []
		for first_statement_node_cursor in first_statement_candidates:
			statement_node_cursor = first_statement_node_cursor.copy()
			size = len(statements) 
			index = 1
			saved_statement_node_cursor = statement_node_cursor.copy()
			while statement_node_cursor.goto_next_sibling() and index < size:
				normalized_candidate_statement_code = " ".join(statement_node_cursor.node.text.decode().split())
				normalized_statement_code = " ".join(statements[index].text.decode().split())
				saved_statement_node_cursor = statement_node_cursor.copy()
				if normalized_candidate_statement_code != normalized_statement_code:
					break 
				index += 1
				if index == size:
					break
 
			if index == size:
				matched_statement_nodes.append([first_statement_node_cursor.copy(), saved_statement_node_cursor])
		
		if matched_statement_nodes:
			if prev_loc_nodes and next_loc_nodes:
				for prev_node_cursor, next_node_cursor in zip(prev_loc_nodes, next_loc_nodes):
					if not contain_test(prev_node_cursor, next_node_cursor):
						for matched_statement_node in matched_statement_nodes:
							first_statement_node_cursor = matched_statement_node[0]
							if contain_test(prev_node_cursor, first_statement_node_cursor) or is_adjacent(src, prev_node_cursor, first_statement_node_cursor):
									last_statement_node_cursor = matched_statement_node[1]
									if is_adjacent(src, last_statement_node_cursor, next_node_cursor):
											edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n" + new_code.encode() + b"\n"))
           
						# if prev_node_cursor.goto_next_sibling():
						# 	for matched_statement_node in matched_statement_nodes:
						# 		first_statement_node_cursor = matched_statement_node[0]
						# 		if prev_node_cursor.node == first_statement_node_cursor.node:
						# 			last_statement_node_cursor = matched_statement_node[1]
						# 			saved_last_statement_node_cursor = last_statement_node_cursor.copy()
						# 			if last_statement_node_cursor.goto_next_sibling():
						# 				if last_statement_node_cursor.node == next_node_cursor.node:
						# 					last_statement_node_cursor.reset_to(saved_last_statement_node_cursor)
						# 					edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n" + new_code.encode() + b"\n"))
					else:
						for matched_statement_node in matched_statement_nodes:
							first_statement_node_cursor = matched_statement_node[0]
							last_statement_node_cursor = matched_statement_node[1]
							# saved_last_statement_node_cursor = last_statement_node_cursor.copy()
							# if last_statement_node_cursor.goto_next_sibling():
							# 		if last_statement_node_cursor.node == next_node_cursor.node:
							# 			last_statement_node_cursor.reset_to(saved_last_statement_node_cursor)
							if is_adjacent(src, last_statement_node_cursor, next_node_cursor):
										edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n" + new_code.encode() + b"\n"))
			elif prev_loc_nodes:
					for prev_node_cursor in prev_loc_nodes:
						# if prev_node_cursor.goto_next_sibling():
							for matched_statement_node in matched_statement_nodes:
								first_statement_node_cursor = matched_statement_node[0]
								last_statement_node_cursor = matched_statement_node[1]
								# if prev_node_cursor.node == first_statement_node_cursor.node:
								if is_adjacent(src, prev_node_cursor, first_statement_node_cursor) or contain_test(prev_node_cursor, first_statement_node_cursor):
									edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n" + new_code.encode() + b"\n"))
			elif next_loc_nodes:
					for next_node_cursor in next_loc_nodes:
						for matched_statement_node in matched_statement_nodes:
							first_statement_node_cursor = matched_statement_node[0]
							last_statement_node_cursor = matched_statement_node[1]
							# saved_last_statement_node_cursor = last_statement_node_cursor.copy()
							# if last_statement_node_cursor.goto_next_sibling():
							# 	if last_statement_node_cursor.node == next_node_cursor.node:
							# 		last_statement_node_cursor.reset_to(saved_last_statement_node_cursor)
							if is_adjacent(src, last_statement_node_cursor, next_node_cursor):
									edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, b"\n" + new_code.encode() + b"\n"))
			
	if edits:
		src = apply_edits(src, edits)
	
	return src.decode()
 

def rename(dsl: RenameArgs):
	"""Rename an identifier, a variable, an API, or a member field."""
	src = dsl.codebase.encode()
	tree = parse(src)

	old_name = dsl.old_name.strip()
	new_name = dsl.new_name.strip()
	import re
	if re.match(r"^\w+$", old_name) and re.match(r"^\w+$", new_name):
		# find all candidate nodes matching the old snippet (exact match)
		candidates = find_nodes_by_code(tree, src, old_name, loc_type=LOC_EXACT)
		if not candidates:
			return src.decode()
		edits = []
		for node_cursor in candidates:
			edits.append(Edit(node_cursor.node.start_byte, node_cursor.node.end_byte, new_name.encode()))
		if edits:
			src = apply_edits(src, edits)
	
	return src.decode()


def ifguard_modify(dsl: IfGuardModArgs) -> str:
	"""Modify the guard (condition) of an existing if-statement.

	Returns the modified source as a string. If the target if-statement
	can't be found or the AST shape is unexpected, returns the original
	source unchanged.
	"""
	src = dsl.codebase.encode()
	tree = parse(src)
	
	edits = []

	# Inputs may be lists (normalized by pydantic, but be defensive)
	if_statement = dsl.if_statement
	new_guard = dsl.new_guard
	if isinstance(if_statement, list):
		if_statement = "\n".join(if_statement)
	if isinstance(new_guard, list):
		new_guard = "\n".join(new_guard)
	if_statement = str(if_statement).strip()
	new_guard = str(new_guard).strip()

	if not if_statement:
		return src.decode()

	# Find the if statement node in the AST
	if_nodes = find_nodes_by_code(tree, src, if_statement, loc_type=LOC_ROUGH)
	if not if_nodes:
		# print("if_statement not found in the AST", if_statement)
		return src.decode()

	for if_node_cursor in if_nodes:
		if_node = if_node_cursor.node
		condition = if_node.child_by_field_name("condition")
		if condition is None:
			continue

		# Build replacement bytes and apply edit
		replacement = b"(" + new_guard.encode() + b")"
		edits.append(Edit(condition.start_byte, condition.end_byte, replacement))
	
	if edits:
		src = apply_edits(src, edits)
	
	return src.decode()

def if_guard(dsl: IfGuardArgs):
	"""Guard existing statements with checks following pattern: if(check){ stm ...}

	This function finds the statement(s) in `dsl.statements` and wraps them
	with an if(<guard>) { ... } block, preserving indentation. Returns the
	modified source as a string. If no match is found, returns original source.
	"""
	src = dsl.codebase.encode()
	tree = parse(src)
	
	guard = dsl.guard
	if isinstance(guard, list):
		guard = "\n".join(guard)
	guard = str(guard).strip()
 
	node_code = dsl.statements
	# node_code may comprise multiple statements separated by newlines
	if isinstance(node_code, list):
		node_code = "\n".join(node_code)
	node_code_src = str(node_code).strip().encode()
	statements = parse(node_code_src).root_node.children
	if len(statements) == 0:
		return src.decode()

	edits = []
	
	first_statement = statements[0]
	first_statement_candidates: List[TreeCursor] = find_nodes_by_code(tree, src, first_statement.text.decode(), loc_type=LOC_EXACT)
	
	if first_statement_candidates:
		# find matched code blocks of the removed statements
		matched_statement_nodes = []
		for first_statement_node_cursor in first_statement_candidates:
			statement_node_cursor = first_statement_node_cursor.copy()
			size = len(statements) 
			index = 1
			saved_statement_node_cursor = statement_node_cursor.copy()
			while statement_node_cursor.goto_next_sibling() and index < size:
				normalized_candidate_statement_code = " ".join(statement_node_cursor.node.text.decode().split())
				normalized_statement_code = " ".join(statements[index].text.decode().split())
				saved_statement_node_cursor = statement_node_cursor.copy()
				if normalized_candidate_statement_code != normalized_statement_code:
					break 
				index += 1
				if index == size:
					break
 
			if index == size:
				matched_statement_nodes.append([first_statement_node_cursor.copy(), saved_statement_node_cursor])
		
		
		# we allow multiple code blocks
		for matched_statement_node in matched_statement_nodes:
				first_statement_node_cursor = matched_statement_node[0]
				last_statement_node_cursor = matched_statement_node[1]
				open_bytes =  b"if (" + guard.encode() + b") {\n"
				close_bytes =  b"}\n"
				if_statements = open_bytes + src[first_statement_node_cursor.node.start_byte:last_statement_node_cursor.node.end_byte] + close_bytes
			
				edits.append(Edit(first_statement_node_cursor.node.start_byte, last_statement_node_cursor.node.end_byte, if_statements))
	
	if edits:
		src = apply_edits(src, edits)
	
	return src.decode()

def test_insert():
	 # Example usage
	# codebase = """
	# void foo() {
	# 	int x = 0;
	# 	x += 1;
	# }
	# """
	# statements = "x += 2;"
	# destination_function = "foo"
	# destination_location_preceding_statement = "x += 1;"
	# destination_location_next_statement = ""

	# dsl = InsertArgs(
	# 	codebase=codebase,
	# 	statements=statements,
	# 	destination_function=destination_function,
	# 	destination_location_preceding_statement=destination_location_preceding_statement,
	# 	destination_location_next_statement=destination_location_next_statement
	# )
	
	

	# modified_code = insert(dsl)
	# print("Modified Code:\n", modified_code)
 
	payload = r'''{
  "statements": [
    "int\t    cmp;"
  ],
  "destination_function": "help_compare",
  "destination_location_preceding_statement": "char    *p1;\n    char    *p2;",
  "destination_location_next_statement": "p1 = *(char **)s1 + strlen(*(char **)s1) + 1;\n    p2 = *(char **)s2 + strlen(*(char **)s2) + 1;",
  "codebase": "static int\nhelp_compare(const void *s1, const void *s2)\n{\n    char    *p1;\n    char    *p2;\n    p1 = *(char **)s1 + strlen(*(char **)s1) + 1;\n    p2 = *(char **)s2 + strlen(*(char **)s2) + 1;\n    return strcmp(p1, p2);\n}"
}'''
	import json 
	json_payload = json.loads(payload)
	
	dsl = InsertArgs(
		codebase=json_payload["codebase"],
		statements=json_payload["statements"],
		destination_function=json_payload["destination_function"],
		destination_location_preceding_statement=json_payload["destination_location_preceding_statement"],
		destination_location_next_statement=json_payload["destination_location_next_statement"]
	)
	
	modified_code = insert(dsl)
	print('\n--- insert case ---')
	print("Modified Code:\n", modified_code)

def test_remove():
	 # Example usage
	codebase = """
	void foo() {
		int x = 0;
		x += 1;
		x += 2;
	}
	"""
	statements = "x += 1;x += 2;"
	destination_function = "foo"
	destination_location_preceding_statement = "int x = 0;"
	destination_location_next_statement = ""		
	dsl = RemoveArgs(
		codebase=codebase,
		statements=statements,
		destination_function=destination_function,
		destination_location_preceding_statement=destination_location_preceding_statement,
		destination_location_next_statement=destination_location_next_statement
	)
	modified_code = remove(dsl)
	print('\n--- remove case ---')
	print("Modified Code:\n", modified_code)

def test_ifguard_modify():
	# Example usage
	# codebase = """
	# void foo() {
	# 	int x = 0;
	# 	if (x > 0) {
	# 		x += 1;
	# 	}
	# }
	# """
	# if_statement = "if (x > 0) {"
	# new_guard = "x <= 0"

	# dsl = IfGuardModArgs(
	# 	codebase=codebase,
	# 	if_statement=if_statement,
	# 	new_guard=new_guard
	# )

	# modified_code = ifguard_modify(dsl)
	# print("Modified Code:\n", modified_code)
 
	payload = r"""{
  "if_statement": "if (idx != MENU_INDEX_INVALID && menu->strings[idx] != NULL)\n    {\n\tif (eap == NULL\n#ifdef FEAT_EVAL\n\t\t|| current_sctx.sc_sid != 0\n#endif\n\t   )\n\t{\n\t\tsave_state_T save_state;\n\t\t++ex_normal_busy;\n\t\tif (save_current_state(&save_state))\n\t\t\texec_normal_cmd(menu->strings[idx], menu->noremap[idx],\n\t\t\t\t\t\t   menu->silent[idx]);\n\t\trestore_current_state(&save_state);\n\t\t--ex_normal_busy;\n\t}\n\telse\n\t    ins_typebuf(menu->strings[idx], menu->noremap[idx], 0,\n\t\t\t     TRUE, menu->silent[idx]);\n    }",
  "new_guard": "idx != MENU_INDEX_INVALID && menu->strings[idx] != NULL && (menu->modes & (1 << idx))",
  "codebase": "if (idx < 0)\n    {\n\tif (restart_edit\n#ifdef FEAT_EVAL\n\t\t&& !current_sctx.sc_sid\n#endif\n\t\t)\n\t{\n\t    idx = MENU_INDEX_INSERT;\n\t}\n#ifdef FEAT_TERMINAL\n\telse if (term_use_loop())\n\t{\n\t    idx = MENU_INDEX_TERMINAL;\n\t}\n#endif\n\telse if (VIsual_active)\n\t{\n\t    idx = MENU_INDEX_VISUAL;\n\t}\n\telse if (eap != NULL && eap->addr_count)\n\t{\n\t    pos_T\ttpos;\n\t    idx = MENU_INDEX_VISUAL;\n\t    if ((curbuf->b_visual.vi_start.lnum == eap->line1)\n\t\t    && (curbuf->b_visual.vi_end.lnum) == eap->line2)\n\t    {\n\t\tVIsual_mode = curbuf->b_visual.vi_mode;\n\t\ttpos = curbuf->b_visual.vi_end;\n\t\tcurwin->w_cursor = curbuf->b_visual.vi_start;\n\t\tcurwin->w_curswant = curbuf->b_visual.vi_curswant;\n\t    }\n\t    else\n\t    {\n\t\tVIsual_mode = 'V';\n\t\tcurwin->w_cursor.lnum = eap->line1;\n\t\tcurwin->w_cursor.col = 1;\n\t\ttpos.lnum = eap->line2;\n\t\ttpos.col = MAXCOL;\n\t\ttpos.coladd = 0;\n\t    }\n\t    VIsual_active = TRUE;\n\t    VIsual_reselect = TRUE;\n\t    check_cursor();\n\t    VIsual = curwin->w_cursor;\n\t    curwin->w_cursor = tpos;\n\t    check_cursor();\n\t    if (*p_sel == 'e' && gchar_cursor() != NUL)\n\t\t++curwin->w_cursor.col;\n\t}\n    }\n    if (idx == -1 || eap == NULL)\n\tidx = MENU_INDEX_NORMAL;\n    if (idx != MENU_INDEX_INVALID && menu->strings[idx] != NULL)\n    {\n\tif (eap == NULL\n#ifdef FEAT_EVAL\n\t\t|| current_sctx.sc_sid != 0\n#endif\n\t   )\n\t{\n\t    save_state_T save_state;\n\t    ++ex_normal_busy;\n\t    if (save_current_state(&save_state))\n\t\texec_normal_cmd(menu->strings[idx], menu->noremap[idx],\n\t\t\t\t\t\t\t   menu->silent[idx]);\n\t    restore_current_state(&save_state);\n\t    --ex_normal_busy;\n\t}\n\telse\n\t    ins_typebuf(menu->strings[idx], menu->noremap[idx], 0,\n\t\t\t\t\t\t     TRUE, menu->silent[idx]);\n    }\n    else if (eap != NULL)\n    {\n\tchar_u\t*mode;\n\tswitch (idx)\n\t{\n\t    case MENU_INDEX_VISUAL:\n\t\tmode = (char_u *)\"Visual\";\n\t\tbreak;\n\t    case MENU_INDEX_SELECT:\n\t\tmode = (char_u *)\"Select\";\n\t\tbreak;\n\t    case MENU_INDEX_OP_PENDING:\n\t\tmode = (char_u *)\"Op-pending\";\n\t\tbreak;\n\t    case MENU_INDEX_TERMINAL:\n\t\tmode = (char_u *)\"Terminal\";\n\t\tbreak;\n\t    case MENU_INDEX_INSERT:\n\t\tmode = (char_u *)\"Insert\";\n\t\tbreak;\n\t    case MENU_INDEX_CMDLINE:\n\t\tmode = (char_u *)\"Cmdline\";\n\t\tbreak;\n\t    default:\n\t\tmode = (char_u *)\"Normal\";\n\t}\n\tsemsg(_(\"E335: Menu not defined for %s mode\"), mode);\n    }"
}"""
	import json 
	json_payload = json.loads(payload)
	
	dsl4 = IfGuardModArgs(
		codebase=json_payload["codebase"],
		if_statement=json_payload["if_statement"],
		new_guard=json_payload["new_guard"]
	)
	print('\n--- ifguard_modify case ---')
	print(ifguard_modify(dsl4))
 
def test_ifguard():
	payload = r'''
    {
    "codebase": "# ifdef FEAT_LINEBREAK\n\t\t    else\n\t\t    {\n\t\t\tchar_u\t*p;\n\t\t\tint\tlen;\n\t\t\tint\ti;\n\t\t\tint\tsaved_nextra = wlv.n_extra;\n# ifdef FEAT_CONCEAL\n\t\t\tif (wlv.vcol_off > 0)\n\t\t\t    tab_len += wlv.vcol_off;\n\t\t\tif (wp->w_p_list && wp->w_lcs_chars.tab1\n\t\t\t\t\t\t      && old_boguscols > 0\n\t\t\t\t\t\t      && wlv.n_extra > tab_len)\n\t\t\t    tab_len += wlv.n_extra - tab_len;\n# endif\n\t\t\t \nint tab2_len = mb_char2len(wp->w_lcs_chars.tab2);\n\t\t\tlen = tab_len * tab2_len;\n\t\t\tif (wp->w_lcs_chars.tab3)\n\t\t\t    len += mb_char2len(wp->w_lcs_chars.tab3) - tab2_len;\n\t\t\tif (wlv.n_extra > 0)\n\t\t\t    len += wlv.n_extra - tab_len;\n\t\t\tc = wp->w_lcs_chars.tab1;\n\t\t\tp = alloc(len + 1);\n\t\t\tif (p == NULL)\n\t\t\t    wlv.n_extra = 0;\n\t\t\telse\n\t\t\t{\n\t\t\t    vim_memset(p, ' ', len);\n\t\t\t    p[len] = NUL;\n\t\t\t    vim_free(wlv.p_extra_free);\n\t\t\t    wlv.p_extra_free = p;\n\t\t\t    for (i = 0; i < tab_len; i++)\n\t\t\t    {\n\t\t\t\tint lcs = wp->w_lcs_chars.tab2;\n\t\t\t\tif (*p == NUL)\n\t\t\t\t{\n\t\t\t\t    tab_len = i;\n\t\t\t\t    break;\n\t\t\t\t}\n\t\t\t\tif (wp->w_lcs_chars.tab3 && i == tab_len - 1)\n\t\t\t\t    lcs = wp->w_lcs_chars.tab3;\n\t\t\t\tp += mb_char2bytes(lcs, p);\n\t\t\t\twlv.n_extra += mb_char2len(lcs)\n\t\t\t\t\t\t  - (saved_nextra > 0 ? 1 : 0);\n\t\t\t    }\n\t\t\t    wlv.p_extra = wlv.p_extra_free;\n# ifdef FEAT_CONCEAL\n\t\t\t    if (wlv.vcol_off > 0)\n\t\t\t\twlv.n_extra -= wlv.vcol_off;\n# endif\n\t\t\t}}\n\n\t\t  \n#endif\n#ifdef FEAT_CONCEAL\n\t\t    {\n\t\t\tint vc_saved = wlv.vcol_off;\n\t\t\tFIX_FOR_BOGUSCOLS;\n\t\t\tif (wlv.n_extra == tab_len + vc_saved && wp->w_p_list\n\t\t\t\t\t\t&& wp->w_lcs_chars.tab1)\n\t\t\t    tab_len += vc_saved;\n\t\t    }\n#endif",
    "statements": "int tab2_len = mb_char2len(wp->w_lcs_chars.tab2);\n\t\t\tlen = tab_len * tab2_len;\n\t\t\tif (wp->w_lcs_chars.tab3)\n\t\t\t    len += mb_char2len(wp->w_lcs_chars.tab3) - tab2_len;\n\t\t\tif (wlv.n_extra > 0)\n\t\t\t    len += wlv.n_extra - tab_len;\n\t\t\tc = wp->w_lcs_chars.tab1;\n\t\t\tp = alloc(len + 1);\n\t\t\tif (p == NULL)\n\t\t\t    wlv.n_extra = 0;\n\t\t\telse\n\t\t\t{\n\t\t\t    vim_memset(p, ' ', len);\n\t\t\t    p[len] = NUL;\n\t\t\t    vim_free(wlv.p_extra_free);\n\t\t\t    wlv.p_extra_free = p;\n\t\t\t    for (i = 0; i < tab_len; i++)\n\t\t\t    {\n\t\t\t\tint lcs = wp->w_lcs_chars.tab2;\n\t\t\t\tif (*p == NUL)\n\t\t\t\t{\n\t\t\t\t    tab_len = i;\n\t\t\t\t    break;\n\t\t\t\t}\n\t\t\t\tif (wp->w_lcs_chars.tab3 && i == tab_len - 1)\n\t\t\t\t    lcs = wp->w_lcs_chars.tab3;\n\t\t\t\tp += mb_char2bytes(lcs, p);\n\t\t\t\twlv.n_extra += mb_char2len(lcs)\n\t\t\t\t\t\t  - (saved_nextra > 0 ? 1 : 0);\n\t\t\t    }\n\t\t\t    wlv.p_extra = wlv.p_extra_free;\n# ifdef FEAT_CONCEAL\n\t\t\t    if (wlv.vcol_off > 0)\n\t\t\t\twlv.n_extra -= wlv.vcol_off;\n# endif\n\t\t\t}",
    "guard": "tab_len > 0"
  }
    '''
	import json 
	json_payload = json.loads(payload)
	
	dsl = IfGuardArgs(
		codebase=json_payload["codebase"],
		statements=json_payload["statements"],
		guard=json_payload["guard"]
	)
	print('\n--- ifguard case ---')
	print(if_guard(dsl))
 
def test_move():
    # this test the functionality of move function
	# Case 1: single-statement snippet move
	codebase1 = """
	void foo() {
	    int x = 0;
	    x += 1;
	    x += 2;
	    x += 3;
	}
	"""
	statements1 = "x += 2;"
	dsl1 = MoveArgs(
		codebase=codebase1,
		statements=statements1,
		destination_function="foo",
		destination_location_preceding_statement="x += 3;",
		destination_location_next_statement="",
	)
	print("\n--- test_move case 1: single-statement snippet move ---")
	print(move(dsl1))

	# Case 2: multi-statement snippet move
	codebase2 = """
	void foo() {
	    int x = 0;
	    x += 1;
	    x += 2;
	    x += 3;
	    x += 4;
	}
	"""
	statements2 = "x += 2;\n    x += 3;"
	dsl2 = MoveArgs(
		codebase=codebase2,
		statements=statements2,
		destination_function="foo",
		destination_location_preceding_statement="x += 4;",
		destination_location_next_statement="",
	)
	print("\n--- test_move case 2: multi-statement snippet move ---")
	print(move(dsl2))

	# Case 3: locate source by prev/next markers (no snippet)
	codebase3 = """
	void foo() {
	    int a = 0;
	    int b = 1;
	    int c = 2;
	    return c;
	}
	"""
	dsl3 = MoveArgs(
		codebase=codebase3,
		statements="int b = 1;",
		destination_function="foo",
		destination_location_preceding_statement="int c = 2;",
		destination_location_next_statement="",
	)
	print("\n--- test_move case 3: source by prev/next markers ---")
	print(move(dsl3))

def test_replace():
    # this test the functionality of replace function
	# Case 1: simple single-statement replace
	# codebase1 = """
	# void foo() {
	# 	int x = 0;
	# 	x += 1;
	# 	x += 2;
	# }
	# """
	# old1 = "x += 1;"
	# new1 = "x += 10;"
	# dsl1 = ReplaceArgs(
	# 	codebase=codebase1,
	# 	old_statement=old1,
	# 	new_statement=new1,
	# 	destination_function="foo",
	# 	destination_location_preceding_statement="",
	# 	destination_location_next_statement="",
	# )
	# print('\n--- test_replace case 1: single-statement replace ---')
	# print(replace(dsl1))

	# # Case 2: multi-statement replace
	# codebase2 = """
	# void foo() {
	# 	int x = 0;
	# 	x += 1;
	# 	x += 2;
	# 	x += 3;
	# }
	# """
	# old2 = "x += 1;\n        x += 2;"
	# new2 = "x = x * 2;"
	# dsl2 = ReplaceArgs(
	# 	codebase=codebase2,
	# 	old_statement=old2,
	# 	new_statement=new2,
	# 	destination_function="foo",
	# 	destination_location_preceding_statement="",
	# 	destination_location_next_statement="",
	# )
	# print('\n--- test_replace case 2: multi-statement replace ---')
	# print(replace(dsl2))

	# # Case 3: constrained replace (only after a prev marker)
	# codebase3 = """
	# void foo() {
	# 	int a = 0;
	# 	int b = 1;
	# 	int c = 2;
	# 	b = a + c;
	# }
	# """
	# old3 = "b = a + c;"
	# new3 = "b = a - c;"
	# dsl3 = ReplaceArgs(
	# 	codebase=codebase3,
	# 	old_statement=old3,
	# 	new_statement=new3,
	# 	destination_function="foo",
	# 	destination_location_preceding_statement="int b = 1;",
	# 	destination_location_next_statement="",
	# )
	# print('\n--- test_replace case 3: constrained replace (after prev) ---')
	# print(replace(dsl3))
 
	payload = r"""{
		"codebase": "if (i > 0)\n\t{\n\t    matchidx_T\tprevIdx = matches[i - 1];\n\t    if (currIdx == (prevIdx + 1))\n\t\tscore += SEQUENTIAL_BONUS;\n\t}\n\tif (currIdx > 0)\n\t{\n\t    int\tneighbor;\n\t    int\tcurr;\n\t    int\tneighborSeparator;\n\t    if (has_mbyte)\n\t    {\n\t\twhile (sidx < currIdx)\n\t\t{\n\t\t    neighbor = (*mb_ptr2char)(p);\n\t\t    (void)mb_ptr2char_adv(&p);\n\t\t    sidx++;\n\t\t}\n\t\tcurr = (*mb_ptr2char)(p);\n\t    }\n\t    else\n\t    {\n\t\tneighbor = str[currIdx - 1];\n\t\tcurr = str[currIdx];\n\t    }\n\t    if (vim_islower(neighbor) && vim_isupper(curr))\n\t\tscore += CAMEL_BONUS;\n\t    neighborSeparator = neighbor == '_' || neighbor == ' ';\n\t    if (neighborSeparator)\n\t\tscore += SEPARATOR_BONUS;\n\t}\n\telse\n\t{\n\t    score += FIRST_LETTER_BONUS;\n\t}",
		"old_statement": "int\tneighbor;",
		"new_statement": "int\tneighbor = ' ';",
		"destination_function": "",
		"destination_location_preceding_statement": "if (currIdx > 0)",
		"destination_location_next_statement": "int\tcurr;"
	}"""
	import json 
	json_payload = json.loads(payload)
	
	dsl4 = ReplaceArgs(
		codebase=json_payload["codebase"],
		old_statement=json_payload["old_statement"],
		new_statement=json_payload["new_statement"],
		destination_function=json_payload["destination_function"],
		destination_location_preceding_statement=json_payload["destination_location_preceding_statement"],
		destination_location_next_statement=json_payload["destination_location_next_statement"]
	)
	print('\n--- test_replace case 4: constrained replace (after prev) ---')
	print(replace(dsl4))
 
def test_parse():
	code_snippet = "if (idx != MENU_INDEX_INVALID && menu->strings[idx] != NULL"
	try:
		tree = parse(code_snippet.encode())
		print(tree)
	except:
		import traceback
		traceback.print_exc()
        

if __name__ == "__main__":
	# test_insert()
	# test_remove()
	test_ifguard_modify()
	# test_move()
	# test_replace()
	# test_ifguard()

