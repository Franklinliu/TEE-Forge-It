from langchain_openai import ChatOpenAI

qwen3coder_30b = ChatOpenAI(
    model="Qwen3-coder:30b", 
    api_key="hanruidong95",
    base_url="http://10.193.104.96:30000/v1",
    temperature=0.7
)

# test code
if __name__ == "__main__":
    response = qwen3coder_30b.invoke(
        input=[
            {"role": "user", "content": "Write a Python function that adds two numbers."}
        ]
    )
    print(response.content)