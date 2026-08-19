"""消息调度器 Cog — 后台轮询待发任务并发送到 Discord"""

import asyncio
import datetime
import io
import logging

import discord
from discord.ext import commands, tasks

from shared_lib.crud import (
    DEFAULT_BOT_ID,
    get_pending_tasks,
    update_task_status,
    get_attachment_data,
    claim_pending_task,
)
from shared_lib.models import (
    TARGET_CHANNEL,
    TARGET_FORUM_NEW,
    TARGET_FORUM_REPLY,
    STATUS_PROCESSING,
    STATUS_SENT,
    STATUS_FAILED,
)

log = logging.getLogger(__name__)

# 轮询间隔（秒）
POLL_INTERVAL = 3
# 单条消息最大长度
MAX_CONTENT_LENGTH = 2000


class MessengerCog(commands.Cog):
    """消息广播调度器"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._poll_loop.start()

    def cog_unload(self):
        self._poll_loop.cancel()

    # ── 后台轮询 ────────────────────────────────────────

    @tasks.loop(seconds=POLL_INTERVAL)
    async def _poll_loop(self):
        """每 3 秒轮询待发送任务"""
        await self.bot.wait_until_ready()
        try:
            tasks_list = get_pending_tasks(DEFAULT_BOT_ID)  # 与 Dashboard 统一
            for task in tasks_list:
                # 原子领取：仅领取成功的实例才会发送，避免多实例重复发同一条消息
                if not claim_pending_task(task["id"]):
                    # 已被其他实例领取或处理，跳过
                    continue
                await self._process_task(task)
        except Exception as e:
            log.error(f"[Messenger] 轮询异常: {e}", exc_info=True)

    @_poll_loop.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()

    # ── 任务处理 ────────────────────────────────────────

    async def _process_task(self, task: dict):
        """处理单个发送任务"""
        task_id = task["id"]
        log.info(f"[Messenger] 开始处理任务 #{task_id} ({task.get('task_name', '')})")

        try:
            # 1. 解析目标
            guild = self.bot.get_guild(int(task["guild_id"]))
            if not guild:
                raise Exception(f"找不到服务器 guild_id={task['guild_id']}")

            target_type = task["target_type"]
            channel_id = int(task["channel_id"])
            content = task.get("content") or ""

            # 2. 获取附件文件
            files = []
            for att in task.get("attachments", []):
                data = get_attachment_data(att["id"])
                if data:
                    files.append(discord.File(
                        fp=io.BytesIO(data),
                        filename=att["filename"],
                        spoiler=False,
                    ))

            # 3. 按目标类型发送
            if target_type == TARGET_CHANNEL:
                await self._send_to_channel(guild, channel_id, content, files)

            elif target_type == TARGET_FORUM_NEW:
                await self._send_to_forum_new(
                    guild, channel_id, content, files,
                    thread_name=task.get("thread_name") or ""
                )

            elif target_type == TARGET_FORUM_REPLY:
                await self._send_to_forum_reply(
                    guild, channel_id, task.get("thread_id"),
                    content, files
                )

            else:
                raise Exception(f"未知的目标类型: {target_type}")

            update_task_status(task_id, STATUS_SENT, "")
            log.info(f"[Messenger] 任务 #{task_id} 发送成功")

        except Exception as e:
            error_msg = str(e)[:500]
            log.error(f"[Messenger] 任务 #{task_id} 失败: {error_msg}", exc_info=True)
            update_task_status(task_id, STATUS_FAILED, error_msg)

    # ── 发送方法 ────────────────────────────────────────

    async def _send_content_chunks(self, send_target, content: str, files: list):
        """将超过 2000 字的内容拆分为多条发送，附件只附在第一条"""
        if len(content) <= MAX_CONTENT_LENGTH:
            await send_target(content=content, files=files if files else None)
            return

        chunks = self._split_content(content)
        for i, chunk in enumerate(chunks):
            f = files if (i == 0 and files) else None
            await send_target(content=chunk, files=f)

    async def _send_to_channel(self, guild, channel_id: int, content: str, files: list):
        """普通频道消息"""
        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            raise Exception(f"找不到文字频道 channel_id={channel_id}")

        send_target = channel.send
        if len(content) <= MAX_CONTENT_LENGTH:
            await send_target(content=content, files=files if files else None)
            return

        chunks = self._split_content(content)
        for i, chunk in enumerate(chunks):
            f = files if (i == 0 and files) else None
            await send_target(content=chunk, files=f)

    async def _send_to_forum_new(self, guild, channel_id: int, content: str,
                                  files: list, thread_name: str):
        """论坛发新帖"""
        forum = guild.get_channel(channel_id)
        if not forum or not isinstance(forum, discord.ForumChannel):
            raise Exception(f"找不到论坛频道 channel_id={channel_id}")

        if not thread_name:
            thread_name = (content[:80] + "..." if len(content) > 80 else content)
            thread_name = thread_name.strip()

        # 第一个内容块作为帖子正文
        if len(content) <= MAX_CONTENT_LENGTH:
            thread = await forum.create_thread(
                name=thread_name,
                content=content,
                files=files if files else None,
            )
        else:
            chunks = self._split_content(content)
            thread = await forum.create_thread(
                name=thread_name,
                content=chunks[0],
                files=files if files else None,
            )
            # 后续分块回复到帖子
            for chunk in chunks[1:]:
                await thread.thread.send(content=chunk)

    async def _send_to_forum_reply(self, guild, channel_id: int,
                                    thread_id: str, content: str, files: list):
        """回复现有帖子"""
        forum = guild.get_channel(channel_id)
        if not forum or not isinstance(forum, discord.ForumChannel):
            raise Exception(f"找不到论坛频道 channel_id={channel_id}")

        thread = forum.get_thread(int(thread_id)) if thread_id else None
        if not thread:
            raise Exception(f"找不到帖子 thread_id={thread_id}")

        send_target = thread.send
        if len(content) <= MAX_CONTENT_LENGTH:
            await send_target(content=content, files=files if files else None)
            return

        chunks = self._split_content(content)
        for i, chunk in enumerate(chunks):
            f = files if (i == 0 and files) else None
            await send_target(content=chunk, files=f)

    # ── 工具方法 ────────────────────────────────────────

    @staticmethod
    def _split_content(content: str, max_len: int = MAX_CONTENT_LENGTH) -> list[str]:
        """将超长消息智能拆分，优先在换行处分割"""
        chunks = []
        while len(content) > max_len:
            # 在 max_len 范围内找最后一个换行
            split_at = content.rfind("\n", 0, max_len)
            if split_at == -1 or split_at < max_len // 2:
                # 没有合适的换行位置，在 max_len-3 处截断加续接符
                split_at = max_len - 3

            chunks.append(content[:split_at])
            content = content[split_at:].lstrip("\n")

        if content:
            chunks.append(content)
        return chunks


async def setup(bot: commands.Bot):
    await bot.add_cog(MessengerCog(bot))
    log.info("[Messenger] Cog 已加载")
