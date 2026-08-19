import os
from dotenv import load_dotenv

load_dotenv()  # 加载 .env 文件（如果有）


def get_bot_token() -> str:
    """获取 Bot Token：优先读数据库，fallback 到环境变量"""
    # 1. 尝试从数据库读取
    try:
        from shared_lib.crud import get_bot_token as db_get_token
        token = db_get_token()
        if token:
            return token
    except Exception:
        pass

    # 2. Fallback：环境变量
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError(
            "未找到 Bot Token。请在 Dashboard → Bot 设置 中配置，"
            "或在 .env 文件中设置 DISCORD_BOT_TOKEN"
        )
    return token