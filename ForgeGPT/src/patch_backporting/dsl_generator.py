import time
from typing import Any, Dict, Optional, Union
import os
import json
import difflib
import random
from .dsl_parser import parse_strategy
from .llm_usage import LLMUsageRecorder
from .dsl_prompt import DSL_GRAMMAR, generate_seed_dsl
from src.model.qwen import qwen3coder_30b
from src.model.chatgpt import gpt3_5_turbo
# Minimal LangChain Chat wrapper import pattern used in this repo
from langchain_openai import ChatOpenAI

# Short/long term memory simple implementation
class ShortTermMemory:
    def __init__(self, capacity: int = 10):
        self.capacity = capacity
        self.buffer = []  # list of recent messages/observations

    def trim_test(self):
        if len(self.buffer) == self.capacity:
            return True, self.buffer[4:]
        return False, None 
    
    def trim(self, items: list[Union[dict, str]], summary: Union[dict, str]):
        total = len(self.buffer)
        self.buffer = self.buffer[:total-len(items)] + [summary]
        return True 

    def push(self, item: str):
        self.buffer.append(item)
        if len(self.buffer) > self.capacity:
            self.buffer.pop(0)
            
    def snapshot(self):
        return self.buffer

class LongTermMemory:
    def __init__(self, persist_dir: Optional[str] = None):
        """初始化基于向量数据库的长期记忆系统。
        
        Args:
            persist_dir: 向量数据库持久化目录
        """
        import chromadb
        from chromadb.config import Settings
        
        self.persist_dir = persist_dir or os.path.join(os.getcwd(), "vector_memory")
        os.makedirs(self.persist_dir, exist_ok=True)
        
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )
        
        # 创建或获取已有集合
        self.collection = self.client.get_or_create_collection(
            name="code_transform_memory",
            metadata={"description": "Code transformation knowledge base"}
        )
        
    def add_knowledge(self, source_code: str, dsl_transform: Union[str, dict], target_code: str):
        """添加代码转换知识。
        
        Args:
            source_code: 原始代码
            dsl_transform: DSL转换规则
            target_code: 目标代码
        """
        # 生成唯一ID
        import hashlib
        knowledge_id = hashlib.md5(
            (source_code + json.dumps(dsl_transform) + target_code).encode()
        ).hexdigest()
        
        # 添加到向量数据库
        self.collection.add(
            ids=[knowledge_id],
            documents=[source_code],  # 用源代码作为文档
            metadatas=[{
                "source_code": source_code,
                "dsl_transform": json.dumps(dsl_transform) if isinstance(dsl_transform, dict) else dsl_transform,
                "target_code": target_code
            }]
        )
        
    def query_similar_transforms(self, source_code: str, n_results: int = 3) -> list[dict]:
        """查询与给定源代码相似的转换知识。
        
        Args:
            source_code: 待查询的源代码
            n_results: 返回结果数量
            
        Returns:
            List[Dict]: 相似度排序的转换知识列表
        """
        # 查询向量数据库
        results = self.collection.query(
            query_texts=[source_code],
            n_results=n_results
        )
        
        knowledge_items = []
        if results and results['metadatas']:
            for metadata in results['metadatas'][0]:  # First query results
                knowledge_items.append({
                    "source_code": metadata["source_code"],
                    "dsl_transform": json.loads(metadata["dsl_transform"]),
                    "target_code": metadata["target_code"]
                })
                
        return knowledge_items


class DSLGeneratorAgent:
    """Generate DSL code for backporting/migration tasks.

    Responsibilities:
      - Use ChatOpenAI to synthesize DSL from an input description or diff.
      - Maintain short-term memory for multi-turn generation.
      - Record important facts in long-term memory.
      - Expose a pluggable tools interface so external functions can be called.
    """

    def __init__(self, model: Optional[ChatOpenAI] = None, lt_memory: Optional[LongTermMemory] = None, usage_recorder: Optional[LLMUsageRecorder] = None):
        self.model: ChatOpenAI = model 
        self.st_memory = ShortTermMemory()
        self.lt_memory = lt_memory or LongTermMemory()
        self.tools = {}
        self.usage_recorder = usage_recorder or LLMUsageRecorder()

    def register_tool(self, name: str, func):
        self.tools[name] = func
        
    def invoke_model(self, prompt: str) -> Any:
        resp = self.model.invoke(prompt)
        self.usage_recorder.record_usage(self.model, resp)
        return resp
    
    def invoke_model_messages(self, messages: list) -> Any:
        if hasattr(self.model, 'invoke_messages'):
                resp = self.model.invoke_messages(messages)
        else:
                # fallback: serialize role messages into a single prompt string
                serialized = ""
                for messsage in messages:
                    serialized = serialized + "[{role}]\n {content}\n".format(role = messsage["role"], content = messsage["content"])
                resp = self.invoke_model(serialized)
                                         
        self.usage_recorder.record_usage(self.model, resp)
        return resp

    def configure_default_messages(self, pre_transform_code: str, post_transform_code:str):
        system = (
            """You are an expert DSL code generator. Your task is to infer transformation rules from the patch between the following two programs. The rules are expressed in the below domain-specific language (DSL) grammar:
            {dsl_grammar}
            """.format(dsl_grammar = DSL_GRAMMAR)
        )
        
        diff_lines = list(difflib.unified_diff(pre_transform_code.splitlines(), post_transform_code.splitlines(), fromfile = "Program#1", tofile = "Program#2"))
        context=(
            "Below is the patch including the program before (Program#1) and the program after (Program#2)",
            """
            Program before (Program#1):`{pre_transform_code}` 
            Program after (Program#2):`{post_transform_code}`
            """.format(
                pre_transform_code=pre_transform_code, post_transform_code=post_transform_code
            )
        )

        user_parts= [f"Context:\n{context}"]
        user_parts.append("Output exactly one JSON object: {\"strategy\": [ ... ]} and nothing else. JSON requires double quotes for all keys and string values. No explanations, no fences."
        """For example: {
                "strategy": [
                    {
                        "Remove": {
                            "Node": "char_u *s = cmd;",
                            "Scope": "func append_command : void -> void"
                        }
                    },
                    {
                        "Insert": {
                            "Node": "size_t  len = STRLEN(IObuff);",
                            "Location": "at_begin_of: append_command"
                        }
                    },
                    {
                        "Insert": {
                            "Node": "char_u *d;",
                            "Location": "at_begin_of: append_command"
                        }
                    },
                    {
                        "Insert": {
                            "Node": "if (len > IOSIZE - 100) { d = IObuff + IOSIZE - 100; d -= mb_head_off(IObuff, d); STRCPY(d, \"...\"); }",
                            "Location": "before: STRCAT(IObuff, \": \");"
                        }
                    },
                    {
                        "Move": {
                            "Node": "char_u *d;",
                            "Location1": "before: STRCAT(IObuff, \": \");",
                            "Location2": "after: size_t  len = STRLEN(IObuff);"
                        }
                    },
                    {
                        "Move": {
                            "Node": "char_u *s = cmd;",
                            "Location1": "before: STRCAT(IObuff, \": \");",
                            "Location2": "after: char_u *d;"
                        }
                    }
                ]
            }""")
        user = "\n".join(user_parts)
        
        assistant = "I understand and will produce the DSL JSON when requested."
        default_messages =  [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
        for message in default_messages:
            self.st_memory.push(message)
        
    def build_user_role_message(self, instruction: Optional[str], context: Optional[str] = None):
        """Return a list of role messages (system/user/assistant) for chat-style LLMs."""
        instruction = "\n\n".join(instruction) if isinstance(instruction, list) else str(instruction)
        user_parts = [f"{instruction}"]
        if context:
            user_parts.append(f"Context:\n{context}")
    
        user_parts.append("Output exactly one JSON object: {\"strategy\": [ ... ]} and nothing else. JSON requires double quotes for all keys and string values. No explanations, no fences.")
        user = "\n".join(user_parts)
        return {"role": "user", "content": user}
    
    def trim_st_memory(self):
        need_trim, trim_messages =  self.st_memory.trim_test()
        if need_trim:
            user_message = {
                "role": "user",
                "content": "Summarize all the historical conversations in briefly."
            }
            resp = self.invoke_model_messages(trim_messages + [user_message])
            self.st_memory.trim(trim_messages, {"role": "assistant", "content": resp.content} if hasattr(resp, 'content') else {"role": "assistant", "content": str(resp)})

    def generate(self, instruction: Optional[str], context: Optional[str] = None) -> Dict[str, Any]:
        # As this is a multi-turn agent, store prompt in short-term memory
        self.trim_st_memory()
        
        user_message = self.build_user_role_message(instruction=instruction, context=context)
        
        # allow tools to preprocess
        if "preprocess" in self.tools:
            instruction = self.tools["preprocess"](instruction)

        # call model - prefer chat/message-based API when available
        text = None
        try:
            history_messages = self.st_memory.snapshot()
          
            resp = self.invoke_model_messages(history_messages + [user_message])
            if hasattr(resp, 'content'):
                text = resp.content
                self.st_memory.push(user_message)
                self.st_memory.push({"role": "assistant", "content": text})
            else:
                text = str(resp)
                self.st_memory.push(user_message)
                self.st_memory.push({"role": "assistant", "content": str(resp)})
            
        except Exception:
            import traceback 
            traceback.print_exc()
        # try parse JSON result or structured strategy
        try:
            if text.startswith("```") and text.endswith("```"):
                text = text.strip("```").strip()
                if text.startswith("json"):
                    text = text[len("json"):].strip()
            parsed_json = json.loads(text)
            parsed = {"dsl": parsed_json, "notes": "json-structured"}
        except Exception:
            # fallback: try parse as DSL grammar lines
            try:
                strat = parse_strategy(text)
                parsed = {"dsl": strat, "notes": "parsed-grammar"}
            except Exception:
                parsed = {"dsl": text, "notes": "raw-output"}
        return parsed

# small test
if __name__ == "__main__":
    agent = DSLGeneratorAgent(model=gpt3_5_turbo)
    out = agent.generate(instruction="Below are two programs where the second program is the transformed version of the first program. Please reverse engineering comprehensive code transformation rules (DSL code) according to the given generic DSL grammar."
    """ Program#1: `
#include <stdio.h>

int fib_n(int num)
{
	if (num == 0 || num == 1)
	{
		return num;
	}
	return fib_n(num - 1) + fib_n(num - 2);
}

int main(void)
{
	int k;
	scanf("%d", &k);
	int fn = fib_n(k);
	k = printf("fib number is %d", fn);
	if (k > 0){
	    printf("TEST");
	}
	return 0;
}
Program #2
#include <stdio.h>

int fib_n(int num)
{
	return num;
}

int main(void)
{
	int k, empty = 0;
	scanf("%d", &k);
	int fn = fib_n(k);
	k = printf("fib number is %d", fn);
	if (k > 0){
	    printf("TEST");
	}
	return 0;
}
`""")
    print(out)
