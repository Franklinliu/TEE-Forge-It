import argparse
import json
import os
import logging
import time
from typing import Optional, Union
import numpy as np
import editdistance
import random
import difflib 
from .dsl_generator import DSLGeneratorAgent, LongTermMemory
from .dsl_verifier import DSLVerifierAgent
from .dsl_adapter import DSLAdapterAgent
from .dsl_applier import DSLApplierAgent
from .dsl_prompt import generate_seed_dsl
from .llm_usage import LLMUsageRecorder
from .fcu import FunctionCompareUtilities
from src.model.chatgpt import gpt3_5_turbo, gpt4o_mini, gpt4o, ChatOpenAI
from src.model.qwen import qwen3coder_30b

class PatchBackportOrchestrator:
    """Orchestrates the DSL agents: generate -> verify -> adapt -> apply.

    It shares long-term memory among agents and allows registering tools.
    """

    def __init__(self, repo_path: Optional[str], lt_memory_path: Optional[str] = None, log_path=None, logger: Optional[logging.Logger] = None, model: Optional[ChatOpenAI] = gpt4o_mini):
        self.repo_path = repo_path
        self.lt_memory = LongTermMemory(path=lt_memory_path) if lt_memory_path else LongTermMemory()
        # instantiate agents with the same long-term memory
        self.usage_recorder = LLMUsageRecorder()
        self.generator = DSLGeneratorAgent(model= model, lt_memory=self.lt_memory, usage_recorder=self.usage_recorder)
        self.verifier = DSLVerifierAgent(model= model,lt_memory=self.lt_memory, usage_recorder=self.usage_recorder)
        self.adapter = DSLAdapterAgent(model= model,lt_memory=self.lt_memory, usage_recorder=self.usage_recorder)
        self.applier = DSLApplierAgent(model=model,lt_memory=self.lt_memory, usage_recorder=self.usage_recorder)
        
        # register simple tools
        self.generator.register_tool("preprocess", self._preprocess)
        self.verifier.register_tool("lint", self._dsl_lint)
        
        self.fcu = FunctionCompareUtilities()
        self.pre_transform_clean_tokens = []
        self.post_transform_clean_tokens = []
        self.target_clean_tokens = []
        # configure per-instance logger: use provided logger, otherwise create a named logger
        if logger is not None:
            self.logger = logger
        else:
            name = f"patchbackport.{str(time.time())}"
            self.logger = logging.getLogger(name)
            fh = logging.FileHandler(os.path.join(log_path, f'patchbackport_{str(time.time())}_{random.randint(0, 999999)}.log'))
            fh.setLevel(logging.DEBUG)
            fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            fh.setFormatter(fmt)
            if not any(isinstance(h, logging.FileHandler) for h in self.logger.handlers):
                self.logger.addHandler(fh)
            if self.logger.level == 0:
                self.logger.setLevel(logging.DEBUG)
        
    def precompute_clean_tokens(self, pre_transform_code: str, post_transform_code: str, target_code: str):
        self.pre_transform_clean_tokens = self.fcu.get_cleaned_tokens(pre_transform_code)
        self.post_transform_clean_tokens = self.fcu.get_cleaned_tokens(post_transform_code)
        self.target_clean_tokens = self.fcu.get_cleaned_tokens(target_code)
        
        self.original_transform_diff_lines = difflib.unified_diff(a = pre_transform_code.splitlines(), b = post_transform_code.splitlines() )
        
        return self.pre_transform_clean_tokens, self.post_transform_clean_tokens, self.target_clean_tokens

    def compute_clean_tokens(self, code: str):
        return self.fcu.get_cleaned_tokens(code)
    
    def compare_clean_tokens(self, tokens1, tokens2):
        if np.array_equal(tokens1, tokens2):
            return True, "exact match"
        dis = editdistance.eval(tokens1, tokens2)
        if dis == 0:
            return True, "exact match"
        else:
            if dis <= 10:
                return True, f"not exact match, but only {dis} edits needed to transform"
            else:
                return False, f"not exact match, there may be {dis} edits need to transform"

    def _preprocess(self, instruction: str) -> str:
        # small preprocessing: trim and normalize whitespace
        if isinstance(instruction, Union[list, tuple]):
            return "\n\n".join(instruction)
        else:
            return instruction

    def _dsl_lint(self, dsl_text: str):
        # very small linter: ensure 'file:' appears before 'replace:'
        errors = []
        # if "replace:" in dsl_text and "file:" not in dsl_text:
        #     errors.append("replace directive without file context")
        return {"ok": not errors, "errors": errors}

    def run_pipeline(self, pre_transform_code: str, post_transform_code: str, target_code: str, expected_post_transform_target_code: str = None, dry_run: bool = True):
        self.precompute_clean_tokens(pre_transform_code, post_transform_code, target_code)
       

        def verify_res_str(gen_res, pre_transform_code=pre_transform_code, post_transform_code=post_transform_code):
            max_iter = 5
            iter_count = 0
            while iter_count < max_iter:

                applier_res = self.applier.apply(gen_res, target_code=pre_transform_code)
                patched = applier_res.get("patched") if isinstance(applier_res, dict) else applier_res

                self.logger.debug("[orchestrator] Apply DSL to pre-patch code, got:\n%s", patched)

                patched_clean_tokens = self.compute_clean_tokens(patched)
                ret, msg = self.compare_clean_tokens(patched_clean_tokens, self.post_transform_clean_tokens)
                
                if ret is False:
                    self.logger.debug("[orchestrator] Warning: Applying generated DSL to pre-patch code did not yield expected post-patch code.")
                    self.logger.debug("Got:\n%s", patched)
                    
                    a_norm = [line.strip() for line in post_transform_code.splitlines()]
                    b_norm = [line.strip() for line in patched.splitlines()]

                    diff = difflib.unified_diff(
                        a_norm,
                        b_norm,
                        fromfile='Generated', tofile='Program#2', lineterm=''
                    )
                    diff = "\n".join(diff)    
                    
                    self.logger.debug("Unified diff:\n%s", diff)                
                    
                    # Fix the DSL
                    fix_instr = (
                        "Applying the latest DSL rule-based actions to Program#1 did not reproduce Program#2",
                        "Regenerate the DSL code and Ensure the new DSL code is precise."
                    )
                    self.logger.debug("[orchestrator] Regenerating DSL...")
                    try:
                        gen_res = self.generator.generate(fix_instr)
                        self.logger.debug("[orchestrator] Generated:\n%s", gen_res.get("dsl"))
                        iter_count += 1
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        self.logger.debug("[orchestrator] Error during regeneration: %s", e)
                        return False, gen_res
                else:
                    self.logger.debug("[orchestrator] Metamorphic test passed: applying DSL to pre-patch code yielded expected post-patch code.")
                       
                    self.lt_memory.add_knowledge(source_code=pre_transform_code, dsl_transform=gen_res.get("dsl"), target_code=post_transform_code)
                    
                    return True, gen_res
            
            return False, gen_res
    
        # Inference of DSL
        self.logger.debug("[orchestrator] Generating DSL...")
        self.generator.configure_default_messages(pre_transform_code=pre_transform_code, post_transform_code=post_transform_code)
        
        gen_res = self.generator.generate(instruction="Generate the DSL code.")
        self.logger.debug("[orchestrator] Generated:\n%s", gen_res.get("dsl"))
        passed, gen_res = verify_res_str(gen_res=gen_res)
        self.logger.debug("[orchestrator] Final verified DSL:\n%s", gen_res.get("dsl", gen_res))
        
        
        # Adaption of DSL
        self.logger.debug("[orchestrator] Adapting DSL for new target...")
        adapted = self.adapter.adapt(dsl_payload=gen_res, old_target=pre_transform_code, old_target_transform = post_transform_code, target=target_code)
        self.logger.debug("[orchestrator] Final adapted DSL:\n%s", adapted.get("dsl", adapted))
        self.logger.debug("[orchestrator] Applying DSL to target code...")

        # Apply of DSL
        applier_res = self.applier.apply(adapted, target_code=target_code)
        patched = applier_res.get("patched") if isinstance(applier_res, dict) else applier_res
        self.logger.debug("[orchestrator] Patched code:\n%s", patched)
        
        # Debate of Patch
        debate_res = self.applier.self_debate()
        self.logger.debug("[orchestrator] Self-debate result: %s", debate_res.get("notes", ""))
        max_iter_debate = 3
        iter_count_debate = 0
        while debate_res.get("notes", "") != "self-debate-accepted" and debate_res.get("patched", None) is not None and iter_count_debate < max_iter_debate:
            self.logger.debug("[orchestrator] Self-debate suggested correction, updating patched code and debating again...")
            patched = debate_res.get("patched", patched)
            debate_res = self.applier.self_debate()
            self.logger.debug("[orchestrator] Self-debate result: %s", debate_res.get("notes", ""))

            iter_count_debate += 1

        if dry_run:
            self.logger.debug("[orchestrator] Dry run - patched code:\n%s", patched)
            if expected_post_transform_target_code is not None:
                expected_tokens = self.compute_clean_tokens(expected_post_transform_target_code)
                patched_tokens = self.compute_clean_tokens(patched)
                distance = editdistance.eval(expected_tokens, patched_tokens)
                similarity = 1 - distance / max(len(expected_tokens), 1)
                exact_match = distance == 0
                return {
                    "patched": patched,
                    "passed": passed,
                    "generated": gen_res,
                    "adapted": adapted,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "target_code": target_code,
                    "usage_report": self.usage_recorder.report(),
                    "exact_match": exact_match,
                    "similarity": similarity,
                }
            else:
                return {
                    "patched": patched,
                    "passed": passed,
                    "generated": gen_res,
                    "adapted": adapted,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "target_code": target_code,
                    "usage_report": self.usage_recorder.report(),
                }
        else:
            self.logger.debug("[orchestrator] Applying patches to repository...")
            # For simplicity, assume single file patching
            if self.repo_path:
                target_file = os.path.join(self.repo_path, "target_file.c")
                with open(target_file, "w") as f:
                    f.write(patched)
                self.logger.debug(f"[orchestrator] Patched file written to {target_file}")
                return {
                    "patched": patched,
                    "passed": passed,
                    "generated": gen_res,
                    "adapted": adapted,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "target_code": target_code,
                    "usage_report": self.usage_recorder.report(),
                }
            else:
                self.logger.debug("[orchestrator] No repository path provided, skipping file write.")
                return {
                    "patched": patched,
                    "passed": passed,
                    "generated": gen_res,
                    "adapted": adapted,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "target_code": target_code,
                    "usage_report": self.usage_recorder.report(),
                }
    
    def run_pipeline_training_dataset_gen(self, pre_transform_code: str, post_transform_code: str):
        self.post_transform_clean_tokens = self.compute_clean_tokens(post_transform_code)
        def verify_res_str(gen_res, pre_transform_code=pre_transform_code, post_transform_code=post_transform_code):
            max_iter = 5
            iter_count = 0
            while iter_count < max_iter:

                applier_res = self.applier.apply(gen_res, target_code=pre_transform_code)
                patched = applier_res.get("patched") if isinstance(applier_res, dict) else applier_res

                self.logger.debug("[orchestrator] Apply DSL to pre-patch code, got:\n%s", patched)

                patched_clean_tokens = self.compute_clean_tokens(patched)
                ret, msg = self.compare_clean_tokens(patched_clean_tokens, self.post_transform_clean_tokens)
                
                if ret is False:
                    self.logger.debug("[orchestrator] Warning: Applying generated DSL to pre-patch code did not yield expected post-patch code.")
                    self.logger.debug("Got:\n%s", patched)
                    
                    a_norm = [line.strip() for line in post_transform_code.splitlines()]
                    b_norm = [line.strip() for line in patched.splitlines()]

                    diff = difflib.unified_diff(
                        a_norm,
                        b_norm,
                        fromfile='Generated', tofile='Program#2', lineterm=''
                    )
                    diff = "\n".join(diff)    
                    
                    self.logger.debug("Unified diff:\n%s", diff)                
                    
                    # Fix the DSL
                    fix_instr = (
                        "Applying the latest DSL rule-based actions to Program#1 did not reproduce Program#2",
                        "Regenerate the DSL code and Ensure the new DSL code is precise."
                    )
                    self.logger.debug("[orchestrator] Regenerating DSL...")
                    try:
                        gen_res = self.generator.generate(fix_instr)
                        self.logger.debug("[orchestrator] Generated:\n%s", gen_res.get("dsl"))
                        iter_count += 1
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        self.logger.debug("[orchestrator] Error during regeneration: %s", e)
                        return False, gen_res
                else:
                    self.logger.debug("[orchestrator] Metamorphic test passed: applying DSL to pre-patch code yielded expected post-patch code.")
                    fact = """Program Transformation using DSL:
                    Program before: {program_before}
                    The edit actions (DSL code): {dsl_actions}
                    Program after: {program_after}
                    """.format(dsl_actions = gen_res.get("dsl"), program_before = pre_transform_code, program_after = post_transform_code)
                    self.lt_memory.add_knowledge(source_code=pre_transform_code, dsl_transform=gen_res.get("dsl"), target_code=post_transform_code)
                    
                    return True, gen_res
            
            return False, gen_res
    
        # Inference of DSL
        self.logger.debug("[orchestrator] Generating DSL...")
        self.generator.configure_default_messages(pre_transform_code=pre_transform_code, post_transform_code=post_transform_code)
        
        gen_res = self.generator.generate(instruction="Generate the DSL code.")
        self.logger.debug("[orchestrator] Generated:\n%s", gen_res.get("dsl"))
        passed, gen_res = verify_res_str(gen_res=gen_res)
        self.logger.debug("[orchestrator] Final verified DSL:\n%s", gen_res.get("dsl", gen_res))
        
        return {
                    "passed": passed,
                    "generated": gen_res,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "usage_report": self.usage_recorder.report(),
                }
       
                
    def run_baseline_llm(self, pre_transform_code: str, post_transform_code: str, target_code: str, expected_post_transform_target_code: str = None, dry_run: bool = True):
        applier_res = self.applier.apply_baseline_llm(target_code=target_code, sample_pre_transform=pre_transform_code, sample_post_transform= post_transform_code)
        patched = applier_res.get("patched") if isinstance(applier_res, dict) else applier_res
        self.logger.debug("[orchestrator] Patched code:\n%s", patched)
        
        if dry_run:
            self.logger.debug("[orchestrator] Dry run - patched code:\n%s", patched)
            if expected_post_transform_target_code is not None:
                expected_tokens = self.compute_clean_tokens(expected_post_transform_target_code)
                patched_tokens = self.compute_clean_tokens(patched)
                distance = editdistance.eval(expected_tokens, patched_tokens)
                similarity = 1 - distance / max(len(expected_tokens), 1)
                exact_match = distance == 0
                return {
                    "patched": patched,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "target_code": target_code,
                    "usage_report": self.usage_recorder.report(),
                    "exact_match": exact_match,
                    "similarity": similarity,
                }
            else:
                return {
                    "patched": patched,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "target_code": target_code,
                    "usage_report": self.usage_recorder.report(),
                }
        else:
            self.logger.debug("[orchestrator] Applying patches to repository...")
            # For simplicity, assume single file patching
            if self.repo_path:
                target_file = os.path.join(self.repo_path, "target_file.c")
                with open(target_file, "w") as f:
                    f.write(patched)
                self.logger.debug(f"[orchestrator] Patched file written to {target_file}")
                return {
                    "patched": patched,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "target_code": target_code,
                    "usage_report": self.usage_recorder.report(),
                }
            else:
                self.logger.debug("[orchestrator] No repository path provided, skipping file write.")
                return {
                    "patched": patched,
                    "pre_transfrom": pre_transform_code,
                    "post_transform": post_transform_code,
                    "target_code": target_code,
                    "usage_report": self.usage_recorder.report(),
                } 
    
def main_impl(repo: Optional[str], pre_transform_code: str, post_transform_code: str, target_code: str, expected_post_transform_target_code: str = None, dry_run: bool = True, log_path: str = None, logger: Optional[logging.Logger] = None):
    # create orchestrator with the provided logger (if any)
    orchestrator = PatchBackportOrchestrator(repo, log_path=log_path, logger=logger, model=qwen3coder_30b)

    res = orchestrator.run_pipeline(
        pre_transform_code=pre_transform_code,
        post_transform_code=post_transform_code,
        target_code=target_code,
        dry_run=dry_run,
        expected_post_transform_target_code=expected_post_transform_target_code,
    )

    out_logger = orchestrator.logger or logging.getLogger(__name__)
    out_logger.debug(json.dumps(res, indent=2, ensure_ascii=False))

    return res


def main_impl_training_dataset_gen(repo: Optional[str], pre_transform_code: str, post_transform_code: str, log_path: str = None, logger: Optional[logging.Logger] = None):
    # create orchestrator with the provided logger (if any)
    orchestrator = PatchBackportOrchestrator(repo, log_path=log_path, logger=logger, model = gpt4o_mini)

    res = orchestrator.run_pipeline_training_dataset_gen(
        pre_transform_code=pre_transform_code,
        post_transform_code=post_transform_code
    )

    out_logger = orchestrator.logger or logging.getLogger(__name__)
    out_logger.debug(json.dumps(res, indent=2, ensure_ascii=False))

    return res

def main_impl_baseline(repo: Optional[str], pre_transform_code: str, post_transform_code: str, target_code: str, expected_post_transform_target_code: str = None, dry_run: bool = True, log_path: str = None, logger: Optional[logging.Logger] = None):
    # create orchestrator with the provided logger (if any)
    orchestrator = PatchBackportOrchestrator(repo, log_path=log_path, logger=logger, model = qwen3coder_30b)

    res = orchestrator.run_baseline_llm(
        pre_transform_code=pre_transform_code,
        post_transform_code=post_transform_code,
        target_code=target_code,
        dry_run=dry_run,
        expected_post_transform_target_code=expected_post_transform_target_code
    )

    out_logger = orchestrator.logger or logging.getLogger(__name__)
    out_logger.debug(json.dumps(res, indent=2, ensure_ascii=False))

    return res

def main():
    parser = argparse.ArgumentParser(description="Patch backport orchestrator")
    parser.add_argument("--repo", help="Path to repository to apply changes", required= False, default=None)
    parser.add_argument("-i", "--input", help="Instruction to generate DSL from (string)")
    parser.add_argument("--pre-transform-code", help="Code before transform", required=True)
    parser.add_argument("--post-transform-code", help="Code after transform", required=True)
    parser.add_argument("--target-code", help="Target code to adapt and apply transformation to", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Don't actually apply changes")
    args = parser.parse_args()

   
    instruction = args.input or input("Describe what you want to do: ")
    pre_transform_code =  open(args.pre_transform_code).read() if os.path.isfile(args.pre_transform_code) else args.pre_transform_code
    post_transform_code = open(args.post_transform_code).read() if os.path.isfile(args.post_transform_code) else args.post_transform_code
    target_code = open(args.target_code).read() if os.path.isfile(args.target_code) else args.target_code
    
    main_impl(repo=args.repo, instruction=instruction, pre_transform_code=pre_transform_code, post_transform_code=post_transform_code, target_code=target_code, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

