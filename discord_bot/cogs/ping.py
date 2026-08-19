import discord
from discord.ext import commands
from shared_lib import crud

class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="ping", description="测试机器人是否在线")
    async def ping(self, ctx: commands.Context):
        await ctx.send(crud._msg("ping_response", crud.DEFAULT_BOT_ID))

async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))