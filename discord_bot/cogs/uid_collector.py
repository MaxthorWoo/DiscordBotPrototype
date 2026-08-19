"""UID 自动采集系统（多采集进程版）

功能：
1. 支持多个采集进程（Campaign），每个进程绑定一个频道、一套规则和时间范围。
2. 实时监听各 running 进程对应频道的新消息，按该进程的位数提取 UID。
3. 校验并打反应（有效 ✅ / 重复或无效 ❌）+ 重叠 / 同人多发 / 位数不符时质询回复。
4. 每个进程独立扫描历史（增量，message_id 去重），到结束时间自动结案。
5. 不同进程数据完全隔离（uid_records.campaign_id）。
6. Discord 管理员发的消息不采集。

跨进程通信：后台创建/编辑进程后写入 uid_campaigns 表，本 cog 定时轮询：
- 各 running 进程执行历史扫描
- 检查是否有进程需要触发首次全量扫描
- 检查过期进程自动结案
"""
import re
import asyncio
import logging
import datetime

import discord
from discord.ext import commands, tasks

from shared_lib import crud
from shared_lib.models import (
    UID_STATUS_VALID, UID_STATUS_DUPLICATE, UID_STATUS_INVALID,
    UID_REASON_OVERLAP, UID_REASON_MULTIPLE, UID_REASON_LENGTH,
    UID_CAMPAIGN_RUNNING, UID_CAMPAIGN_ENDED,
)

log = logging.getLogger(__name__)

# 扫描轮询间隔（秒）
SCAN_POLL_INTERVAL = 5
# 扫描历史时批量处理的消息数
SCAN_BATCH_SIZE = 50


def _extract_uid(text: str, length: int) -> tuple:
    """从消息文本中提取 UID。

    返回 (uid, has_digit):
    - 优先匹配恰好 length 位的连续数字（前后不接数字），取第一个。
    - 若没有恰 length 位的，但有其它位数连续数字，has_digit=True, uid=None。
    - 完全没有数字，has_digit=False。
    """
    if not text:
        return None, False
    # 恰好 length 位，前后不接数字
    m = re.search(rf'(?<!\d)\d{{{length}}}(?!\d)', text)
    if m:
        return m.group(0), True
    # 存在任意连续数字（至少 1 位）
    if re.search(r'\d', text):
        return None, True
    return None, False


def _extract_answer(text: str) -> str:
    """宽松提取"答案"作为附加信息（不校验对错，抓不到返回空）。

    规则（按优先级）：
    1. "答案[:：] X" / "answer[:：] X" / "answer is X"
    2. "my answer is X"
    3. 整条消息只是一个大写字母
    """
    if not text:
        return ""
    m = re.search(r'答案\s*[:：]\s*([A-Za-z0-9]{1,6})', text)
    if m:
        return m.group(1).upper()
    m = re.search(r'answer\s*(?:[:：]|is)\s*([A-Za-z0-9]{1,6})', text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(r'my\s+answer\s+is\s+([A-Za-z0-9]{1,6})', text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    if re.fullmatch(r'\s*[A-Z]\s*', text):
        return text.strip().upper()
    return ""


def _mention_list(user_ids: list) -> list:
    return [f"<@{uid}>" for uid in user_ids]


def _render_template(template: str, **kwargs) -> str:
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value))
    return template


class UIDCollectorCog(commands.Cog):
    """UID 自动采集（多进程）"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot_id = crud.DEFAULT_BOT_ID
        # 最近处理的消息 key（进程内去重），格式 "campaign_id:message_id"
        self._recent_message_keys = {}
        # 记录哪些进程已完成首次全量扫描，避免每次轮询都重复扫
        self._campaign_scanned_once = set()

    # ==================== 工具方法 ====================

    def _is_admin(self, message: discord.Message) -> bool:
        """Discord 服务器管理员不采集"""
        if not message.guild or message.author.bot:
            return False
        perms = getattr(message.author, "guild_permissions", None)
        if perms is None:
            return False
        return bool(perms.administrator)

    def _campaign_in_time_window(self, camp) -> bool:
        """进程是否在有效时间窗口内（started_at <= now <= end_at）"""
        now = datetime.datetime.utcnow()
        if camp.started_at and now < camp.started_at:
            return False
        if camp.end_at and now > camp.end_at:
            return False
        return True

    # ==================== 核心处理 ====================

    async def _process_message(self, message: discord.Message, camp, scanned: bool = False):
        """按某个进程的规则处理单条消息"""
        # 忽略机器人 / DM
        if message.author.bot or not message.guild:
            return
        gid = str(message.guild.id)
        chid = str(message.channel.id)
        campaign_id = camp.id

        # 频道匹配（进程绑定的频道）
        if chid != str(camp.channel_id):
            return
        # 管理员不采集
        if self._is_admin(message):
            return

        # 进程级去重：同一进程内同一消息只处理一次
        msg_key = f"{campaign_id}:{message.id}"
        if msg_key in self._recent_message_keys:
            return
        self._recent_message_keys[msg_key] = True
        if len(self._recent_message_keys) > 5000:
            self._recent_message_keys.clear()

        text = message.content or ""
        uid_length = camp.uid_length or 8
        uid, has_digit = _extract_uid(text, uid_length)

        # 完全没有数字 → 无效参与，跳过
        if not has_digit:
            return

        answer = _extract_answer(text)
        user_id = str(message.author.id)
        user_name = str(message.author)
        mentioned = [str(m.id) for m in message.mentions]

        # ── 判定 ──
        if uid:
            existing_by_uid = crud.uid_find_valid_by_uid(self.bot_id, campaign_id, uid)
            existing_by_user = crud.uid_find_valid_by_user(self.bot_id, campaign_id, user_id)

            if existing_by_uid:
                first = existing_by_uid[0]
                status = UID_STATUS_DUPLICATE
                reason = UID_REASON_OVERLAP
                if first.user_id == user_id:
                    # 同一人重复，忽略不回复
                    await self._react(message, camp, "duplicate")
                    crud.uid_upsert_record(
                        self.bot_id, campaign_id, gid, chid, str(message.id),
                        user_id, user_name, uid, answer, status, reason, text, mentioned, scanned)
                    return
                # 不同人 → 重叠质询
                await self._react(message, camp, "duplicate")
                await self._reply_query(message, camp, "overlap", uid=uid)
                crud.uid_upsert_record(
                    self.bot_id, campaign_id, gid, chid, str(message.id),
                    user_id, user_name, uid, answer, status, reason, text, mentioned, scanned)
                return
            elif existing_by_user:
                # 同一用户已发过【不同】UID → 只能发一个，最新作废
                await self._react(message, camp, "duplicate")
                await self._reply_query(message, camp, "multiple", uid=uid)
                crud.uid_upsert_record(
                    self.bot_id, campaign_id, gid, chid, str(message.id),
                    user_id, user_name, uid, answer,
                    UID_STATUS_INVALID, UID_REASON_MULTIPLE, text, mentioned, scanned)
                return
            else:
                # 全新有效 UID
                await self._react(message, camp, "valid")
                crud.uid_upsert_record(
                    self.bot_id, campaign_id, gid, chid, str(message.id),
                    user_id, user_name, uid, answer,
                    UID_STATUS_VALID, None, text, mentioned, scanned)
                return
        else:
            # 有数字但位数不符 → 无效 + 质询
            await self._react(message, camp, "duplicate")
            await self._reply_query(message, camp, "length", uid="")
            crud.uid_upsert_record(
                self.bot_id, campaign_id, gid, chid, str(message.id),
                user_id, user_name, "", answer,
                UID_STATUS_INVALID, UID_REASON_LENGTH, text, mentioned, scanned)
            return

    async def _react(self, message: discord.Message, camp, kind: str):
        """给消息添加反应（kind: valid / duplicate）"""
        emoji = camp.valid_reaction if kind == "valid" else camp.duplicate_reaction
        if not emoji:
            return
        try:
            await message.add_reaction(emoji)
        except discord.Forbidden:
            log.warning(f"[UID] 添加反应失败（无权限）: {emoji}")
        except discord.HTTPException as e:
            log.warning(f"[UID] 添加反应失败(HTTP {e.status}): {emoji}")
        except Exception as e:
            log.warning(f"[UID] 添加反应异常: {emoji} -> {e!r}")

    async def _reply_query(self, message: discord.Message, camp, kind: str, uid: str):
        """在消息下回复并 @ 质询"""
        if kind == "overlap":
            template = camp.msg_overlap or ""
        elif kind == "multiple":
            template = camp.msg_multiple or ""
        else:  # length
            template = camp.msg_length or "@{user} 你消息里的数字位数与要求不符，请确认是否为 {uid_length} 位 UID。"
        if not template:
            log.warning(f"[UID] 质询模板为空，kind={kind}，未回复")
            return
        try:
            text = _render_template(
                template,
                user=message.author.mention,
                uid=uid,
                uid_length=camp.uid_length or 8,
            )
            await message.reply(text)
        except discord.Forbidden:
            log.warning(f"[UID] 质询回复失败（无发送消息权限）: {kind}")
        except discord.HTTPException as e:
            log.warning(f"[UID] 质询回复失败(HTTP {e.status}): {kind}")
        except Exception as e:
            log.warning(f"[UID] 质询回复异常: {kind} -> {e!r}")

    # ==================== 实时监听 ====================

    @commands.Cog.listener()
    async def on_ready(self):
        """启动扫描轮询循环"""
        if not self._scan_loop.is_running():
            self._scan_loop.start()
        print("[UID] UID 采集 cog 已就绪，扫描轮询已启动")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            if message.author.bot or not message.guild:
                return
            chid = str(message.channel.id)
            # 找到该频道所有 running 进程（一个频道至多一个，但保险起见遍历）
            for camp in crud.uid_get_running_campaigns(self.bot_id):
                if str(camp.channel_id) == chid:
                    if not self._campaign_in_time_window(camp):
                        continue
                    await self._process_message(message, camp, scanned=False)
        except Exception as e:
            log.warning(f"[UID] 实时处理失败: {e}")

    # ==================== 历史扫描与轮询 ====================

    @tasks.loop(seconds=SCAN_POLL_INTERVAL)
    async def _scan_loop(self):
        try:
            if not self.bot.is_ready():
                return
            # 1. 过期进程自动结案
            ended = crud.uid_end_expired_campaigns(self.bot_id)
            if ended:
                print(f"[UID] {ended} 个进程已到结束时间，自动结案")
            # 2. 遍历所有 running 进程做增量扫描
            for camp in crud.uid_get_running_campaigns(self.bot_id):
                if not self._campaign_in_time_window(camp):
                    continue
                await self._run_scan(camp)
            # 3. 处理手动扫描任务（查漏补缺）
            await self._process_scan_tasks()
        except Exception as e:
            log.warning(f"[UID] 扫描轮询异常: {e}")

    async def _process_scan_tasks(self):
        """轮询并执行待处理的手动扫描任务。"""
        for task in crud.uid_get_pending_scan_tasks(self.bot_id):
            if not crud.uid_claim_scan_task(task.id):
                continue  # 已被其他实例领取
            await self._manual_scan(task)

    async def _manual_scan(self, task):
        """执行一次手动全量扫描（基于进程时间范围过滤），并写回结果。

        用于 bot 掉线后查漏补缺。统计：
        - scanned_new: 本次新增采集的记录数
        - scanned_dup: 已采集过的重复消息数（跳过）
        - out_of_window: 超出进程时间范围被忽略的消息数
        """
        campaign_id = task.campaign_id
        import datetime as _dt
        from shared_lib.models import UIDCampaign, UIDRecord
        # 直接拿 ORM 对象（_process_message 需属性访问），并取原始时间/已采集 message_id
        camp = None
        started_dt, ended_dt = None, None
        existing = set()
        s = crud.SessionLocal()
        try:
            camp = s.query(UIDCampaign).filter_by(
                bot_id=self.bot_id, id=campaign_id).first()
            if camp:
                started_dt = camp.started_at
                ended_dt = camp.end_at
            rows = s.query(UIDRecord.message_id).filter(
                UIDRecord.bot_id == self.bot_id,
                UIDRecord.campaign_id == campaign_id,
            ).all()
            existing = {r[0] for r in rows}
        finally:
            s.close()

        if not camp:
            crud.uid_finish_scan_task(task.id, error="进程不存在")
            return

        channel_id = str(camp.channel_id)
        channel = self.bot.get_channel(int(channel_id)) if channel_id.isdigit() else None
        if not channel:
            crud.uid_finish_scan_task(task.id, error=f"找不到频道 {channel_id}，请确认 Bot 还在该服务器")
            return

        scanned_new = 0
        scanned_dup = 0
        out_of_window = 0
        now = _dt.datetime.utcnow()

        try:
            async for msg in channel.history(limit=None):
                # 时间范围过滤：只采纳进程时间范围内的消息
                msg_dt = msg.created_at.replace(tzinfo=None) if msg.created_at.tzinfo else msg.created_at
                if started_dt and msg_dt < started_dt:
                    out_of_window += 1
                    continue
                if ended_dt and msg_dt > ended_dt:
                    out_of_window += 1
                    continue
                if not msg.author.bot and msg.guild:
                    msg_key = f"{campaign_id}:{msg.id}"
                    if str(msg.id) in existing or msg_key in self._recent_message_keys:
                        scanned_dup += 1
                    else:
                        await self._process_message(msg, camp, scanned=True)
                        scanned_new += 1
        except discord.Forbidden:
            crud.uid_finish_scan_task(task.id, error="无权限读取频道历史")
            return
        except Exception as e:
            log.warning(f"[UID] 手动扫描异常: {e}")
            crud.uid_finish_scan_task(task.id, error=f"扫描异常: {e}")
            return

        result = {
            "scanned_new": scanned_new,
            "scanned_dup": scanned_dup,
            "out_of_window": out_of_window,
            "processed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        crud.uid_finish_scan_task(task.id, result=result)
        crud.add_system_event(
            "bot", "uid_scan",
            f"[{camp.name}] 手动扫描完成：新增 {scanned_new} 条，重复 {scanned_dup} 条，"
            f"超出时间范围忽略 {out_of_window} 条"
        )
        print(f"[UID] [{camp.name}] 手动扫描完成：新增 {scanned_new}，重复 {scanned_dup}，忽略 {out_of_window}")

    @_scan_loop.before_loop
    async def _before_scan_loop(self):
        await self.bot.wait_until_ready()

    async def _run_scan(self, camp):
        """对某个进程做增量历史扫描。首次启动时全量扫一次，之后增量。"""
        campaign_id = camp.id
        guild_id = str(camp.guild_id)
        channel_id = str(camp.channel_id)

        channel = self.bot.get_channel(int(channel_id)) if channel_id.isdigit() else None
        if not channel:
            return

        # 首次扫描：记录一次日志，全量从头扫
        is_first = campaign_id not in self._campaign_scanned_once
        if is_first:
            crud.add_system_event(
                "bot", "uid_scan", f"[{camp.name}] 开始全量扫描频道 #{getattr(channel, 'name', channel_id)} 的历史消息…")
            self._campaign_scanned_once.add(campaign_id)

        processed = 0
        scanned = 0

        # 增量游标：从已处理的最早消息继续往下扫
        before = None
        cursor = camp.last_scan_message_id or ""
        if cursor and cursor.isdigit():
            before = discord.Object(id=int(cursor))

        try:
            while True:
                history = []
                async for msg in channel.history(before=before, limit=SCAN_BATCH_SIZE):
                    history.append(msg)
                if not history:
                    break
                for msg in history:
                    processed += 1
                    await self._process_message(msg, camp, scanned=True)
                    scanned += 1
                    if processed % SCAN_BATCH_SIZE == 0:
                        await asyncio.sleep(0)
                before = discord.Object(id=history[-1].id)
                if len(history) < SCAN_BATCH_SIZE:
                    break
        except discord.Forbidden:
            crud.add_system_event("bot", "uid_scan", f"[{camp.name}] 扫描失败：无权限读取频道 {channel_id}")
            return
        except Exception as e:
            crud.add_system_event("bot", "uid_scan", f"[{camp.name}] 扫描异常: {e}")
            return

        if before:
            crud.uid_set_last_scan(self.bot_id, campaign_id, str(before.id))

        if is_first or scanned > 0:
            stats = crud.uid_get_statistics(self.bot_id, campaign_id)
            crud.add_system_event(
                "bot", "uid_scan",
                f"[{camp.name}] 扫描完成：本次处理 {scanned} 条，累计有效 {stats['valid']}，重复 {stats['duplicate']}，无效 {stats['invalid']}"
            )
            print(f"[UID] [{camp.name}] 扫描完成，本次处理 {scanned} 条")


async def setup(bot: commands.Bot):
    await bot.add_cog(UIDCollectorCog(bot))
