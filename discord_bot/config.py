import os
from dotenv import load_dotenv

load_dotenv()  # 加载 .env 文件（如果有）


def get_bot_token(bot_id: str = None) -> str:
    """获取 Bot Token：优先读数据库（按 bot_id），fallback 到环境变量"""
    # 1. 尝试从数据库读取
    try:
        from shared_lib.crud import get_bot_token as db_get_token
        token = db_get_token(bot_id)
        if token:
            return token
    except Exception:
        pass

    # 2. Fallback：环境变量（仅在未指定 bot_id 时使用，避免串号）
    if not bot_id:
        token = os.getenv("DISCORD_BOT_TOKEN")
        if token:
            return token

    # 未找到对应 bot 的 token
    raise ValueError(
        "未找到 Bot Token。请在 Dashboard → Bot 设置 中配置该机器人，"
        "或在 .env 文件中设置 DISCORD_BOT_TOKEN"
    )