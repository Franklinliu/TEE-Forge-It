# 使用ChatOpenAI访问GPT-3.5-turbo
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os 
load_dotenv()  # 从.env文件加载环境变量

OPEN_API_KEY = os.getenv("OPENAI_API_KEY")
# 请确保已设置OPENAI_API_KEY环境变量，或在此处直接传递api_key参数
gpt3_5_turbo = ChatOpenAI(
    model="gpt-3.5-turbo",
    temperature=0.7,
    api_key=OPEN_API_KEY
)

# 示例：
if __name__ == "__main__":
    prompt = "请用一句话介绍大语言模型的应用场景。"
    response = gpt3_5_turbo.invoke(prompt)
    print(response)
