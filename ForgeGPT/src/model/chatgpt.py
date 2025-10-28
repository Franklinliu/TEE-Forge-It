# 使用ChatOpenAI访问GPT-3.5-turbo
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from typing import List
import os 
from langgraph.prebuilt import create_react_agent
from langchain.tools import tool


load_dotenv()  # 从.env文件加载环境变量


OPEN_API_KEY = os.getenv("OPENAI_API_KEY")
# 请确保已设置OPENAI_API_KEY环境变量，或在此处直接传递api_key参数
gpt3_5_turbo = ChatOpenAI(
    model="gpt-3.5-turbo",
    temperature=1,
    api_key=OPEN_API_KEY,
    stream_usage=True
)
gpt4o_mini = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.5,
    api_key=OPEN_API_KEY,
    stream_usage=True 
)

gpt4o = ChatOpenAI(
    model="gpt-4o",
    temperature = 1,
    api_key = OPEN_API_KEY,
    stream_usage = True
)

@tool 
def get_weather(city):
    """Get the weather in a given city today."""
    return f"The weather in {city} is sunny."

def create_user_messages(prompt: str) -> List[dict]:
    """Create user messages for agent invocation."""
    return [{"role": "user", "content": prompt}]

# 示例：
if __name__ == "__main__":
    prompt = "请用一句话介绍大语言模型的应用场景。"
    
    response = gpt3_5_turbo.invoke(prompt)
    print(response)
    
    agent = create_react_agent(model=gpt3_5_turbo, tools = [get_weather], prompt="You are a helpful assistant")
    response = agent.invoke({"messages": create_user_messages("What is the weather of Beijing today?")}, config={"recursion_limit": 50})
    print(response)
