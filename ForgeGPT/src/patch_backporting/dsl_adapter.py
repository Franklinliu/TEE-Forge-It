from typing import Any, Dict, Optional
import json
import os
from langchain_openai import ChatOpenAI
from .dsl_generator import ShortTermMemory, LongTermMemory
from .llm_usage import LLMUsageRecorder
from .dsl_prompt import DSL_GRAMMAR
from src.model.chatgpt import gpt3_5_turbo, gpt4o_mini
from src.model.qwen import qwen3coder_30b
class DSLAdapterAgent:
    """Adapt generated DSL to target environments or styles.

    Responsibilities:
      - Take DSL and apply target-specific transformations (naming, feature flags).
      - Offer different adaptation strategies via tools/plugins.
    """

    def __init__(self, model: Optional[ChatOpenAI] = None, lt_memory: Optional[LongTermMemory] = None, usage_recorder: Optional[LLMUsageRecorder] = None):
        self.model = model 
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
        
    def adapt(self, dsl_payload: Dict[str, Any], target: str, old_target: str,  old_target_transform: str, scenario_type: Optional[str] = "patch") -> Dict[str, Any]:
        dsl_text = dsl_payload.get("dsl", "")
        prompt = (
            """You are an expert DSL transformer. Your task is to adapt an existing DSL to the new target code, resulting a new DSL code. The existing DSL code is learned from the given {scenario_type} pair <Target(old), DSL(old)>.\n
            {dsl_grammar}
            """.format(scenario_type=scenario_type, dsl_grammar = DSL_GRAMMAR),
            f"###Target(old):\n{old_target}",
            f"###DSL(old):\n{dsl_text}\n",
            f"###Target(new): {target}\n",
            f"###DSL(new):  \n",
            f"Follow the instrutions when generation the new DSL code:\n",
            """
                - For each rule from the old DSL, make an adaption of the rule according to the new target code. 
                - The new DSL code MUST be semantically similar to the old DSL code.
                - The number of new DSL rules equals to that of the rules in the old DSL code.
            """,  
            "Output exactly one JSON object and nothing else. No explanations, no fences. NOTE JSON requires double quotes for all keys and string values.\n"
        )
        resp = self.invoke_model(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        try:
            # replace ```json ... ``` if present
            if text.startswith("```") and text.endswith("```"):
                text = text.strip("```").strip()
                if text.startswith("json"):
                    text = text[len("json"):].strip()
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "dsl" in parsed:
                return {"dsl": parsed.get("dsl"), "notes": "json-structured"}
            else:
                return {"dsl": parsed, "notes": "json-structured"}
            
        except Exception:
            parsed = {"dsl": text, "notes": "raw-output"}
        return parsed


if __name__ == "__main__":
    agent = DSLAdapterAgent(model=gpt4o_mini)
    sample = {'dsl': '{"strategy": [{"Remove": {"Node": "return fib_n(num - 1) + fib_n(num - 2);", "Scope": "func fib_n : int -> int"}}, {"Replace": {"Node1": "if (num == 0 || num == 1) { return num; }", "Node2": "return num;", "Scope": "func fib_n : int -> int"}}]}', 'notes': 'json-structured'}
    old_target = """
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
    
    """
    target = """
#include <stdio.h>

int fib_n(int num)
{
	if (num == 2)
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
}"""
    print(agent.adapt(sample, target=target, old_target=old_target))
