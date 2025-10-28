import re
from difflib import SequenceMatcher
from typing import Iterable, List, Tuple

def _norm_line(s: str) -> str:
    # remove all whitespace (spaces, tabs, CR/LF) for comparison
    return re.sub(r"\s+", "", s)

def _split_lines(text: str) -> List[str]:
    # normalize line endings but preserve line breaks for output
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

def unified_diff_ignore_whitespace(a: str, b: str,
                                   fromfile: str = "a",
                                   tofile: str = "b",
                                   context: int = 3) -> str:
    a_lines = _split_lines(a)
    b_lines = _split_lines(b)
    a_cmp = [_norm_line(x) for x in a_lines]
    b_cmp = [_norm_line(x) for x in b_lines]

    sm = SequenceMatcher(None, a_cmp, b_cmp, autojunk=False)
    groups = sm.get_grouped_opcodes(context)

    out = []
    out.append(f"--- {fromfile}")
    out.append(f"+++ {tofile}")

    for group in groups:
        a_start = group[0][1]
        a_end   = group[-1][2]
        b_start = group[0][3]
        b_end   = group[-1][4]

        # line numbers in unified diff are 1-based; counts can be zero
        a_count = a_end - a_start
        b_count = b_end - b_start
        out.append(f"@@ -{a_start+1},{a_count} +{b_start+1},{b_count} @@")

        for tag, i1, i2, j1, j2 in group:
            if tag in ("replace", "delete"):
                for i in range(i1, i2):
                    out.append(f"-{a_lines[i]}")
            if tag in ("replace", "insert"):
                for j in range(j1, j2):
                    out.append(f"+{b_lines[j]}")
            if tag == "equal":
                for i in range(i1, i2):
                    out.append(f" {a_lines[i]}")

    return "\n".join(out) + "\n" if groups else ""  # empty string when “equal” under whitespace-ignoring