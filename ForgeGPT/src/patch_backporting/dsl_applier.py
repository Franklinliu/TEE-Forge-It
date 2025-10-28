import os
import subprocess
import json
import difflib
from typing import Any, Dict, Optional
from langchain_openai import ChatOpenAI
from .llm_usage import LLMUsageRecorder
from .dsl_generator import ShortTermMemory, LongTermMemory
from .dsl_prompt import DSL_GRAMMAR
from src.model.chatgpt import gpt3_5_turbo, gpt4o_mini

class DSLApplierAgent:
    """Apply DSL actions to a repository or workspace.

    Responsibilities:
      - Parse DSL and perform file edits, patch application, or run commands.
      - Optionally call verifier/adapter agents as part of apply pipeline.
    """

    def __init__(self, model: Optional[ChatOpenAI] = None, lt_memory: Optional[LongTermMemory] = None, usage_recorder: Optional[LLMUsageRecorder] = None):
        self.model = model
        self.st_memory = ShortTermMemory()
        self.lt_memory = lt_memory or LongTermMemory()
        self.tools = {}
        self.usage_recorder = usage_recorder or LLMUsageRecorder()

    def clear_st_memory(self):
        self.st_memory = ShortTermMemory()

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

    def configure_default_messages(self):
        self.st_memory.buffer.clear()
        system = (
            """You are a code transformation assistant for C programs. Your task is to apply the code transformation rules (DSL Actions) to the new target code. The rules are expressed in the below domain-specific language (DSL) grammar:
            {dsl_grammar}
            """.format(dsl_grammar = DSL_GRAMMAR)
        )
      
        user_parts = ["Output exactly a JSON object {\"patched\": \"...full source...\"}. JSON requires double quotes for all keys and string values. No explanations, no fences."]
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
    
        user_parts.append("Output exactly a JSON object {\"patched\": \"...full source...\"}. JSON requires double quotes for all keys and string values. No explanations, no fences.")
        user = "\n".join(user_parts)
        return {"role": "user", "content": user}    
    
    def self_debate(self) -> Dict[str, Any]:
        """Given a DSL payload, target code, and patched code, attempt to self-debate the patch.

        This function will call the LLM to produce a debated patch. It returns a dict:
          {"patched": "<debated code>", "notes": ...}

        If the model is unavailable or fails, the original patched code is returned with a note.
        """
       
        prompt_parts = [
                """You are a code patch reviwewer. Your task is to review the previous program patch result of Neovim.""",
                "Follow the instrutions:\n",
                """
                * If the previous patch is incorrect, generate a new patched code as the result. Output exactly a JSON object {\"patched\": \"...full source...\"}. JSON requires double quotes for all keys and string values. No explanations, no fences.
                
                * If the previous patch is correct, output exactly the single token: YES (uppercase) with no surrounding text or code fences.
                """   
            ]
            
        prompt = "\n\n".join(prompt_parts)
        user_message = self.build_user_role_message(instruction=prompt)
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
            pass  
        
    
        if text.strip().lower().find("yes")!=-1:
                return {"notes": "self-debate-accepted"}
        else:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict) and parsed.get('patched'):
                        return {"patched": parsed.get('patched'), "notes": "self-corrected-model-json"}
                    else:
                        return {"patched": parsed, "notes": "self-corrected-model-json"}
                except Exception:
                    # not JSON, try strip fences and return raw
                    text = text.strip()
                            
                    if text.startswith('```'):
                        lines = text.splitlines()
                        if lines[0].startswith('```'):
                            try:
                                end_idx = len(lines) - 1 - lines[::-1].index('```')
                            except Exception:
                                end_idx = len(lines)
                                body = '\n'.join(lines[1:end_idx])
                                try:
                                    parsed = json.loads(body)
                                    if isinstance(parsed, dict) and parsed.get('patched'):
                                        return {"patched": parsed.get('patched'), "notes": "self-corrected-model-json"}
                                    else:
                                        return {"patched": parsed, "notes": "self-corrected-model-raw"} 
                                except Exception:
                                    return {"patched": body, "notes": "self-corrected-model-raw"}        
                    else:
                        return {"patched": text, "notes": "self-corrected-model-raw"}
        
       
    def apply(self, dsl_payload: Dict[str, Any], target_code: str) -> Dict[str, Any]:
        """Apply the structured DSL to a single target_code string.

        This function will call the LLM to produce the transformed code. It returns a dict:
          {"patched": "<transformed code>", "notes": ...}

        If the model is unavailable or fails, a conservative local text-level transformation is used
        and returned as the patched code.
        """
        
        self.configure_default_messages()
        
        dsl = dsl_payload.get("dsl", "")
        knowledges = self.lt_memory.query_similar_transforms(source_code=target_code, n_results=2)
        if len(knowledges)>0:
            print("Use RAG knowledge techinique")
        try:
            dsl = dsl if isinstance(dsl, dict) else json.loads(dsl)
            Rules = dsl.get('strategy', []) if isinstance(dsl, dict) else []
            Actions = Rules
        except Exception as e:
            # print("DSL is not valid JSON, cannot apply:", dsl, type(dsl))
            # print("Error:", str(e))
            Actions = [dsl]

        original = target_code
        # Build LLM prompt
        prompt_parts = (
                """Below is a patch (including function before and function after) from vim, paired with a corresponding function before from neovim. 
                Adapt the patch from vim to neovim by generating the function after based on the given function before.\n\n
                ### Patch Knowledge (vim): \n {knowledge} \n\n\n
                ### Function Before (neovim):\n{func_before_target}\n\n
                ### The edit actions (DSL code): {dsl_actions}\n\n
                ### Function After (neovim):\n""".format(func_before_target = original, knowledge = knowledges[0] if len(knowledges)>0 else "Empty", dsl_actions = Actions),
                "Output exactly a JSON object {\"patched\": \"...full source...\"}. Do NOT include any extra explanation, commentary, or markdown fences."  
            )
        prompt = "\n\n".join(prompt_parts)
        user_message = self.build_user_role_message(instruction=prompt)
        
        text = None
        try:
            history_messages = self.st_memory.snapshot()
            if hasattr(self.model, 'invoke_messages'):
                resp = self.invoke_model_messages(history_messages + [user_message])
                if hasattr(resp, 'content'):
                    text = resp.content
                    self.st_memory.push(user_message)
                    self.st_memory.push({"role": "assistant", "content": text})
                else:
                    text = str(resp)
                    self.st_memory.push(user_message)
                    self.st_memory.push({"role": "assistant", "content": str(resp)})
            else:
                # fallback: serialize role messages into a single prompt string
                serialized = ""
                for messsage in history_messages:
                    serialized = serialized + "[{role}]\n {content}\n".format(role = messsage["role"], content = messsage["content"])
                
                serialized = serialized + "[{role}]\n {content}\n".format(role = user_message["role"], content = user_message["content"])
               
                resp = self.invoke_model(serialized)
                
                if hasattr(resp, 'content'):
                    text = resp.content
                    self.st_memory.push(user_message)
                    self.st_memory.push({"role": resp["role"], "content": text})
                else:
                    text = str(resp)
                    self.st_memory.push(user_message)
                    self.st_memory.push({"role": "assistant", "content": str(resp)})
            
        except Exception:
            # final fallback: use old prompt string
            return {"patched": original, "notes": "model-failed"} 
        
        # try parse JSON result or structured strategy
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get('patched'):
                return {"patched": parsed.get('patched'), "notes": "model-json"}
        except Exception:
            # not JSON, try strip fences and return raw
            if text.strip().startswith('```'):
                        lines = text.splitlines()
                        if lines[0].startswith('```'):
                            try:
                                end_idx = len(lines) - 1 - lines[::-1].index('```')
                            except Exception:
                                end_idx = len(lines)
                            body = '\n'.join(lines[1:end_idx])
                            try:
                                return json.loads(body)  # test parse
                            except Exception:
                                return {"patched": body, "notes": "model-raw-fenced"}
            else:
                return {"patched": text, "notes": "model-raw"}
    
    def apply_baseline_llm(self, target_code: str, sample_pre_transform: Optional[str], sample_post_transform: Optional[str]):
        original = target_code
        # Build LLM prompt
        assert self.model is not None, "Model does not exist"
        prompt_parts = (
                """Below is a patch (including function before and function after) from vim, paired with a corresponding function before from neovim. 
                Adapt the patch from vim to neovim by generating the function after based on the given function before.\n\n
                ### Function Before (vim):\n{func_before_source}\n\n
                ### Function After (vim):\n{func_after_source}\n\n
                ### Function Before (neovim):\n{func_before_target}\n\n
                ### Function After (neovim):\n""".format(func_before_source = sample_pre_transform, func_after_source = sample_post_transform, func_before_target = original),
                "RESPONSE FORMAT: Return the full transformed source code as raw text, OR a JSON object {\"patched\": \"...full source...\"}. Do NOT include any extra explanation, commentary, or markdown fences."  
        )
        prompt = "\n\n".join(prompt_parts)
        try:
                resp = self.invoke_model(prompt)
                text = resp.content if hasattr(resp, "content") else str(resp)
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict) and parsed.get('patched'):
                        return {"patched": parsed.get('patched'), "notes": "model-json"}
                except Exception:
                    # not JSON, try strip fences and return raw
                    if text.strip().startswith('```'):
                        lines = text.splitlines()
                        if lines[0].startswith('```'):
                            try:
                                end_idx = len(lines) - 1 - lines[::-1].index('```')
                            except Exception:
                                end_idx = len(lines)
                            body = '\n'.join(lines[1:end_idx])
                            try:
                                return json.loads(body)  # test parse
                            except Exception:
                                return {"patched": body, "notes": "model-raw-fenced"}
                    return {"patched": text, "notes": "model-raw"}
        except Exception as e:
                # model failed; fallthrough to local fallback
                failure = str(e)
                return {"patched": original, "notes": "use original-model-failed:" + failure}

      

if __name__ == "__main__":
    applier = DSLApplierAgent(model=gpt4o_mini)
    sample = {'dsl': '{"strategy": [{"Remove": {"Node": "return fib_n(num - 1) + fib_n(num - 2);", "Scope": "func fib_n : int -> int"}}, {"Replace": {"Node1": "if (num == 0 || num == 1) { return num; }", "Node2": "return num;", "Scope": "func fib_n : int -> int"}}]}', 'notes': 'json-structured'}
    target = """
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
    print(applier.apply(dsl_payload=sample, target_code=target).get('patched', "Unknown result"))
