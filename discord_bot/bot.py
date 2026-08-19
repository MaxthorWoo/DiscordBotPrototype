import discord
from discord.ext import commands

def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True  # 如果不需要读取消息内容可以关闭
    intents.members = True  # 需要 Server Members 权限，否则 guild.members 缓存为空，成员同步不到
    # 可以设置其他 intents
    bot = commands.Bot(command_prefix="!", intents=intents)
    return bot