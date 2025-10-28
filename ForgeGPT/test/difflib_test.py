import difflib

old_code = """\
int main() {
     int a = 5;
    return a;
}
"""

new_code = """\
int main() {
    int a = 5;
    int b = a + 1;
    return b;
}
"""
def normalize_whitespace(s: str) -> str:
    # Collapse tabs/newlines/multiple spaces into single space
    return " ".join(s.split())

a_norm = [line.strip() for line in old_code.splitlines()]
b_norm = [line.strip() for line in new_code.splitlines()]

diff = difflib.unified_diff(
    a_norm,
    b_norm,
    fromfile='old.c', tofile='new.c', lineterm=''
)
print('\n'.join(diff))

diff = difflib.unified_diff(
    old_code.splitlines(),
    new_code.splitlines(),
    fromfile='old.c',
    tofile='new.c',
    n=2,  # context lines
    lineterm=''
)

print('\n'.join(diff))