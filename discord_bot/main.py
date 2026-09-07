import sys
import os
import argparse

# 确保项目根目录在 sys.path，兼容直接运行 和 python -m discord_bot.main
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from shared_lib.crud import (
    init_default_bot, init_bot_messages, migrate_lottery_schema, migrate_bot_heartbeat,
    DEFAULT_BOT_ID, set_bot_error,
)
from discord_bot.bot import create_bot
from discord_bot.config import get_bot_token

# 初始化数据库默认数据（仅首次运行）
init_default_bot()
init_bot_messages()
migrate_lottery_schema()  # 即开番赏固定奖池字段迁移
migrate_bot_heartbeat()   # bots 表心跳列迁移

def _parse_args():
    parser = argparse.ArgumentParser(description="Discord Bot 进程")
    parser.add_argument(
        "--bot-id",
        default=None,
        help="指定要启动的机器人 bot_id（不传则使用 default_bot）",
    )
    return parser.parse_args()

async def main():
    args = _parse_args()
    bot_id = args.bot_id or DEFAULT_BOT_ID

    # 先取 Token：无 Token 时直接退出，避免加载 cog 后后台 task 空跑报错
    try:
        token = get_bot_token(bot_id)
    except ValueError as e:
        print(f"[Bot] bot_id={bot_id} 未配置 Token，进程退出：{e}")
        return

    bot = create_bot(bot_id=bot_id)
    # 加载所有 cogs（自动发现 cogs/ 目录下的所有 cog）
    await bot.load_extension("discord_bot.cogs.events")
    await bot.load_extension("discord_bot.cogs.ping")
    await bot.load_extension("discord_bot.cogs.trap")
    await bot.load_extension("discord_bot.cogs.giftcode")
    await bot.load_extension("discord_bot.cogs.messenger")
    await bot.load_extension("discord_bot.cogs.raffle")
    await bot.load_extension("discord_bot.cogs.lottery")
    await bot.load_extension("discord_bot.cogs.uid_collector")

    print(f"[Bot] 正在以 bot_id={bot_id} 启动...")
    try:
        await bot.start(token)
    except Exception as e:
        # 登录/启动失败（如 Token 无效、Privileged Intents 未开启等）：
        # 记录到数据库，供后台展示失败原因，然后非零退出（由启动器判定为快速失败）
        msg = f"{type(e).__name__}: {e}"
        print(f"[Bot] bot_id={bot_id} 启动失败：{msg}")
        try:
            set_bot_error(bot_id, msg)
        except Exception:
            pass
        raise SystemExit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())