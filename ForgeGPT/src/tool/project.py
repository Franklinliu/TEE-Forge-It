
import subprocess
from langchain.tools import BaseTool
from typing import Optional, Type
import os
import shutil

class ProjectToolKit(BaseTool):
    name = "ProjectTool"
    description = "A toolkit to manage and interact with Rust library project files."

    project_path: str  # Path to the root of the Rust project

    def _run(self, command: str, file_path: Optional[str] = None, content: Optional[str] = None) -> str:
        """
        Execute a command on the project files.
        
        Commands:
        - read_file: Read the content of a specified file.
        - write_file: Write content to a specified file.
        - list_files: List all files in the project directory.
        - reset_project: Reset the project directory to its initial state.
        - get_dependencies: Get dependencies from Cargo.toml files.

        Args:
            command (str): The command to execute.
            file_path (Optional[str]): The path to the file (for read/write commands).
            content (Optional[str]): The content to write (for write command).

        Returns:
            str: The result of the command execution.
        """
        if command == "read_file":
            if not file_path:
                return "Error: file_path is required for read_file command."
            full_path = os.path.join(self.project_path, file_path)
            if not os.path.exists(full_path):
                return f"Error: File {file_path} does not exist."
            with open(full_path, 'r') as f:
                return f.read()

        elif command == "write_file":
            if not file_path or content is None:
                return "Error: file_path and content are required for write_file command."
            full_path = os.path.join(self.project_path, file_path)
            with open(full_path, 'w') as f:
                f.write(content)
            return f"Successfully wrote to {file_path}."

        elif command == "list_files":
            files = []
            for root, _, filenames in os.walk(self.project_path):
                for filename in filenames:
                    files.append(os.path.relpath(os.path.join(root, filename), self.project_path))
            return "\n".join(files)

        elif command == "reset_project":
            # Assuming we have a backup of the initial state at project_path_backup
            backup_path = self.project_path + "_backup"
            if os.path.exists(backup_path):
                if os.path.exists(self.project_path):
                    shutil.rmtree(self.project_path)
                shutil.copytree(backup_path, self.project_path)
                return "Project has been reset to its initial state."
            else:
                return "Error: Backup of the initial state does not exist." 
        elif command == "get_dependencies":
            cargo_toml_path = os.path.join(self.project_path, "Cargo.toml")
            if not os.path.exists(cargo_toml_path):
                return "Error: Cargo.toml does not exist in the project root."
            with open(cargo_toml_path, 'r') as f:
                content = f.read()
            # Simple parsing to extract dependencies (this can be improved with a proper TOML parser)
            dependencies = []
            in_dependencies_section = False
            for line in content.splitlines():
                line = line.strip()
                if line == "[dependencies]":
                    in_dependencies_section = True
                    continue
                if line.startswith("[") and line.endswith("]"):
                    in_dependencies_section = False
                if in_dependencies_section and line and not line.startswith("#"):
                    dependencies.append(line)
            return "\n".join(dependencies)
        else:
            return f"Error: Unknown command {command}."


class Project(object):
    def __init__(self, project_path: str):
        self.project_path = project_path
        self.tool = ProjectToolKit(project_path=project_path)
        
    def setup_docker_environment(self) -> str:
        # This method can be expanded to set up a Docker environment if needed.
        # docker-sgx-xargo-create
        subprocess.run(f"bash -i -c 'docker-sgx-xargo-create {os.path.basename(os.path.dirname(self.project_path))}'", shell=True)
        # docker-sgx-cargo-create
        subprocess.run(f"bash -i -c 'docker-sgx-cargo-create {os.path.basename(os.path.dirname(self.project_path))}'", shell=True)
    
        # change directory to project_path 
        os.chdir(self.project_path)

    def read_file(self, file_path: str) -> str:
        return self.tool.run(command="read_file", file_path=file_path)

    def write_file(self, file_path: str, content: str) -> str:
        return self.tool.run(command="write_file", file_path=file_path, content=content)

    def list_files(self) -> str:
        return self.tool.run(command="list_files")

    def reset_project(self) -> str:
        return self.tool.run(command="reset_project")

    def get_dependencies(self) -> str:
        return self.tool.run(command="get_dependencies")
    
    def compile_project(self, use_xargo: bool = True) -> str:
        from ..compilation.compile import xargo_compile_sgx_project, cargo_compile_sgx_project
        project_name = os.path.basename(self.project_path)
        if use_xargo:
            return xargo_compile_sgx_project(os.path.dirname(self.project_path), project_name)
        else:
            return cargo_compile_sgx_project(os.path.dirname(self.project_path), project_name)
