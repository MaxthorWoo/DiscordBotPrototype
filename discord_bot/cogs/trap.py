import discord
from discord.ext import commands
from shared_lib import crud
from shared_lib.models import SessionLocal, TrapConfig

class TrapCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1. 忽略机器人自己的消息
        if message.author.bot:
            return

        # 2. 忽略私信（没有 guild 表示私信）
        if not message.guild:
            return

        # 3. 从数据库获取陷阱配置
        config = self._get_trap_config(message.guild.id)
        if not config or not config.is_enabled:
            return

        # 4. 检查是否在陷阱频道（如果未设置陷阱频道，则不执行）
        if not config.trap_channel_id:
            return
        if str(message.channel.id) != config.trap_channel_id:
            return

        # 5. 检查是否白名单
        if self._is_whitelisted(message.author, message.guild, config):
            return

        # 6. 执行踢出
        await self._kick_user(message, config)

    def _get_trap_config(self, guild_id: int):
        """从数据库读取陷阱配置"""
        session = SessionLocal()
        try:
            return session.query(TrapConfig).filter_by(
                bot_id=crud.DEFAULT_BOT_ID,
                guild_id=str(guild_id)
            ).first()
        finally:
            session.close()

    def _is_whitelisted(self, user: discord.Member, guild: discord.Guild, config: TrapConfig) -> bool:
        """检查用户是否在白名单中"""
        # 管理员永远豁免
        if user.guild_permissions.administrator:
            return True

        # 检查角色白名单（如果配置了）
        if config.whitelist_roles:
            whitelist_role_ids = set(config.whitelist_roles.split(','))
            user_role_ids = {str(role.id) for role in user.roles}
            if user_role_ids & whitelist_role_ids:
                return True

        # 检查用户白名单（如果配置了）
        if config.whitelist_users:
            if str(user.id) in config.whitelist_users.split(','):
                return True

        return False

    async def _kick_user(self, message: discord.Message, config: TrapConfig):
        """执行踢人并删除消息（通过封禁+即时解封实现）"""
        try:

            # 封禁用户并删除其 1 小时内的消息
            await message.guild.ban(
                message.author,
                reason=f"在陷阱频道 {message.channel.name} 发言",
                delete_message_seconds=3600  # 删除 1 小时内的消息
            )

            # 立即解封用户（使其可以重新加入服务器）
            await message.guild.unban(
                message.author,
                reason="陷阱功能：自动解封（仅用于清除消息）"
            )

            # 记录日志
            crud.add_trap_log(
                bot_id=crud.DEFAULT_BOT_ID,
                guild_id=str(message.guild.id),
                channel_id=str(message.channel.id),
                user_id=str(message.author.id),
                user_name=str(message.author),
                reason=f"在陷阱频道发言: {config.kick_message} (已封禁并解封以清除1小时消息)"
            )
            print(f"🪤 已通过封禁+解封方式处理 {message.author}，并清除了1小时消息")

        except discord.Forbidden:
            print(f"⚠️ 机器人没有权限封禁/解封 {message.author}，请检查机器人角色权限")
        except Exception as e:
            print(f"❌ 操作失败: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(TrapCog(bot))