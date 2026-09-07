import discord
from discord.ext import commands
from shared_lib import crud
import logging
import asyncio

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # cog_load 是 async 上下文，此时事件循环已存在，可用 asyncio.create_task。
        # 心跳作为独立后台任务启动，不依赖 on_ready 的同步流程是否走完，
        # 保证在线状态始终能及时上报（on_ready 里同步频道/成员可能较耗时）。
        try:
            asyncio.create_task(self._heartbeat_runner())
        except Exception as e:
            log.warning(f"[心跳] 任务创建失败: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        bot_id = getattr(self.bot, "bot_id", crud.DEFAULT_BOT_ID)

        # 成功上线：清除上一次的启动失败记录，让后台展示在线状态
        try:
            crud.set_bot_error(bot_id, None)
        except Exception:
            pass

        # ── 首次心跳：上报在线 + 延迟 ──
        latency_ms = int(self.bot.latency * 1000) if self.bot.latency is not None else None
        crud.update_bot_heartbeat(bot_id, latency_ms=latency_ms)

        # ── 同步服务器 ──
        crud.sync_guilds_from_discord(bot_id, self.bot.guilds)
        crud.add_system_event(
            source="bot",
            event_type="online",
            message=f"机器人 {self.bot.user.name} 已成功启动！"
        )

        # ── 同步频道（文字 + 论坛 + 帖子）批量收集后一次写入 ──
        text_count = forum_count = thread_count = member_count = 0

        for guild in self.bot.guilds:
            gid = str(guild.id)
            channel_batch = []

            for channel in guild.channels:
                if isinstance(channel, discord.TextChannel):
                    channel_batch.append({
                        "channel_id": str(channel.id),
                        "channel_name": channel.name,
                        "channel_type": "text",
                    })
                    text_count += 1

                elif isinstance(channel, discord.ForumChannel):
                    channel_batch.append({
                        "channel_id": str(channel.id),
                        "channel_name": channel.name,
                        "channel_type": "forum",
                    })
                    forum_count += 1

                    # 同步论坛中的活跃帖子
                    try:
                        for thread in channel.threads:
                            channel_batch.append({
                                "channel_id": str(thread.id),
                                "channel_name": f"[{channel.name}] {thread.name}",
                                "channel_type": "thread",
                                "parent_channel_id": str(channel.id),
                            })
                            thread_count += 1
                    except Exception as e:
                        log.warning(f"同步论坛帖子失败 {channel.name}: {e}")

            try:
                crud.bulk_upsert_channels(bot_id, gid, channel_batch)
            except Exception as e:
                log.warning(f"同步频道失败 {guild.name}: {e}")

            # ── 同步成员（批量写入，避免逐个提交导致 DB 锁竞争与事件循环阻塞）──
            try:
                batch = []
                for member in guild.members:
                    if member.bot:  # 跳过机器人自身和其他 Bot
                        continue
                    batch.append({
                        "user_id": str(member.id),
                        "username": member.name,
                        "nickname": member.nick or "",
                        "avatar_url": str(member.display_avatar.url) if member.display_avatar else "",
                    })
                member_count += crud.bulk_upsert_members(bot_id, gid, batch)
                # 让出事件循环，保证心跳循环等任务不被长时间阻塞
                await asyncio.sleep(0)
            except Exception as e:
                log.warning(f"同步成员失败 {guild.name}: {e}")

        print(f"📡 已缓存 {text_count} 个文字频道 + {forum_count} 个论坛 + {thread_count} 个帖子")
        print(f"👥 已缓存 {member_count} 个成员")
        print(f"✅ 已登录为: {self.bot.user.name} (ID: {self.bot.user.id})")
        print(f"📝 已同步 {len(self.bot.guilds)} 个服务器到数据库。")

        # ── 同步斜杠命令 ──
        try:
            synced = await self.bot.tree.sync()
            print(f"⚡ 已同步 {len(synced)} 条斜杠命令")
        except Exception as e:
            print(f"同步斜杠命令失败: {e}")

    async def _heartbeat_runner(self):
        """独立心跳后台任务：等待登录就绪后立即上报一次，随后按固定间隔持续上报。

        之所以独立于 on_ready：on_ready 中的频道/成员同步可能耗时较长，
        若心跳放在 on_ready 末尾，同步卡住时心跳就永远不会启动。
        """
        try:
            await self.bot.wait_until_ready()
        except Exception as e:
            log.warning(f"[心跳] wait_until_ready 失败: {e}")
            return
        while True:
            try:
                bot_id = getattr(self.bot, "bot_id", crud.DEFAULT_BOT_ID)
                latency_ms = int(self.bot.latency * 1000) if self.bot.latency is not None else None
                crud.update_bot_heartbeat(bot_id, latency_ms=latency_ms)
            except Exception as e:
                log.warning(f"[心跳] 上报失败: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
