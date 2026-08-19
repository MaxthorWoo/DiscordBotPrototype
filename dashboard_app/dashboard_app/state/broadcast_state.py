"""广播页面状态 — 服务器/频道选择 + 消息编辑 + @mention + 实时预览"""

import asyncio
import base64
import datetime
import re

import reflex as rx

from shared_lib import crud
from shared_lib.models import (
    TARGET_CHANNEL, TARGET_FORUM_NEW, TARGET_FORUM_REPLY,
    SCHEDULE_IMMEDIATE, SCHEDULE_TIMED,
    STATUS_DRAFT, STATUS_PENDING,
)


class BroadcastState(rx.State):
    # ── Bot / Guild ────────────────────────────────────
    current_bot_id: str = ""
    bots_list: list[dict] = []
    selected_guild_id: str = ""
    guilds_list: list[dict] = []

    # ── 频道选择 ───────────────────────────────────────
    channels_text: list[dict] = []
    channels_forum: list[dict] = []
    channels_threads: list[dict] = []
    filtered_threads: list[dict] = []     # 按当前选中论坛过滤后的帖子
    selected_channel_id: str = ""

    # ── 目标类型 ───────────────────────────────────────
    target_type: str = TARGET_CHANNEL
    thread_name: str = ""               # forum_new 时的帖子标题
    selected_thread_id: str = ""        # forum_reply 时选中的帖子
    selected_thread_parent_channel: str = ""  # 帖子所属论坛 ID

    # ── 消息内容 ───────────────────────────────────────
    content: str = ""

    # ── @提及 ──────────────────────────────────────────
    mention_search: str = ""
    mention_results: list[dict] = []    # 搜索结果
    member_cache: list[dict] = []       # 当前服务器成员
    mention_mode: str = "member"         # "member" / "channel"
    mention_panel_open: bool = False     # 面板是否可见
    channel_search_hits: list[dict] = []  # #频道引用搜索结果

    # ── 定时 ──────────────────────────────────────────
    schedule_type: str = SCHEDULE_IMMEDIATE
    scheduled_date: str = ""
    scheduled_time: str = ""

    # ── 附件 ──────────────────────────────────────────
    attachments: list[dict] = []

    # ── 提交 ──────────────────────────────────────────
    task_name: str = ""
    submit_toast: str = ""

    # ── 发送历史 ──────────────────────────────────────
    history_modal_open: bool = False
    history_tasks: list[dict] = []
    history_page: int = 1
    history_per_page: int = 10
    history_search: str = ""
    history_total: int = 0

    is_loaded: bool = False

    # ═══════════════════════════════════════════════════
    #  COMPUTED VARS
    # ═══════════════════════════════════════════════════

    @rx.var
    def char_count(self) -> int:
        return len(self.content)

    @rx.var
    def is_too_long(self) -> bool:
        return len(self.content) > 2000

    @rx.var
    def chunks(self) -> list[str]:
        """超长内容拆分成预览分段"""
        text = self.content
        if len(text) <= 2000:
            return [text] if text else []

        chunks = []
        while len(text) > 2000:
            split_at = text.rfind("\n", 0, 2000)
            if split_at == -1 or split_at < 1000:
                split_at = 2000 - 3
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        if text:
            chunks.append(text)
        return chunks

    @rx.var
    def preview_content(self) -> str:
        """预处理 Discord 特殊语法 → 标准 Markdown，供预览渲染"""
        text = self.content
        if not text:
            return "*（输入消息内容后此处实时预览）*"

        # 1) <@user_id> → **@DisplayName**
        for m in self.member_cache:
            text = text.replace(
                f"<@{m['user_id']}>",
                f"**@{m['display_name']}**"
            )

        # 2) <#channel_id> → **#频道名**
        all_channels = self.channels_text + self.channels_forum
        for c in all_channels:
            text = text.replace(
                f"<#{c['channel_id']}>",
                f"**#{c['channel_name']}**"
            )

        # 3) ||spoiler|| → ~~▮ 剧透文本 ▮~~
        text = re.sub(r'\|\|(.+?)\|\|', r'~~▮ \1 ▮~~', text)

        # 4) <:emoji_name:id> / <a:anim_name:id> → :emoji_name:
        text = re.sub(r'<(a?):(\w+):\d+>', r':\2:', text)

        # 5) <t:timestamp> / <t:timestamp:format> → 本地时间
        def _format_ts(m):
            try:
                ts = int(m.group(1))
                fmt = m.group(2) or ""
                dt = datetime.datetime.utcfromtimestamp(ts)
                if fmt == "D":
                    return dt.strftime("%Y-%m-%d")
                if fmt == "T":
                    return dt.strftime("%H:%M:%S")
                if fmt == "R":
                    delta = datetime.datetime.utcnow() - dt
                    if delta.days >= 1:
                        return f"{delta.days} 天前"
                    if delta.seconds >= 3600:
                        return f"{delta.seconds // 3600} 小时前"
                    if delta.seconds >= 60:
                        return f"{delta.seconds // 60} 分钟前"
                    return "刚刚"
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return m.group(0)

        text = re.sub(r'<t:(\d+):?(\w*)>', _format_ts, text)

        # 6) 单行换行 → Markdown 硬换行（两个空格 + \n），使预览换行与 Discord 一致
        #    代码块内的换行不受影响（代码块本身已原样渲染）
        lines = text.split('\n')
        result_lines = []
        in_code_block = False
        for line in lines:
            if line.startswith('```'):
                in_code_block = not in_code_block
                result_lines.append(line)
            elif in_code_block:
                result_lines.append(line)
            else:
                # 非代码块行：末尾加两个空格触发 Markdown 硬换行
                result_lines.append(line + '  ')
        text = '\n'.join(result_lines)

        return text

    @rx.var
    def today_str(self) -> str:
        return datetime.date.today().isoformat()

    @rx.var
    def history_total_pages(self) -> int:
        if self.history_total == 0:
            return 0
        return (self.history_total + self.history_per_page - 1) // self.history_per_page

    # ═══════════════════════════════════════════════════
    #  LOAD
    # ═══════════════════════════════════════════════════

    async def load(self):
        """初始化：加载 Bot 列表和服务器列表"""
        if self.is_loaded:
            return  # 避免重复加载

        bots = crud.get_active_bots()
        self.bots_list = [{"bot_id": b[0], "bot_name": b[1]} for b in bots] if bots else []
        if self.bots_list:
            self.current_bot_id = self.bots_list[0]["bot_id"]
            await self._load_guilds()
        self.is_loaded = True

    async def _load_guilds(self):
        """加载当前 Bot 的服务器列表"""
        if not self.current_bot_id:
            return
        guilds = crud.get_guilds(self.current_bot_id)
        self.guilds_list = [{"guild_id": g["guild_id"], "guild_name": g["guild_name"]} for g in guilds]

    # ── 选择 Bot ──
    async def on_bot_change(self, bot_id: str):
        self.current_bot_id = bot_id
        self.selected_guild_id = ""
        self.channels_text = []
        self.channels_forum = []
        self.channels_threads = []
        self.member_cache = []
        self.guilds_list = []
        await self._load_guilds()

    # ── 选择服务器 ──
    async def on_guild_change(self, guild_id: str):
        """选择服务器 → 加载频道和成员"""
        self.selected_guild_id = guild_id
        self.selected_channel_id = ""
        self.selected_thread_id = ""
        self.selected_thread_parent_channel = ""
        self.target_type = TARGET_CHANNEL

        if not guild_id or not self.current_bot_id:
            return

        # 加载频道（按类型分组）
        result = crud.get_channels_all_types(self.current_bot_id, guild_id)
        self.channels_text = result["text"]
        self.channels_forum = result["forum"]
        self.channels_threads = result["threads"]
        self.filtered_threads = []

        # 加载成员
        members = crud.get_members(self.current_bot_id, guild_id)
        self.member_cache = members

    # ── 切换目标类型 ──
    def on_target_change(self, target: str):
        self.target_type = target
        self.selected_thread_id = ""
        self.selected_thread_parent_channel = ""
        self.thread_name = ""

    # ── 选中帖子（forum_reply）──
    def on_thread_select(self, thread_id: str):
        self.selected_thread_id = thread_id
        # 查找对应的 parent_channel_id
        for t in self.channels_threads:
            if t["channel_id"] == thread_id:
                self.selected_thread_parent_channel = t.get("parent_channel_id", "")
                break

    # ═══════════════════════════════════════════════════
    #  EVENT HANDLERS (explicit setters for Reflex binding)
    # ═══════════════════════════════════════════════════

    def set_selected_channel(self, value: str):
        self.selected_channel_id = value
        self._update_filtered_threads()
        # 切换频道后清空已选帖子
        self.selected_thread_id = ""
        self.selected_thread_parent_channel = ""

    def _update_filtered_threads(self):
        """根据当前选中的论坛频道过滤帖子列表（回复帖子时只显示该论坛内的帖子）。"""
        if not self.selected_channel_id:
            self.filtered_threads = self.channels_threads
            return
        self.filtered_threads = [
            t for t in self.channels_threads
            if t.get("parent_channel_id") == self.selected_channel_id
        ]

    def set_schedule_type_evt(self, value: str):
        self.schedule_type = value

    def set_thread_name_evt(self, value: str):
        self.thread_name = value

    def set_scheduled_date_evt(self, value: str):
        self.scheduled_date = value

    def set_scheduled_time_evt(self, value: str):
        self.scheduled_time = value

    def set_task_name_evt(self, value: str):
        self.task_name = value

    _mention_re = re.compile(r'(?:^|\s)(@)(\S*)$')
    _channel_re = re.compile(r'(?:^|\s)(#)(\S*)$')

    def set_content_evt(self, value: str):
        self.content = value
        self._detect_mention_trigger(value)

    def _detect_mention_trigger(self, text: str):
        """检测内容末尾是否输入了 @xxx 或 #xxx 触发模式"""
        m = self._mention_re.search(text)
        if m:
            self.mention_mode = "member"
            self.mention_search = m.group(2)
            self.mention_panel_open = True
            self._do_mention_search()
            return

        m = self._channel_re.search(text)
        if m:
            self.mention_mode = "channel"
            self.mention_search = m.group(2)
            self.mention_panel_open = True
            self._do_channel_search()
            return

        # 没有匹配的触发模式 → 关闭面板
        if self.mention_panel_open:
            self._close_mention()

    def _do_mention_search(self):
        q = self.mention_search.lower()
        self.mention_results = [
            m for m in self.member_cache
            if q in m["display_name"].lower()
        ][:20]

    def _do_channel_search(self):
        q = self.mention_search.lower()
        all_ch = self.channels_text + self.channels_forum
        self.channel_search_hits = [
            c for c in all_ch
            if q in c["channel_name"].lower()
        ][:20]

    def _close_mention(self):
        self.mention_panel_open = False
        self.mention_search = ""
        self.mention_results = []
        self.channel_search_hits = []

    # ═══════════════════════════════════════════════════
    #  FORMATTING HELPERS
    #  注：格式化实际操作交给前端 JS（通过 rx.call_script），
    #  这样能正确获取 textarea 中的选区和光标位置。
    #  下方方法仅作为 JS 不可用时的退化回退。
    # ═══════════════════════════════════════════════════

    def fmt_bold(self):
        self.content += "**粗体**"

    def fmt_italic(self):
        self.content += "*斜体*"

    def fmt_strike(self):
        self.content += "~~删除~~"

    def fmt_code(self):
        self.content += "`代码`"

    def fmt_quote(self):
        self.content += "> 引用\n"

    def fmt_spoiler(self):
        self.content += "||剧透||"

    # ═══════════════════════════════════════════════════
    #  @MENTION
    # ═══════════════════════════════════════════════════

    def on_mention_search_change(self, value: str):
        """@提及搜索输入变化（手动在搜索框输入时触发）"""
        self.mention_search = value
        if not value:
            self.mention_results = []
            self.channel_search_hits = []
            return

        if self.mention_mode == "member":
            self._do_mention_search()
        elif self.mention_mode == "channel":
            self._do_channel_search()

    def set_mention_mode(self, mode: str):
        """切换 / 关闭提及面板"""
        if mode:
            self.mention_mode = mode
            self.mention_search = ""
            self.mention_results = []
            self.channel_search_hits = []
            self.mention_panel_open = True
        else:
            self.mention_mode = ""
            self._close_mention()

    def on_dialog_open_change(self, open: bool):
        """弹窗开关变化：关闭时收起提及面板"""
        if not open:
            self.mention_mode = ""
            self._close_mention()

    def insert_mention(self, mention_str: str):
        """将 <@id> 或 <#id> 替换掉内容末尾的 @xxx / #xxx 触发器。

        注意：不依赖 mention_search（搜索框的词），因为通过搜索框搜索时搜索词
        与 content 末尾的触发符可能不一致，会导致替换失败、弹窗消失而无插入。
        直接匹配 content 末尾的 @名字/#名字（与 _detect_mention_trigger 一致），
        将最后的触发符整体替换为 mention_str，并保留前面的空格。"""
        if self.mention_mode == "member":
            self.content = re.sub(
                r'(\s?)@\S*$', rf'\1{mention_str}', self.content)
        else:
            self.content = re.sub(
                r'(\s?)#\S*$', rf'\1{mention_str}', self.content)
        self._close_mention()

    def insert_mention_user(self, user_id: str):
        """插入成员提及：事件系统传入纯字符串 user_id，内部拼接 <@id>，
        避免在 rx.foreach 闭包里用 f-string 拼接 Var 导致的 [object Object] 问题。"""
        self.insert_mention(f"<@{user_id}>")

    def insert_mention_channel(self, channel_id: str):
        """插入频道引用：同上，拼接 <#id>"""
        self.insert_mention(f"<#{channel_id}>")

    # ═══════════════════════════════════════════════════
    #  ATTACHMENTS
    # ═══════════════════════════════════════════════════

    async def handle_upload(self, files: list[rx.UploadFile]):
        """处理文件上传"""
        for file in files:
            try:
                data = await file.read()
                self.attachments.append({
                    "filename": file.filename or "unknown",
                    "data_b64": base64.b64encode(data).decode("utf-8"),
                    "content_type": getattr(file, "content_type", "") or "",
                    "size": len(data),
                })
            except Exception as e:
                print(f"[Broadcast] 上传失败: {e}")

    def remove_attachment(self, idx: int):
        """移除指定附件"""
        if 0 <= idx < len(self.attachments):
            self.attachments.pop(idx)

    # ═══════════════════════════════════════════════════
    #  SUBMIT
    # ═══════════════════════════════════════════════════

    async def submit(self):
        """提交广播任务"""
        if not self._validate():
            return

        # 确定实际 channel_id / thread_id
        channel_id = self.selected_channel_id
        thread_id = ""
        if self.target_type == TARGET_FORUM_NEW:
            pass  # channel_id = forum id, thread_name = self.thread_name
        elif self.target_type == TARGET_FORUM_REPLY:
            thread_id = self.selected_thread_id
            # 用帖子的 parent forum 作为 channel_id
            channel_id = self.selected_thread_parent_channel or channel_id

        # 解析定时（用户输入的是本地时间 → 转 UTC 储存）
        scheduled_at = None
        if self.schedule_type == SCHEDULE_TIMED and self.scheduled_date:
            try:
                dt_str = f"{self.scheduled_date} {self.scheduled_time or '00:00'}"
                local_dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                # 转为 UTC naive datetime，与 get_pending_tasks 中的 utcnow() 对齐
                local_tz = datetime.datetime.now().astimezone().tzinfo
                local_aware = local_dt.replace(tzinfo=local_tz)
                scheduled_at = local_aware.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            except ValueError:
                self.submit_toast = "日期格式错误"
                return

        task_id = crud.create_message_task(
            bot_id=self.current_bot_id,
            guild_id=self.selected_guild_id,
            channel_id=channel_id,
            target_type=self.target_type,
            content=self.content,
            task_name=self.task_name or f"广播 {datetime.datetime.now().strftime('%m-%d %H:%M')}",
            thread_id=thread_id,
            thread_name=self.thread_name if self.target_type == TARGET_FORUM_NEW else "",
            schedule_type=self.schedule_type,
            scheduled_at=scheduled_at,
            status=STATUS_PENDING,
        )

        if not task_id:
            self.submit_toast = "提交失败，请重试"
            return

        # 保存附件
        for att in self.attachments:
            data = base64.b64decode(att["data_b64"])
            crud.add_attachment(
                task_id=task_id,
                filename=att["filename"],
                file_data=data,
                content_type=att["content_type"],
                file_size=att["size"],
            )

        # 清空表单
        self.content = ""
        self.attachments = []
        self.task_name = ""
        self.submit_toast = "广播任务已提交"

    async def save_draft(self):
        """存为草稿"""
        if not self.content.strip():
            self.submit_toast = "内容不能为空"
            return

        task_id = crud.create_message_task(
            bot_id=self.current_bot_id,
            guild_id=self.selected_guild_id,
            channel_id=self.selected_channel_id,
            target_type=self.target_type,
            content=self.content,
            task_name=self.task_name or "草稿",
            status=STATUS_DRAFT,
        )
        if task_id:
            self.submit_toast = "已保存为草稿"
            self.content = ""
            self.task_name = ""
        else:
            self.submit_toast = "保存失败"

    def _validate(self) -> bool:
        if not self.current_bot_id:
            self.submit_toast = "请先选择机器人"
            return False
        if not self.selected_guild_id:
            self.submit_toast = "请选择服务器"
            return False
        if not self.selected_channel_id:
            self.submit_toast = "请选择目标频道"
            return False
        if self.target_type == TARGET_FORUM_REPLY and not self.selected_thread_id:
            self.submit_toast = "请选择要回复的帖子"
            return False
        if not self.content.strip():
            self.submit_toast = "消息内容不能为空"
            return False
        if self.schedule_type == SCHEDULE_TIMED and not self.scheduled_date:
            self.submit_toast = "定时发送需要指定日期"
            return False
        return True

    # ═══════════════════════════════════════════════════
    #  HISTORY
    # ═══════════════════════════════════════════════════

    def open_history(self):
        self.history_modal_open = True
        self.history_page = 1
        self.history_search = ""
        self._load_history()

    def close_history(self):
        self.history_modal_open = False

    def on_history_dialog_change(self, open: bool):
        """响应 rx.dialog.root 的 on_open_change 事件"""
        self.history_modal_open = open

    def _load_history(self):
        bot_id = self.current_bot_id or crud.DEFAULT_BOT_ID
        guild_id = self.selected_guild_id or None
        tasks, total = crud.get_task_history_paginated(
            bot_id=bot_id,
            guild_id=guild_id,
            search=self.history_search,
            page=self.history_page,
            per_page=self.history_per_page,
        )
        self.history_tasks = tasks
        self.history_total = total

    def go_history_page(self, page: int):
        self.history_page = page
        self._load_history()

    def set_history_per_page(self, per_page: str):
        self.history_per_page = int(per_page)
        self.history_page = 1
        self._load_history()

    def set_history_search(self, value: str):
        self.history_search = value
        self.history_page = 1
        self._load_history()
