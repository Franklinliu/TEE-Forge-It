import pprint
import time
from tree_sitter import Language, Parser
import numpy as np
import sys
import logging
from tree_sitter_languages import get_language

class FunctionCompareUtilities:
    _instance = None

    def __new__(cls, log_path=None):
        if cls._instance is None:
            sys.setrecursionlimit(100000)
            cls._instance = super(FunctionCompareUtilities, cls).__new__(cls)
            LANG_C = get_language("c")
            parser = Parser()
            parser.set_language(LANG_C)
            cls._instance.parser = parser
            if log_path is not None:
                logging.basicConfig(filename=f'{log_path}fcu_{str(time.time())}.log', level=logging.DEBUG)
        return cls._instance

    @classmethod
    def parse(cls, code_bytes):
        return cls._instance.parser.parse(code_bytes)

    @classmethod
    def retrieve_string_slice(cls, string: str, start_point, end_point) -> str:
        string_list = cls.get_line_list(string, start_point[0], end_point[0])
        string_list[-1] = string_list[-1][:end_point[1]]
        string_list[0] = string_list[0][start_point[1]:]
        return "".join(string_list)

    @classmethod
    def get_functions(cls, code_str, root):
        def dfs(current_node):
            if current_node.type == "function_definition":
                func_sign = current_node.child_by_field_name("declarator")
                func_sign_str = cls.retrieve_string_slice(code_str, func_sign.start_point, func_sign.end_point)
                function_nodes[func_sign_str] = current_node

            elif len(current_node.children) != 0:
                for sub_node in current_node.children:
                    dfs(sub_node)

        function_nodes = {}
        dfs(root)
        return function_nodes

    @classmethod
    def get_tokens(cls, code_bytes, root):

        def dfs(current_node):
            if len(current_node.children) == 0:
                tokens.append(code_bytes[current_node.start_byte:current_node.end_byte].decode())
            else:
                for sub_node in current_node.children:
                    dfs(sub_node)

        tokens = []
        dfs(root)
        return tokens
    
    # ---------- Normalization helpers ----------
    def _skip_empty(self, nodes):
        for ch in nodes:
            if ch.type == "empty_statement":   # lone ';'
                continue
            yield ch


    def unwrap_parens(self, node):
        """Collapse ( ... ) wrappers if they contain exactly one named child."""
        cur = node
        while cur.type == "parenthesized_expression" and len(cur.named_children) == 1:
            cur = cur.named_children[0]
        return cur

    def unwrap_singleton_block(self, node):
        """
        Collapse { stmt } → stmt when the block contains exactly one non-empty named child.
        Do NOT collapse multi-statement blocks.
        """
        cur = node
        while cur.type == "compound_statement":
            kids = list(self._skip_empty(cur.named_children))
            if len(kids) == 1:
                cur = kids[0]
                # keep unwrapping if nested singleton blocks exist
                continue
            break
        return cur

    def normalize_node(self, node):
        """Apply all unwrappings in a stable order."""
        cur = self.unwrap_parens(node)
        cur = self.unwrap_singleton_block(cur)
        return cur
    
    def normalized_children(self, node):
        """Yield children after removing empty statements and unwrapping parens/blocks."""
        for ch in self._skip_empty(node.children):
            yield self.normalize_node(ch)

    def get_cleaned_tokens(self, code_str):
        logging.debug(code_str)
        code_str = self.remove_empty_lines(code_str)
        code_bytes = code_str.encode('utf-8')
        func_tree = self.parse(code_bytes)
        def dfs(current_node):
            if len(current_node.children) == 0:
                tokens.append((code_bytes[current_node.start_byte:current_node.end_byte].decode(), current_node.type))
            else:
                normalized_children = list(self.normalized_children(current_node))
                for sub_node in normalized_children:
                    dfs(sub_node)

        tokens = []
        dfs(func_tree.root_node)

        cleaned_tokens = []
        
        invalid_node_type = ["comment"]
        for t in tokens:
            if t[1] in invalid_node_type:
                continue
            
            cleaned_tokens.append(t[0])
        
        return cleaned_tokens

    @classmethod
    def get_tokens_count(cls, code_str: str) -> int:
        code_bytes = code_str.encode('utf-8')
        func_tree = cls.parse(code_bytes)
        return len(cls.get_tokens(code_bytes, func_tree.root_node))

    @classmethod
    def if_functions_with_same_tokens(cls, code_str_1, code_str_2):
        code_bytes_1 = code_str_1.encode('utf-8')
        code_bytes_2 = code_str_2.encode('utf-8')
        func_tree_1 = cls.parse(code_bytes_1)
        func_tree_2 = cls.parse(code_bytes_2)
        func_tokens_1 = cls.get_tokens(code_bytes_1, func_tree_1.root_node)
        func_tokens_2 = cls.get_tokens(code_bytes_2, func_tree_2.root_node)
        return np.array_equal(func_tokens_1, func_tokens_2)

    @classmethod
    def modified_functions_lines(cls, codes_str_1, codes_str_2, root_1, root_2):
        func_list_1 = cls.get_function_lines(codes_str_1, root_1)
        func_list_2 = cls.get_function_lines(codes_str_2, root_2)
        func_list_copy_1 = func_list_1.copy()
        func_list_copy_2 = func_list_2
        for func_name, func_lines in func_list_1.items():
            if func_name in func_list_copy_2 and \
                    np.array_equal(func_lines, func_list_copy_2[func_name]):
                del func_list_copy_1[func_name]
                del func_list_copy_2[func_name]
        return func_list_copy_1, func_list_copy_2

    @classmethod
    def code_standardization(cls, code):

        def enough_alpha(string):
            threshold = 5
            count = 0
            for char in string:
                if char.isalpha():
                    count += 1
                if count >= threshold:
                    return True
            return False

        def is_valid_parentheses(s: str):
            stack = []
            for c in s:
                if c == '(':
                    stack.append(c)
                elif c == ')':
                    if not stack or stack[-1] != '(':
                        return False
                    stack.pop()
            return not stack

        lines = code.splitlines(keepends=True)
        assert len(lines) >= 3, "code to short!"
        macro_lines = []
        for line_num in range(1, len(lines) - 1):
            if lines[line_num].upper() == lines[line_num] and \
                    lines[line_num - 1].strip().endswith(')') and \
                    lines[line_num + 1].strip().startswith('{') and \
                    enough_alpha(lines[line_num]) and \
                    is_valid_parentheses(lines[line_num]):
                macro_lines.append(line_num)
        for macro_line in macro_lines:
            logging.debug(lines[macro_line])
            lines[macro_line] = "\n"
        return "".join(lines)

    @classmethod
    def get_line_list(cls, code_str, start_line, end_line):
        lines = code_str.splitlines(keepends=True)
        lines = lines[start_line:end_line + 1]
        return lines

    @classmethod
    def get_function_lines(cls, code_str, root):
        function_nodes = cls.get_functions(code_str, root)
        function_lines = {functino_name: cls.get_line_list(code_str, cls.expand_to_comment(node), node.end_point[0])
                          for (functino_name, node) in function_nodes.items()}
        return function_lines

    @classmethod
    def expand_to_comment(cls, function_node):
        start_line = function_node.start_point[0]
        current_node = function_node.prev_sibling
        while current_node is not None and current_node.end_point[0] == start_line - 1 and \
                current_node.type == "comment":
            start_line = current_node.start_point[0]
            current_node = current_node.prev_sibling
        return start_line

    @classmethod
    def remove_comments(cls, code_str):
        def dfs(tree_root):
            nonlocal comments
            for child in tree_root.children:
                if child.type == "comment":
                    comments.append((child.start_byte, child.end_byte))
                else:
                    dfs(child)

        code_bytes = code_str.encode('utf-8')
        code_tree = cls.parse(code_bytes)

        comments = []
        dfs(code_tree.root_node)
        comments = sorted(comments, key=lambda x: x[0], reverse=True)
        code_bytearray = bytearray(code_bytes)

        for start_byte, end_byte in comments:
            code_bytearray[start_byte:end_byte] = b''

        return bytes(code_bytearray).decode()

    @classmethod
    def remove_empty_lines(cls, string: str) -> str:
        lines = string.splitlines(keepends=True)
        non_empty_lines = [line for line in lines if line.strip()]
        return "".join(non_empty_lines)

    @classmethod
    def retrieve_bytes_as_string(cls, string: str, start_byte: int, end_byte: int) -> str:
        string_bytes = string.encode('utf-8')
        string_bytearray = bytearray(string_bytes)
        return bytes(string_bytearray[start_byte:end_byte]).decode()

    @classmethod
    def display_ast(cls, root, func, depth=0):
        print(" - " * depth, root.type)
        pprint.pprint(cls.retrieve_string_slice(func, root.start_point, root.end_point))
        print("-" * 100)
        for child in root.children:
            cls.display_ast(child, func, depth + 1)

    @classmethod
    def get_byte_length(cls, string, encoding='utf-8') -> int:
        return len(string.encode(encoding))
    
if __name__ == "__main__":
    fcu = FunctionCompareUtilities(log_path="/workspaces/TEE-Forge-It/tmp/")
    code1 = """
    else
    { return (b);}
}"""

    tokens = fcu.get_cleaned_tokens(code1)
    print(tokens)