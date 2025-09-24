import os
import subprocess
import json

def get_cargo_metadata(project_path):
    """
    Runs `cargo metadata` in the given Rust project directory and returns parsed JSON output.
    """
    try:
        result = subprocess.run(
            ["cargo", "metadata", "--format-version", "1", "--no-deps"],  # 加上 --no-deps 只获取主包及直接依赖
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running cargo metadata: {e.stderr}")
        return None

def analyze_dependencies(metadata):
    """
    Extracts and returns a list of dependencies from cargo metadata.
    """
    if not metadata or "packages" not in metadata:
        return []

    dependencies = []
    for package in metadata["packages"]:
        for dep in package.get("dependencies", []):
            dependencies.append({
                "name": dep["name"],
                "req": dep["req"],
                "kind": dep.get("kind", "normal"),
                "source": dep.get("source", "local"),
            })
    return dependencies

def print_dependencies(dependencies):
    """
    Prints the dependencies in a readable format.
    """
    print("Dependencies found:")
    for dep in dependencies:
        print(f"- {dep['name']} ({dep['req']}) [{dep['kind']}] Source: {dep['source']}")

if __name__ == "__main__":
    project_path = os.getenv("CARGO_PROJECT_PATH", ".")
    print(project_path)
    metadata = get_cargo_metadata(project_path)
    deps = analyze_dependencies(metadata)
    print_dependencies(deps)