"""
DSL Transformer for C code edits using tree-sitter.
Supports Move, Insert, Remove, Replace actions as described in DSL grammar.
"""
import re
import sys
from dataclasses import dataclass
from tree_sitter import Parser
from tree_sitter_languages import get_language



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
			}
			if node_bytes.startswith(code_bytes) and node.type in allowed_types:
				matches.append(node)

		for child in node.children:
			walk(child)

	walk(tree.root_node)
	return matches

def apply_edits(src: bytes, edits):
	"""Apply non-overlapping edits in reverse start order."""
	edits_sorted = sorted(edits, key=lambda e: e.start, reverse=True)
	out = bytearray(src)
	for e in edits_sorted:
		out[e.start:e.end] = e.replacement
	return bytes(out)

def transform_c_code_with_dsl(src: bytes, dsl: dict) -> bytes:
	"""
	Apply DSL edits to C code source.
	DSL format: {"strategy": [Rule, ...]}
	"""
	tree = parse(src)
	edits = []
	for rule in dsl.get("strategy", []):
		if "Insert" in rule:
			node_code = rule["Insert"]["Node"]
			location = rule["Insert"]["Location"]
			# Find location node
			loc_type, loc_code = None, None
			if ":" in location:
				loc_type, loc_code = location.split(":", 1)
				loc_code = loc_code.strip()
			loc_nodes = find_nodes_by_code(tree, src, loc_code, loc_type) if loc_code else []
			loc_node = loc_nodes[0] if loc_nodes else None
			if loc_node:
				# Insert after or before
				if loc_type == "after":
					insert_pos = loc_node.end_byte
				elif loc_type == "before":
					insert_pos = loc_node.start_byte
				else:
					continue
				# Indent as location
				indent = re.match(br"[ \t]*", src[loc_node.start_byte:loc_node.start_byte+100]).group(0)
				replacement = indent + node_code.strip().encode() + b"\n"
				edits.append(Edit(insert_pos, insert_pos, replacement))
		elif "Remove" in rule:
			node_code = rule["Remove"]["Node"]
			location = rule["Remove"]["Location"]
			# Find node to remove
			nodes = find_nodes_by_code(tree, src, node_code)
			node = nodes[0] if nodes else None
			if node:
				edits.append(Edit(node.start_byte, node.end_byte, b""))
		elif "Replace" in rule:
			node1 = rule["Replace"]["Node1"]
			node2 = rule["Replace"]["Node2"]
			location = rule["Replace"]["Location"]
			nodes = find_nodes_by_code(tree, src, node1)
			node = nodes[0] if nodes else None
			if node:
				replacement = node2.strip().encode()
				edits.append(Edit(node.start_byte, node.end_byte, replacement))
		elif "Move" in rule:
			node_code = rule["Move"]["Node"]
			loc1 = rule["Move"]["Location1"]
			loc2 = rule["Move"]["Location2"]
			# Remove from Location1
			nodes = find_nodes_by_code(tree, src, node_code)
			node = nodes[0] if nodes else None
			if node:
				edits.append(Edit(node.start_byte, node.end_byte, b""))
			# Insert at Location2
			loc_type, loc_code = None, None
			if ":" in loc2:
				loc_type, loc_code = loc2.split(":", 1)
				loc_code = loc_code.strip()
			loc_nodes = find_nodes_by_code(tree, src, loc_code, loc_type) if loc_code else []
			loc_node = loc_nodes[0] if loc_nodes else None
			if loc_node:
				if loc_type == "after":
					insert_pos = loc_node.end_byte
				elif loc_type == "before":
					insert_pos = loc_node.start_byte
				else:
					continue
				indent = re.match(br"[ \t]*", src[loc_node.start_byte:loc_node.start_byte+100]).group(0)
				replacement = indent + node_code.strip().encode() + b"\n"
				edits.append(Edit(insert_pos, insert_pos, replacement))
	# Apply all edits
	if edits:
		src = apply_edits(src, edits)
	return src

if __name__ == "__main__":
	import json
	if len(sys.argv) != 3:
		print("Usage: python dsl_transformer.py input.c dsl.json", file=sys.stderr)
		sys.exit(2)
	with open(sys.argv[1], "rb") as f:
		src = f.read()
	with open(sys.argv[2], "r") as f:
		dsl = json.load(f)
	out = transform_c_code_with_dsl(src, dsl)
	sys.stdout.buffer.write(out)
