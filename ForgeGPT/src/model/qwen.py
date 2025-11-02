import os 
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from concurrent.futures import ProcessPoolExecutor, as_completed

load_dotenv()

QWEN3_API_KEY = os.getenv("QWEN3_API_KEY")

qwen3coder_30b = ChatOpenAI(
    model="Qwen3-coder:30b", 
    api_key= QWEN3_API_KEY,
    base_url="http://10.193.104.96:30000/v1",
    temperature=0.7
)

def test():
    response = qwen3coder_30b.invoke(
        input=[
            {"role": "user", "content": "Write a Python function that adds two numbers."}
        ]
    )
    print(response.content)
    return response.content


# Test the parallel performance of qwen3coder_30b

def compute_square(x):
    return x * x

data = range(1, 20)
    

# test code
if __name__ == "__main__":
    # test()
        
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(test) for n in data]
        for f in as_completed(futures):
            print(f.result())
        
        
        
        