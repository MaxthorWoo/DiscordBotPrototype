import sys
import os

# 确保项目根目录在 sys.path，兼容直接运行 和 python -m discord_bot.main
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from shared_lib.crud import (
    init_default_bot, init_bot_messages, migrate_lottery_schema, migrate_bot_heartbeat,
)
from discord_bot.bot import create_bot
from discord_bot.config import get_bot_token

# 初始化数据库默认数据（仅首次运行）
init_default_bot()
init_bot_messages()
migrate_lottery_schema()  # 即开番赏固定奖池字段迁移
migrate_bot_heartbeat()   # bots 表心跳列迁移

async def main():
    bot = create_bot()
    # 加载所有 cogs（自动发现 cogs/ 目录下的所有 cog）
    await bot.load_extension("discord_bot.cogs.events")
    await bot.load_extension("discord_bot.cogs.ping")
    await bot.load_extension("discord_bot.cogs.trap")
    await bot.load_extension("discord_bot.cogs.giftcode")
    await bot.load_extension("discord_bot.cogs.messenger")
    await bot.load_extension("discord_bot.cogs.raffle")
    await bot.load_extension("discord_bot.cogs.lottery")
    await bot.load_extension("discord_bot.cogs.uid_collector")

    token = get_bot_token()
    await bot.start(token)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())