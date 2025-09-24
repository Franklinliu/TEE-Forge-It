import re

def remove_ansi_colors(text: str) -> str:
    """
    Remove all ANSI escape sequences (coloring and formatting) from Rust compiler output.
    """
    ansi_escape = re.compile(
        r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'
    )
    return ansi_escape.sub('', text)

def format_delta_compile_results():
    """
    Format the delta compile results saved in the /workspaces/TEE-Forge-It/changes/*.deltacompile.json.
    Remove ansi color codes and save back to the original file.
    """
    import os
    import json

    changes_dir = "/workspaces/TEE-Forge-It/changes"
    for filename in os.listdir(changes_dir):
        if filename.endswith(".deltacompile.json"):
            file_path = os.path.join(changes_dir, filename)
            with open(file_path, 'r') as f:
                data = json.load(f)
            # Clean ansi colors in all error messages
            for rel_file, results in data.items():
                for result in results:
                    if 'xargo_error' in result:
                        result['xargo_error'] = remove_ansi_colors(result['xargo_error'])
                    if 'cargo_error' in result:
                        result['cargo_error'] = remove_ansi_colors(result['cargo_error'])
            # Save back to the same file
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"Formatted {file_path}")
    

def test():
    sample_text = "\x1b[0;31merror:\x1b[0m something went wrong"
    print("Original:", repr(sample_text))
    print("Cleaned:", repr(remove_ansi_colors(sample_text)))
    print("Original:", repr(open("/workspaces/TEE-Forge-It/test_error.log").read()))
    print("Cleaned:", repr(remove_ansi_colors(open("/workspaces/TEE-Forge-It/test_error.log").read())))


if __name__ == "__main__":
   format_delta_compile_results()
