from tree_sitter import Language, Parser
import tree_sitter_rust as tsrust

with open("./examples/lib.rs", "rb") as f:
    raw = f.read()

parser = Parser(Language(tsrust.language()))
tree = parser.parse(raw)

enums = [
    node
    for node in tree.root_node.children
    if node.type == 'extern_crate_declaration'
]
print(enums)