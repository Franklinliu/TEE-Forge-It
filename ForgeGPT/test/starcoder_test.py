# pip install -q transformers bitsandbytes accelerate
from huggingface_hub import login
import dotenv

dotenv.load_dotenv()

from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch
import os
# import gc

# # Clear GPU cache
# torch.cuda.empty_cache()
# gc.collect()

# Configure 8-bit quantization
quantization_config = BitsAndBytesConfig(
    load_in_8bit=True,
    llm_int8_threshold=6.0
)

checkpoint = "bigcode/starcoder"
# Use GPUs 1 and 2 (second and third GPUs)
os.environ["CUDA_VISIBLE_DEVICES"] = "1,2"
device = "cuda"  # for GPU usage or "cpu" for CPU usage

tokenizer = AutoTokenizer.from_pretrained(checkpoint)
model = AutoModelForCausalLM.from_pretrained(
    checkpoint,
    quantization_config=quantization_config,
    device_map="auto",  # Automatically distribute across available GPUs
    torch_dtype=torch.float16,  # Use half precision
    max_memory={0: "10GB", 1: "10GB"}  # Limit memory usage per GPU
)

inputs = tokenizer.encode("def print_hello_world():", return_tensors="pt").to(device)
outputs = model.generate(inputs)
print(tokenizer.decode(outputs[0]))
