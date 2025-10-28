"""
DSL Transformer for C code edits using tree-sitter.
Supports Move, Insert, Remove, Replace actions as described in DSL grammar.
"""
from os import close
import re
import sys
from typing import Union, List
from dataclasses import dataclass
from tree_sitter import Parser, TreeCursor
from tree_sitter_languages import get_language
from pydantic import BaseModel, Field, field_validator
import numpy as np 
import editdistance
from .fcu import FunctionCompareUtilities

fcu = FunctionCompareUtilities()

def equivalent_test(src, target):
    src_tokens = fcu.get_cleaned_tokens(src)
    target_tokens = fcu.get_cleaned_tokens(target)
    return np.array_equal(src_tokens, target_tokens)

def get_edit_distance(src, target):
    src_tokens = fcu.get_cleaned_tokens(src)
    target_tokens = fcu.get_cleaned_tokens(target)
    return editdistance.eval(src_tokens, target_tokens)

class InsertArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    statements: Union[str, List[str]] = Field(description="Snippet(s) to insert")
    destination_function: str = Field(description="The name of function where the insertion occurs, default \"\"")
    destination_location_prev_statement: str = Field(description="Snippets before the statements inserted")
    destination_location_next_statement: str = Field(description="Snippets after the statements inserted")
    @field_validator("statements")	
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v

class RemoveArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    statements: Union[str, List[str]] = Field(description="Snippet(s) to remove")
    destination_function: str = Field(description="The name of function where the removal occurs, default \"\"")
    destination_location_prev_statement: str = Field(description="Snippets before the statements removed")
    destination_location_next_statement: str = Field(description="Snippets after the statements removed")
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
	# source_location_prev_statement: str = Field(description="Snippets before the statements before moving")
	# source_location_next_statement: str = Field(description="Snippets after the statements before moving")
	destination_function: str = Field(description="The name of function where the statements move to, default \"\"")
	destination_location_prev_statement: str = Field(description="Snippets before the statements once moving done")
	destination_location_next_statement: str = Field(description="Snippets after the statements once moving done")
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
    destination_function: str = Field(description="The name of function where the replacement occurs, default \"\"")
    destination_location_prev_statement: str = Field(description="Snippets before the statements replaced")
    destination_location_next_statement: str = Field(description="Snippets after the statements replaced")

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
    statements: Union[str, List[str]] = Field(description="Snippet(s) to guard with checks")
    guard: str = Field(description="Guard condition to apply")

    @field_validator("statements", "guard")
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v

class IfGuardModArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    if_statement: str = Field(description="Snippet(s) containing if-statement to modify")
    new_guard: str = Field(description="New guard condition to apply")

    @field_validator("if_statement", "new_guard")
    @classmethod
    def _normalize_str_or_list(cls, v):
        if isinstance(v, list):
            return "\n".join(v)
        return v

class IfGuardSimArgs(BaseModel):
    codebase: str = Field(description="The full source text to edit")
    if_statement: Union[str, List[str]] = Field(description="Snippet(s) containing if-statements to modify")
   
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

def find_nodes_by_code(tree, src: bytes, code: str, loc_type: str = "exact"):
	"""Find all nodes in the tree whose source matches code (stripped).

	Returns a list of nodes in preorder.
	loc_type can be 'before' (node startswith code), 'after' (endswith code),
	or 'exact' (exact match). Default is 'exact'.
	"""
	code = code.strip()
	if code.endswith("{"):
		code = code[:-1]
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
		
		if loc_type == "exact":
			if node_bytes == code_bytes:
				matches.append([cursor.copy()])
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
			
			if node_bytes.startswith(code_bytes) and (node.type in allowed_types or node.type.endswith("_statement")):
				matches.append([cursor.copy()])

		if cursor.goto_first_child():
			cursor_walk(cursor)
			while cursor.goto_next_sibling():
				cursor_walk(cursor)
			cursor.goto_parent()

	def walk(node):
		nonlocal code_bytes
		try:
			node_bytes = src[node.start_byte:node.end_byte].strip()
			node_bytes = b" ".join(node_bytes.split())
			code_bytes = b" ".join(code_bytes.split())
			
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
				"case_statement",
				"switch_statement",
				"labeled_statement",
				"goto_statement"
			}
			
			if node_bytes.startswith(code_bytes) and (node.type in allowed_types or node.type.endswith("_statement")):
				matches.append(node)
			# if node_bytes.startswith(code_bytes):
			# 	matches.append(node)

		for child in node.children:
			walk(child)

	walk(tree.root_node)
	# cursor: TreeCursor = tree.walk()
	# cursor_walk(cursor)
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
	
	def gen_edits(loc_code, loc_type):
		edits = []	
		loc_nodes = find_nodes_by_code(tree, src, loc_code, loc_type) if loc_code else []
		loc_node = loc_nodes[0] if loc_nodes else None
		if loc_node:
			# Insert after or before
			if loc_type == "after":
				insert_pos = loc_node.end_byte
			elif loc_type == "before":
				insert_pos = loc_node.start_byte
				
			# Indent as location
			m = re.match(br"[ \t]*", src[loc_node.start_byte:loc_node.start_byte+100])
			indent = m.group(0) if m is not None else b""
			if loc_type == "before":
				replacement = indent + node_code.strip().encode() + b"\n"
			else:
				replacement = b"\n" + indent + node_code.strip().encode()
			edits.append(Edit(insert_pos, insert_pos, replacement))
		return edits

	if dsl.destination_location_prev_statement:
		edits = gen_edits(dsl.destination_location_prev_statement, loc_type="after")
		
		# Apply all edits
		if edits:
			src = apply_edits(src, edits)
			return src.decode()

	if dsl.destination_location_next_statement:
		edits = gen_edits(dsl.destination_location_next_statement, loc_type="before")
			
		# Apply all edits
		if edits:
			src = apply_edits(src, edits)
			return src.decode()

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
	def gen_edits(loc_code, loc_type):
		edits = []
		loc_nodes = find_nodes_by_code(tree, src, loc_code, loc_type) if loc_code else []
		if len(statements) == 1:
				statement = statements[0]
				matched_statement_nodes = find_nodes_by_code(tree, src, node_code_src[statement.start_byte:statement.end_byte].decode())
				# if len(matched_statement_nodes) == 0:
				# 	return src.decode()
				edited = False
				for node in matched_statement_nodes:
					# Remove the matched statement when any of loc_nodes at loc_type is also satisfied
					# TODO: improve matching accuracy
					if loc_nodes:
						for loc_node in loc_nodes:
							if loc_type == "after" and node.start_byte >= loc_node.end_byte:
								edits.append(Edit(node.start_byte, node.end_byte, b""))
								edited = True
								break
							elif loc_type == "before" and node.end_byte <= loc_node.start_byte:
								edits.append(Edit(node.start_byte, node.end_byte, b""))
								edited = True
								break
					if edited:
						break
		
		else:
				begin_statement = statements[0]
				end_statement = statements[-1]
				matched_begin_statement_nodes = find_nodes_by_code(tree, src, node_code_src[begin_statement.start_byte:begin_statement.end_byte].decode())
				matched_end_statement_nodes = find_nodes_by_code(tree, src, node_code_src[end_statement.start_byte:end_statement.end_byte].decode())
				# if len(matched_begin_statement_nodes) == 0 or len(matched_end_statement_nodes) == 0:
				# 	return src.decode()
				for b_node in matched_begin_statement_nodes:
					for e_node in matched_end_statement_nodes:
						# we assume that the statements between begin and end are matched with node_code's statements
						# TODO: improve matching accuracy
						if b_node.start_byte < e_node.end_byte:
							edits.append(Edit(b_node.start_byte, e_node.end_byte, b""))
							break
		return edits
	if dsl.destination_location_prev_statement:
		edits = gen_edits(dsl.destination_location_prev_statement, loc_type="after")
		# Apply all edits
		if edits:
			src = apply_edits(src, edits)
			return src.decode()
	if dsl.destination_location_next_statement:
		edits = gen_edits(dsl.destination_location_next_statement, loc_type="before")
		# Apply all edits
		if edits:
			src = apply_edits(src, edits)
			return src.decode()
	
	return src.decode()

def move(dsl: MoveArgs) -> str:
    # Move a statement from one place to anther place in the codebase
	src = dsl.codebase.encode()
	tree = parse(src)
	statements = dsl.statements
	if isinstance(statements, list):
		statements = "\n".join(statements)
 
	destination_next_statement = dsl.destination_location_next_statement
	destination_prev_statement = dsl.destination_location_prev_statement

	# Prepare the snippet AST
	node_code_src = statements.strip().encode()
	stmt_nodes = parse(node_code_src).root_node.children
	if len(stmt_nodes) == 0:
		return src.decode()

	# helper: find candidate region to move
	move_start = None
	move_end = None

	# single statement: match exact nodes
	if len(stmt_nodes) == 1:
		snippet = node_code_src
		matched_nodes = find_nodes_by_code(tree, src, snippet.decode())
		if not matched_nodes:
			return src.decode()

		chosen = None

		if chosen is None:
			# fallback to first match
			chosen = matched_nodes[0]

		move_start = chosen.start_byte
		move_end = chosen.end_byte

	else:
		# multi-statement: find begin and end snippet matches
		begin_stmt = stmt_nodes[0]
		end_stmt = stmt_nodes[-1]
		begin_matches = find_nodes_by_code(tree, src, node_code_src[begin_stmt.start_byte:begin_stmt.end_byte].decode())
		end_matches = find_nodes_by_code(tree, src, node_code_src[end_stmt.start_byte:end_stmt.end_byte].decode())
		if not begin_matches or not end_matches:
			return src.decode()

		found = False

		if not found:
			# fallback: take first begin..first end
			move_start = begin_matches[0].start_byte
			move_end = end_matches[0].end_byte

	if move_start is None or move_end is None:
		return src.decode()

	# Extract the bytes to move and remove from source
	moved_bytes = src[move_start:move_end]
	remove_edit = Edit(move_start, move_end, b"")
	src_removed = apply_edits(src, [remove_edit])

	# Reparse after removal and locate destination insertion point
	tree_after = parse(src_removed)

	insert_pos = None
	if destination_prev_statement:
		dest_nodes = find_nodes_by_code(tree_after, src_removed, destination_prev_statement, loc_type="after")
		if dest_nodes:
			dest = dest_nodes[0]
			insert_pos = dest.end_byte
	if insert_pos is None and destination_next_statement:
		dest_nodes = find_nodes_by_code(tree_after, src_removed, destination_next_statement, loc_type="before")
		if dest_nodes:
			dest = dest_nodes[0]
			insert_pos = dest.start_byte

	if insert_pos is None:
		# could not find destination; return original source (no-op)
		return src.decode()

	# determine indentation at insert location
	m = re.match(br"[ \t]*", src_removed[insert_pos:insert_pos+100])
	indent = m.group(0) if m is not None else b""
	replacement = indent + moved_bytes.strip() + b"\n"
	insert_edit = Edit(insert_pos, insert_pos, replacement)
	final = apply_edits(src_removed, [insert_edit])

	return final.decode()

def replace(dsl: ReplaceArgs):
	"""Replace old_statement(s) with new_statement(s) near the designated location.

	Behavior:
	- old_statement/new_statement may be a single statement or multiple lines (pydantic normalizes lists to strings).
	- If destination_location_prev_statement is provided, the replacement will target occurrences after that location.
	- If destination_location_next_statement is provided, the replacement will target occurrences before that location.
	- If multiple candidate matches exist, the first match that satisfies the location constraint is used.
	- If no match is found, returns the original source unchanged.
	"""
	src = dsl.codebase.encode()
	tree = parse(src)

	old_stmt = dsl.old_statement
	new_stmt = dsl.new_statement
	# defensive normalization
	if isinstance(old_stmt, list):
		old_stmt = "\n".join(old_stmt)
	if isinstance(new_stmt, list):
		new_stmt = "\n".join(new_stmt)
	old_stmt = str(old_stmt).strip()
	new_stmt = str(new_stmt).strip()

	if not old_stmt:
		return src.decode()

	old_bytes = old_stmt.encode()
	# parse old snippet to identify if it's single or multi-statement
	old_nodes = parse(old_bytes).root_node.children
	if len(old_nodes) == 0:
		return src.decode()

	node_start = None
	node_end = None

	# If single statement, reuse node-matching logic and apply location constraints
	if len(old_nodes) == 1:
		# find all candidate nodes matching the old snippet (exact match)
		candidates = find_nodes_by_code(tree, src, old_stmt, loc_type="exact")
		# if not candidates:
		# 	# try rough matches
		# 	candidates = find_nodes_by_code(tree, src, old_stmt, loc_type="rough")
		if not candidates:
			return src.decode()

		chosen = None
		# apply location constraints if provided
		if dsl.destination_location_prev_statement:
			prev_nodes = find_nodes_by_code(tree, src, dsl.destination_location_prev_statement, loc_type="after")
		else:
			prev_nodes = []
		if dsl.destination_location_next_statement:
			next_nodes = find_nodes_by_code(tree, src, dsl.destination_location_next_statement, loc_type="before")
		else:
			next_nodes = []

		for node in candidates:
			ok = True
			if prev_nodes:
				prev = prev_nodes[0]
				if node.start_byte < prev.end_byte and not (prev.start_byte <= node.start_byte < prev.end_byte):
					ok = False
			if next_nodes:
				nxt = next_nodes[0]
				if node.end_byte > nxt.start_byte:
					ok = False
			if ok:
				chosen = node
				break

		if chosen is None:
			chosen = candidates[0]

		node_start = chosen.start_byte
		node_end = chosen.end_byte

	else:
		# multi-statement: match begin and end snippets separately and pick a containing pair
		begin_node = old_nodes[0]
		end_node = old_nodes[-1]
		begin_code = old_bytes[begin_node.start_byte:begin_node.end_byte].decode()
		end_code = old_bytes[end_node.start_byte:end_node.end_byte].decode()

		begin_matches = find_nodes_by_code(tree, src, begin_code, loc_type="exact")
		end_matches = find_nodes_by_code(tree, src, end_code, loc_type="exact")
		# if not begin_matches or not end_matches:
		# 	begin_matches = find_nodes_by_code(tree, src, begin_code, loc_type="rough")
		# 	end_matches = find_nodes_by_code(tree, src, end_code, loc_type="rough")
		if not begin_matches or not end_matches:
			return src.decode()

		# find the best pair (smallest enclosing span)
		best_pair = None
		best_span = None
		for b in begin_matches:
			for e in end_matches:
				if b.start_byte < e.end_byte:
					span = e.end_byte - b.start_byte
					if best_span is None or span < best_span:
						best_span = span
						best_pair = (b, e)
		if best_pair is None:
			node_start = begin_matches[0].start_byte
			node_end = end_matches[0].end_byte
		else:
			node_start = best_pair[0].start_byte
			node_end = best_pair[1].end_byte

	if node_start is None or node_end is None:
		return src.decode()

	# Build replacement bytes while preserving indentation for each line
	m = re.match(br"[ \t]*", src[node_start:node_start+100])
	indent = m.group(0) if m is not None else b""

	# For multi-line new statements, indent each line to match location
	new_lines = [ln.rstrip() for ln in new_stmt.splitlines()]
	if len(new_lines) == 0:
		replacement = b""
	else:
		replacement = b"".join(indent + ln.encode() + b"\n" for ln in new_lines)

	edit = Edit(node_start, node_end, replacement)
	new_src = apply_edits(src, [edit])
	return new_src.decode()

def rename(dsl: RenameArgs):
	"""Rename an identifier, a variable, an API, or a member field."""
	src = dsl.codebase.encode()
	tree = parse(src)

	old_name = dsl.old_name.strip()
	new_name = dsl.new_name.strip()
	import re
	if re.match(r"^\w+$", old_name) and re.match(r"^\w+$", new_name):
		# find all candidate nodes matching the old snippet (exact match)
		candidates = find_nodes_by_code(tree, src, old_name, loc_type="exact")
		if not candidates:
			return src.decode()
		edits = []
		for node in candidates:
			edits.append(Edit(node.start_byte, node.end_byte, new_name.encode()))
		
		new_src = apply_edits(src, edits)
		return new_src.decode()
	else:
		return src.decode()


def ifguard_modify(dsl: IfGuardModArgs) -> str:
	"""Modify the guard (condition) of an existing if-statement.

	Returns the modified source as a string. If the target if-statement
	can't be found or the AST shape is unexpected, returns the original
	source unchanged.
	"""
	src = dsl.codebase.encode()
	tree = parse(src)

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
	if_nodes = find_nodes_by_code(tree, src, if_statement, loc_type="rough")
	if not if_nodes:
		return src.decode()

	if_node = if_nodes[0]
	condition = if_node.child_by_field_name("condition")
	if condition is None:
		return src.decode()

	# Build replacement bytes and apply edit
	replacement = b"(" + new_guard.encode() + b")"
	edit = Edit(condition.start_byte, condition.end_byte, replacement)
	new_src = apply_edits(src, [edit])

	return new_src.decode()

def if_guard(dsl: IfGuardArgs):
	"""Guard existing statements with checks following pattern: if(check){ stm ...}

	This function finds the statement(s) in `dsl.statements` and wraps them
	with an if(<guard>) { ... } block, preserving indentation. Returns the
	modified source as a string. If no match is found, returns original source.
	"""
	src = dsl.codebase.encode()
	tree = parse(src)

	stmts = dsl.statements
	guard = dsl.guard
	# defensive normalization
	if isinstance(stmts, list):
		stmts = "\n".join(stmts)
	if isinstance(guard, list):
		guard = "\n".join(guard)
	stmts = str(stmts).strip()
	guard = str(guard).strip()

	if not stmts or not guard:
		return src.decode()

	# prepare snippet AST and identify begin/end nodes
	snippet_bytes = stmts.strip().encode()
	snippet_tree = parse(snippet_bytes)
	snippet_nodes = snippet_tree.root_node.children
	if len(snippet_nodes) == 0:
		return src.decode()

	# If single snippet node, use the same matching strategy as before
	if len(snippet_nodes) == 1:
		matches = find_nodes_by_code(tree, src, stmts, loc_type="exact")
		if not matches:
			matches = find_nodes_by_code(tree, src, stmts, loc_type="rough")
		if not matches:
			return src.decode()
		node_start = matches[0].start_byte
		node_end = matches[0].end_byte
	else:
		# multi-statement: match begin and end snippets separately and pick a containing pair
		begin_node = snippet_nodes[0]
		end_node = snippet_nodes[-1]
		begin_code = snippet_bytes[begin_node.start_byte:begin_node.end_byte].decode()
		end_code = snippet_bytes[end_node.start_byte:end_node.end_byte].decode()

		begin_matches = find_nodes_by_code(tree, src, begin_code, loc_type="exact")
		end_matches = find_nodes_by_code(tree, src, end_code, loc_type="exact")
		# if not begin_matches or not end_matches:
		# 	begin_matches = find_nodes_by_code(tree, src, begin_code, loc_type="rough")
		# 	end_matches = find_nodes_by_code(tree, src, end_code, loc_type="rough")
		if not begin_matches or not end_matches:
			return src.decode()

		# find the best pair (smallest enclosing span)
		best_pair = None
		best_span = None
		for b in begin_matches:
			for e in end_matches:
				if b.start_byte < e.end_byte:
					span = e.end_byte - b.start_byte
					if best_span is None or span < best_span:
						best_span = span
						best_pair = (b, e)
		if best_pair is None:
			node_start = begin_matches[0].start_byte
			node_end = end_matches[0].end_byte
		else:
			node_start = best_pair[0].start_byte
			node_end = best_pair[1].end_byte

	# determine indentation at node start
	m = re.match(br"[ \t]*", src[node_start:node_start+100])
	indent = m.group(0) if m is not None else b""

	open_bytes = indent + b"if (" + guard.encode() + b") {\n"
	close_bytes = indent + b"}\n"
	if_statements = open_bytes + src[node_start:node_end] + close_bytes
 
	edits = [
		Edit(node_start, node_end, if_statements)
	]

	new_src = apply_edits(src, edits)
	return new_src.decode()

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
	# destination_location_prev_statement = "x += 1;"
	# destination_location_next_statement = ""

	# dsl = InsertArgs(
	# 	codebase=codebase,
	# 	statements=statements,
	# 	destination_function=destination_function,
	# 	destination_location_prev_statement=destination_location_prev_statement,
	# 	destination_location_next_statement=destination_location_next_statement
	# )
	
	

	# modified_code = insert(dsl)
	# print("Modified Code:\n", modified_code)
 
	payload = r'''{
    "codebase": "if (curwin->w_cursor.col < 0)\n\t\t\t\tcurwin->w_cursor.col = 0;\n\t\t\t    getvcol(curwin, &curwin->w_cursor, NULL, NULL, &ec);\n\t\t\t    if (subflags.do_number || curwin->w_p_nu)\n\t\t\t    {\n\t\t\t\tint numw = number_width(curwin) + 1;\n\t\t\t\tsc += numw;\n\t\t\t\tec += numw;\n\t\t\t    }",
    "statements": [
      "curwin->w_cursor.col = regmatch.startpos[0].col;"
    ],
    "destination_function": "",
    "destination_location_prev_statement": "getvcol(curwin, &curwin->w_cursor, NULL, NULL, &ec);",
    "destination_location_next_statement": "if (subflags.do_number || curwin->w_p_nu)"
  }'''
	import json 
	json_payload = json.loads(payload)
	
	dsl = InsertArgs(
		codebase=json_payload["codebase"],
		statements=json_payload["statements"],
		destination_function=json_payload["destination_function"],
		destination_location_prev_statement=json_payload["destination_location_prev_statement"],
		destination_location_next_statement=json_payload["destination_location_next_statement"]
	)
	
	modified_code = insert(dsl)
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
	destination_location_prev_statement = "x += 1;"
	destination_location_next_statement = ""		
	dsl = RemoveArgs(
		codebase=codebase,
		statements=statements,
		destination_function=destination_function,
		destination_location_prev_statement=destination_location_prev_statement,
		destination_location_next_statement=destination_location_next_statement
	)
	modified_code = remove(dsl)
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
    "codebase": "if (evalarg->eval_tofree == NULL)\n\t(evalarg->eval_tofree = tofree;\n    else\n\tvim_free(tofree);\n    return OK;\nerrret:\n    ga_clear_strings(&newargs);\n    ga_clear_strings(&newlines);\n    vim_free(fp);\n    vim_free(pt);\n    if (evalarg->eval_tofree == NULL)\n\t(evalarg->eval_tofree = tofree;\n    else\n\tvim_free(tofree);",
    "if_statement": "if (evalarg->eval_tofree == NULL)\n\t(evalarg->eval_tofree = tofree;\n    else\n\tvim_free(tofree);",
    "new_guard": "evalarg != NULL && evalarg->eval_tofree == NULL"
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
    "codebase": "# ifdef FEAT_LINEBREAK\n\t\t    else\n\t\t    {\n\t\t\tchar_u\t*p;\n\t\t\tint\tlen;\n\t\t\tint\ti;\n\t\t\tint\tsaved_nextra = wlv.n_extra;\n# ifdef FEAT_CONCEAL\n\t\t\tif (wlv.vcol_off > 0)\n\t\t\t    tab_len += wlv.vcol_off;\n\t\t\tif (wp->w_p_list && wp->w_lcs_chars.tab1\n\t\t\t\t\t\t      && old_boguscols > 0\n\t\t\t\t\t\t      && wlv.n_extra > tab_len)\n\t\t\t    tab_len += wlv.n_extra - tab_len;\n# endif\n\t\t\tif (tab_len > 0) {\nint tab2_len = mb_char2len(wp->w_lcs_chars.tab2);\n\t\t\tlen = tab_len * tab2_len;\n\t\t\tif (wp->w_lcs_chars.tab3)\n\t\t\t    len += mb_char2len(wp->w_lcs_chars.tab3) - tab2_len;\n\t\t\tif (wlv.n_extra > 0)\n\t\t\t    len += wlv.n_extra - tab_len;\n\t\t\tc = wp->w_lcs_chars.tab1;\n\t\t\tp = alloc(len + 1);\n\t\t\tif (p == NULL)\n\t\t\t    wlv.n_extra = 0;\n\t\t\telse\n\t\t\t{\n\t\t\t    vim_memset(p, ' ', len);\n\t\t\t    p[len] = NUL;\n\t\t\t    vim_free(wlv.p_extra_free);\n\t\t\t    wlv.p_extra_free = p;\n\t\t\t    for (i = 0; i < tab_len; i++)\n\t\t\t    {\n\t\t\t\tint lcs = wp->w_lcs_chars.tab2;\n\t\t\t\tif (*p == NUL)\n\t\t\t\t{\n\t\t\t\t    tab_len = i;\n\t\t\t\t    break;\n\t\t\t\t}\n\t\t\t\tif (wp->w_lcs_chars.tab3 && i == tab_len - 1)\n\t\t\t\t    lcs = wp->w_lcs_chars.tab3;\n\t\t\t\tp += mb_char2bytes(lcs, p);\n\t\t\t\twlv.n_extra += mb_char2len(lcs)\n\t\t\t\t\t\t  - (saved_nextra > 0 ? 1 : 0);\n\t\t\t    }\n\t\t\t    wlv.p_extra = wlv.p_extra_free;\n# ifdef FEAT_CONCEAL\n\t\t\t    if (wlv.vcol_off > 0)\n\t\t\t\twlv.n_extra -= wlv.vcol_off;\n# endif\n\t\t\t}}\n\n\t\t    }\n#endif\n#ifdef FEAT_CONCEAL\n\t\t    {\n\t\t\tint vc_saved = wlv.vcol_off;\n\t\t\tFIX_FOR_BOGUSCOLS;\n\t\t\tif (wlv.n_extra == tab_len + vc_saved && wp->w_p_list\n\t\t\t\t\t\t&& wp->w_lcs_chars.tab1)\n\t\t\t    tab_len += vc_saved;\n\t\t    }\n#endif",
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
		source_function="foo",
		source_location_prev_statement="",
		source_location_next_statement="",
		destination_function="foo",
		destination_location_prev_statement="x += 3;",
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
		source_function="foo",
		source_location_prev_statement="",
		source_location_next_statement="",
		destination_function="foo",
		destination_location_prev_statement="x += 4;",
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
		source_function="foo",
		source_location_prev_statement="int a = 0;",
		source_location_next_statement="int c = 2;",
		destination_function="foo",
		destination_location_prev_statement="int c = 2;",
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
	# 	destination_location_prev_statement="",
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
	# 	destination_location_prev_statement="",
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
	# 	destination_location_prev_statement="int b = 1;",
	# 	destination_location_next_statement="",
	# )
	# print('\n--- test_replace case 3: constrained replace (after prev) ---')
	# print(replace(dsl3))
 
	payload = r"""{
		"codebase": "if (i > 0)\n\t{\n\t    matchidx_T\tprevIdx = matches[i - 1];\n\t    if (currIdx == (prevIdx + 1))\n\t\tscore += SEQUENTIAL_BONUS;\n\t}\n\tif (currIdx > 0)\n\t{\n\t    int\tneighbor;\n\t    int\tcurr;\n\t    int\tneighborSeparator;\n\t    if (has_mbyte)\n\t    {\n\t\twhile (sidx < currIdx)\n\t\t{\n\t\t    neighbor = (*mb_ptr2char)(p);\n\t\t    (void)mb_ptr2char_adv(&p);\n\t\t    sidx++;\n\t\t}\n\t\tcurr = (*mb_ptr2char)(p);\n\t    }\n\t    else\n\t    {\n\t\tneighbor = str[currIdx - 1];\n\t\tcurr = str[currIdx];\n\t    }\n\t    if (vim_islower(neighbor) && vim_isupper(curr))\n\t\tscore += CAMEL_BONUS;\n\t    neighborSeparator = neighbor == '_' || neighbor == ' ';\n\t    if (neighborSeparator)\n\t\tscore += SEPARATOR_BONUS;\n\t}\n\telse\n\t{\n\t    score += FIRST_LETTER_BONUS;\n\t}",
		"old_statement": "int\tneighbor;",
		"new_statement": "int\tneighbor = ' ';",
		"destination_function": "",
		"destination_location_prev_statement": "if (currIdx > 0)",
		"destination_location_next_statement": "int\tcurr;"
	}"""
	import json 
	json_payload = json.loads(payload)
	
	dsl4 = ReplaceArgs(
		codebase=json_payload["codebase"],
		old_statement=json_payload["old_statement"],
		new_statement=json_payload["new_statement"],
		destination_function=json_payload["destination_function"],
		destination_location_prev_statement=json_payload["destination_location_prev_statement"],
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
	# test_ifguard_modify()
	# test_move()
	# test_replace()
	# test_ifguard()
	test_parse()
