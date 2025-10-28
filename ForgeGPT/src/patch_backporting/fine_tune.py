import os
import json
import openai
from typing import List, Dict, Any
import time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()  # 从.env文件加载环境变量

# 保持原有的数据集路径
finetune_dataset = "/workspaces/TEE-Forge-It/baseline/dataset/PPatHF/Neovim-Vim/finetune_training_dataset_gen_raw_result.json"

GEN_PATCH_PROMPT_TEMPLATE = {
    "prompt": """
Below are the programs before and after the patch.
###Program before: `{program_before}`\n
###Program after: `{program_after}`
""",
"completion": """
Edition rules within the Patch: `{patch_rules}`
"""
}
class FineTuner:
    def __init__(self, api_key: str = None):
        """初始化 FineTuner.
        
        Args:
            api_key: OpenAI API key. 如果为None，将从环境变量获取。
        """
        if api_key:
            openai.api_key = api_key
        else:
            openai.api_key = os.getenv("OPENAI_API_KEY")
            if not openai.api_key:
                raise ValueError("需要提供 OpenAI API key 或设置 OPENAI_API_KEY 环境变量")

    def prepare_training_data(self, data: List[Dict[str, Any]], output_file: str) -> str:
        """准备符合 OpenAI 微调格式的训练数据。
        
        Args:
            data: 原始训练数据列表
            output_file: 输出JSONL文件路径
            
        Returns:
            处理后的JSONL文件路径
        """
        formatted_data = []
        for item in data:
            
            new_item = {
                "prompt": GEN_PATCH_PROMPT_TEMPLATE["prompt"].format(program_before = item["pre_transfrom"], program_after = item["post_transform"]),
                "completion": GEN_PATCH_PROMPT_TEMPLATE["completion"].format(patch_rules = item["generated"]["dsl"])
            }
            
            # 确保包含必需的字段
            if "prompt" not in new_item or "completion" not in new_item:
                continue
                
            # 格式化为ChatGPT对话格式
            messages = [
                {"role": "system", "content": "You are an expert patch assistant with expertise in understanding and implementing patches between the following two programs, i.e., the program before the path, and the program after the patch."},
                {"role": "user", "content": new_item["prompt"]},
                {"role": "assistant", "content": new_item["completion"]}
            ]
            
            formatted_data.append({
                "messages": messages
            })
        
        # 写入JSONL格式
        with open(output_file, 'w', encoding='utf-8') as f:
            for item in formatted_data:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
                
        return output_file

    def validate_training_file(self, file_path: str) -> bool:
        """验证训练数据文件格式。"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    data = json.loads(line)
                    if "messages" not in data:
                        return False
                    for msg in data["messages"]:
                        if not all(k in msg for k in ("role", "content")):
                            return False
            return True
        except Exception as e:
            print(f"验证失败: {str(e)}")
            return False

    def create_fine_tune(self, 
                        training_file: str,
                        validation_file: str = None,
                        model: str = "gpt-3.5-turbo",
                        n_epochs: int = 3,
                        batch_size: int = 1,
                        learning_rate_multiplier: float = 1.0) -> str:
        """创建并启动微调任务。
        
        Args:
            training_file: 训练数据文件路径
            validation_file: 可选的验证数据文件路径
            model: 基础模型名称
            n_epochs: 训练轮数
            batch_size: 批次大小
            learning_rate_multiplier: 学习率倍数
            
        Returns:
            微调任务ID
        """
        # 验证训练文件
        if not self.validate_training_file(training_file):
            raise ValueError("训练数据文件格式无效")
            
        if validation_file and not self.validate_training_file(validation_file):
            raise ValueError("验证数据文件格式无效")
        
        # 上传文件
        with open(training_file, 'rb') as f:
            train_file = openai.File.create(file=f, purpose='fine-tune')
            
        val_file = None
        if validation_file:
            with open(validation_file, 'rb') as f:
                val_file = openai.File.create(file=f, purpose='fine-tune')
        
        # 创建微调任务
        job = openai.FineTuningJob.create(
            training_file=train_file.id,
            validation_file=val_file.id if val_file else None,
            model=model,
            hyperparameters={
                "n_epochs": n_epochs,
                "batch_size": batch_size,
                "learning_rate_multiplier": learning_rate_multiplier
            }
        )
        
        return job.id

    def monitor_fine_tune(self, job_id: str, wait: bool = True) -> Dict:
        """监控微调任务进度。
        
        Args:
            job_id: 微调任务ID
            wait: 是否等待任务完成
            
        Returns:
            任务状态信息
        """
        while True:
            job = openai.FineTuningJob.retrieve(job_id)
            status = job.status
            
            print(f"任务状态: {status}")
            if status == "succeeded":
                print(f"微调完成! 新模型: {job.fine_tuned_model}")
                return job
            elif status == "failed":
                print("微调失败")
                return job
                
            if not wait:
                return job
                
            print("等待中...")
            time.sleep(60)  # 每分钟检查一次

def load_finetune_dataset() -> List[Dict[str, Any]]:
    """加载微调数据集。"""
    if not os.path.exists(finetune_dataset):
        raise FileNotFoundError(f"找不到数据集文件: {finetune_dataset}")
        
    with open(finetune_dataset, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    data = list(filter(lambda item: item["passed"], data))
    return data

if __name__ == "__main__":
    # 加载并准备训练数据
    try:
        tuner = FineTuner()
        training_data = load_finetune_dataset()
        
        # 准备训练数据
        train_file = tuner.prepare_training_data(
            training_data,
            f"training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        )
        
        # # 开始微调
        # job_id = tuner.create_fine_tune(
        #     training_file=train_file,
        #     model="gpt-3.5-turbo",
        #     n_epochs=3
        # )
        # print(f"已创建微调任务: {job_id}")
        
        # # 监控进度
        # tuner.monitor_fine_tune(job_id)
    except Exception as e:
        print(f"微调过程出错: {str(e)}")
