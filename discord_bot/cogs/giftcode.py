import discord
from discord.ext import commands
from shared_lib import crud


class GiftCodeCog(commands.Cog):
    """礼包码领取系统 — 玩家在频道发出口令消息即可领取"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1. 忽略机器人自己的消息
        if message.author.bot:
            return

        # 2. 只在服务器频道中使用
        if not message.guild:
            return

        command_text = message.content.strip().lower()
        if not command_text:
            return

        bot_id = crud.DEFAULT_BOT_ID
        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)
        user_id = str(message.author.id)
        user_name = str(message.author)

        # 3. 快速预检：没有匹配的活跃批次则直接忽略（不加锁，避免拖慢频道）
        if not crud.check_active_batch_exists(bot_id, guild_id, command_text):
            return

        print(f"[GiftCode] 用户 {user_name} 尝试使用口令 '{command_text}' 领取礼包码")

        # 4. 调用 atomic CRUD 领取
        result = crud.claim_gift_code(
            bot_id=bot_id,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            user_name=user_name,
            command_text=command_text,
        )

        reply_text = result["message"]

        # 5. 优先私信发送礼包码
        try:
            await message.author.send(reply_text)
        except (discord.Forbidden, discord.HTTPException):
            # 私信失败 → 频道内公开回复并 @ 对方，60 秒后自动删除
            await message.channel.send(
                f"{message.author.mention}，{reply_text}\n\n> *请开启私信权限以保护你的礼包码。*",
                delete_after=60,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(GiftCodeCog(bot))
