# In this file, we define the used prompts for the migration agent.
from typing import List
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain.schema import BaseMessage
from langchain.prompts.chat import MessagesPlaceholder
from langchain.prompts import PromptTemplate

prompt_hunk_gen = PromptTemplate(template = """
    You are a Rust SGX/TEE porting expert. Based on the following original Rust code, and reference knowledge, provide modification suggestions to make it TEE-compatible.

    Original code:
    ```
    {rust_code}
    ```

    Related knowledge:
    {context_text}

    Please generate only the change hunks in the hunk form of `git diff` format, which can be directly applied to the original code using the `git apply` command. In the git diff output, apart from change hunk header information, MUST use "+" for addition while use "-" for removal.
    """)
    

prompt_code_gen = PromptTemplate(template = """
    You are a Rust SGX/TEE porting expert. Based on the following Rust source code, compiler errors, and knowledge base content, provide modification suggestions to make it TEE-compatible, and output the complete modified code.

    Original code:
    {rust_code}

    Compiler errors:
    {error_text}

    Related knowledge:
    {context_text}

    Please output the complete modified code directly.
    Please provide only the modified complete code without any explanations.
    """)


prompt_git_diff_summary = PromptTemplate(template = """
    You are a Rust SGX/TEE porting expert. Based on the following git diff output, summarize the modifications made in this commit.
    Git diff:
    ```
    {git_diff}
    ```
    Please provide a concise summary of the changes made in this commit.
    """)