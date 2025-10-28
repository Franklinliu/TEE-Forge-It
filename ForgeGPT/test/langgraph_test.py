from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langgraph.prebuilt import create_react_agent

@tool
def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"

model = ChatOpenAI(
    model="Qwen3-coder:30b", 
    api_key="hanruidong95",
    base_url="http://10.193.104.96:30000/v1",
    temperature=0.2
)

agent = create_react_agent(
    model=model,
    tools=[get_weather],
    prompt="You are a helpful assistant"
)

print(agent.invoke({"messages": [{"role": "user", "content": "what is the weather in sf"}]}))
