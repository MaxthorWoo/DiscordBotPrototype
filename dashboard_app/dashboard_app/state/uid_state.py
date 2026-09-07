"""UID 采集进程后台状态（多进程管理）"""
import asyncio
import datetime
from typing import Optional
import reflex as rx
from shared_lib import crud
from pydantic import BaseModel
from .bot_state import BotState


class UIDCampaignItem(BaseModel):
    id: int = 0
    name: str = ""
    status: str = ""
    guild_id: str = ""
    channel_id: str = ""
    uid_length: int = 8
    valid_reaction: str = "✅"
    duplicate_reaction: str = "❌"
    msg_overlap: str = ""
    msg_multiple: str = ""
    msg_length: str = ""
    started_at: str = ""
    end_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    stats: dict = {}
    # 频道/服务器名（供展示）
    guild_name: str = ""
    channel_name: str = ""


class UIDStats(BaseModel):
    total: int = 0
    valid: int = 0
    duplicate: int = 0
    invalid: int = 0
    unique_uids: int = 0


class UIDRecordItem(BaseModel):
    id: int = 0
    campaign_id: Optional[int] = None
    user_name: Optional[str] = ""
    uid: Optional[str] = ""
    answer: Optional[str] = ""
    status: Optional[str] = ""
    invalid_reason: Optional[str] = ""
    raw_content: Optional[str] = ""
    mentioned_users: Optional[str] = "[]"
    created_at: Optional[str] = ""


class GuildOption(BaseModel):
    guild_id: str = ""
    guild_name: str = ""


class ScanTaskItem(BaseModel):
    id: int = 0
    status: str = ""
    error: str = ""
    created_at: str = ""
    processed_at: str = ""
    # 扫描结果展开字段（从 result dict 提取）
    scanned_new: int = 0
    scanned_dup: int = 0
    out_of_window: int = 0


class UIDState(BotState):
    # ===== 列表页 =====
    campaigns: list[UIDCampaignItem] = []
    loading: bool = False

    # ===== 新建/编辑表单 =====
    form_id: int = 0                    # 0 = 新建，>0 = 编辑
    form_name: str = ""
    form_guild_id: str = ""
    form_channel_id: str = ""
    form_length: str = "8"
    form_valid_reaction: str = "✅"
    form_duplicate_reaction: str = "❌"
    form_msg_overlap: str = ""
    form_msg_multiple: str = ""
    form_msg_length: str = ""
    form_start_date: str = ""
    form_start_time: str = ""
    form_end_date: str = ""
    form_end_time: str = ""

    # ===== 服务器/频道选项 =====
    guilds: list[GuildOption] = []
    channels: list[dict] = []

    # ===== 详情页 =====
    current_campaign: UIDCampaignItem = UIDCampaignItem()
    stats: UIDStats = UIDStats()
    records: list[UIDRecordItem] = []
    uid_list: list[str] = []
    filter_status: str = "all"
    filter_start: str = ""
    filter_end: str = ""

    # ===== 手动扫描 =====
    scan_tasks: list[ScanTaskItem] = []  # 扫描任务历史
    scan_processing: bool = False        # 是否已有正在执行的扫描
    scan_show_result: bool = False       # 是否展示扫描结果弹窗
    scan_result: dict = {}               # 最近一次扫描结果
    scan_result_title: str = ""

    toast: str = ""
    error: str = ""

    def _bot_id(self) -> str:
        return self.current_bot_id

    # ===== 通用 =====
    async def _flash_auto(self, message: str, is_error: bool = False):
        if is_error:
            self.error = message
        else:
            self.toast = message
        await asyncio.sleep(2)
        if is_error:
            self.error = ""
        else:
            self.toast = ""

    # ===== 列表页 =====
    async def load_campaigns(self):
        self.loading = True
        bot_id = self._bot_id()
        raw = crud.uid_get_campaigns(bot_id)
        # 补服务器/频道名
        guild_map = {}
        for g in crud.get_guilds_monitor(bot_id):
            guild_map[g["guild_id"]] = g["guild_name"] or ""
        ch_map = {}
        for g in crud.get_channels_by_guild(bot_id):
            for c in g["channels"]:
                ch_map[c["channel_id"]] = c["channel_name"]
        items = []
        for c in raw:
            c["guild_name"] = guild_map.get(c["guild_id"], c["guild_id"])
            c["channel_name"] = ch_map.get(c["channel_id"], c["channel_id"])
            items.append(UIDCampaignItem(**c))
        self.campaigns = items
        self.loading = False

    async def load_guilds(self):
        bot_id = self._bot_id()
        self.guilds = [
            GuildOption(guild_id=g["guild_id"], guild_name=g["guild_name"] or "未知服务器")
            for g in crud.get_guilds_monitor(bot_id)
        ]

    async def on_guild_change(self, guild_id: str):
        self.form_guild_id = guild_id
        self.form_channel_id = ""
        self.channels = []
        bot_id = self._bot_id()
        for g in crud.get_channels_by_guild(bot_id):
            if g["guild_id"] == guild_id:
                self.channels = g["channels"]
                break

    async def on_channel_change(self, channel_id: str):
        self.form_channel_id = channel_id

    # ===== 表单字段 =====
    def on_name_change(self, v: str): self.form_name = v
    def on_length_change(self, v: str): self.form_length = v
    def on_valid_reaction_change(self, v: str): self.form_valid_reaction = v
    def on_duplicate_reaction_change(self, v: str): self.form_duplicate_reaction = v
    def on_msg_overlap_change(self, v: str): self.form_msg_overlap = v
    def on_msg_multiple_change(self, v: str): self.form_msg_multiple = v
    def on_msg_length_change(self, v: str): self.form_msg_length = v
    def on_start_date_change(self, v: str): self.form_start_date = v
    def on_start_time_change(self, v: str): self.form_start_time = v
    def on_end_date_change(self, v: str): self.form_end_date = v
    def on_end_time_change(self, v: str): self.form_end_time = v

    # ===== 新建 =====
    async def start_new(self):
        """进入新建模式"""
        self.form_id = 0
        self.form_name = ""
        self.form_guild_id = ""
        self.form_channel_id = ""
        self.form_length = "8"
        self.form_valid_reaction = "✅"
        self.form_duplicate_reaction = "❌"
        # 新建时预填默认质询模板（中英双语）
        self.form_msg_overlap = crud._DEFAULT_MSG_OVERLAP
        self.form_msg_multiple = crud._DEFAULT_MSG_MULTIPLE
        self.form_msg_length = crud._DEFAULT_MSG_LENGTH
        self.form_start_date = ""
        self.form_start_time = ""
        self.form_end_date = ""
        self.form_end_time = ""
        self.error = ""
        await self.load_guilds()

    # ===== 编辑：加载进程到表单 =====
    async def load_campaign_for_edit(self):
        campaign_id = self.router._page.params.get("campaign_id", "")
        if campaign_id is None or str(campaign_id) == "":
            self.error = "缺少进程 ID"
            return
        try:
            campaign_id = int(campaign_id)
        except (TypeError, ValueError):
            self.error = "进程 ID 无效"
            return
        bot_id = self._bot_id()
        c = crud.uid_get_campaign(bot_id, campaign_id)
        if not c:
            self.error = "进程不存在"
            return
        self.form_id = campaign_id
        self.form_name = c["name"]
        self.form_guild_id = c["guild_id"]
        self.form_channel_id = c["channel_id"]
        self.form_length = str(c["uid_length"])
        self.form_valid_reaction = c["valid_reaction"]
        self.form_duplicate_reaction = c["duplicate_reaction"]
        self.form_msg_overlap = c["msg_overlap"]
        self.form_msg_multiple = c["msg_multiple"]
        self.form_msg_length = c["msg_length"]
        self._split_dt(c["started_at"], "start")
        self._split_dt(c["end_at"], "end")
        await self.load_guilds()
        # 加载当前服务器频道
        self.channels = []
        for g in crud.get_channels_by_guild(bot_id):
            if g["guild_id"] == c["guild_id"]:
                self.channels = g["channels"]
                break

    def _split_dt(self, bj_str: str, kind: str):
        """把北京时间字符串拆成日期+时间"""
        date, time = "", ""
        if bj_str:
            parts = bj_str.split(" ")
            date = parts[0] if parts else ""
            time = parts[1][:5] if len(parts) > 1 else ""
        if kind == "start":
            self.form_start_date, self.form_start_time = date, time
        else:
            self.form_end_date, self.form_end_time = date, time

    def _combine_dt(self, date: str, time: str):
        """把日期+时间（北京时间）转成 UTC naive datetime，可空则返回 None"""
        if not date:
            return None
        t = time or "00:00"
        try:
            hh, mm = t.split(":")[:2]
            bj = datetime.datetime.strptime(f"{date} {int(hh)}:{int(mm)}", "%Y-%m-%d %H:%M")
            # 北京时间 → UTC
            utc = bj - datetime.timedelta(hours=8)
            return utc
        except (ValueError, IndexError):
            return None

    # ===== 保存 =====
    async def save_campaign(self):
        bot_id = self._bot_id()
        # 校验失败时，短暂提示后自动清除并中止
        if not self.form_guild_id:
            self.toast = "请选择服务器"
            yield
            await asyncio.sleep(2)
            self.toast = ""
            return
        if not self.form_channel_id:
            self.toast = "请选择频道"
            yield
            await asyncio.sleep(2)
            self.toast = ""
            return
        if not self.form_name.strip():
            self.toast = "请输入进程名称"
            yield
            await asyncio.sleep(2)
            self.toast = ""
            return
        try:
            length = int(self.form_length or 8)
        except (TypeError, ValueError):
            length = 8
        started = self._combine_dt(self.form_start_date, self.form_start_time)
        ended = self._combine_dt(self.form_end_date, self.form_end_time)
        if ended and started and ended <= started:
            self.toast = "结束时间必须晚于开始时间"
            yield
            await asyncio.sleep(2)
            self.toast = ""
            return

        if self.form_id == 0:
            cid = crud.uid_create_campaign(
                bot_id, self.form_name, self.form_guild_id, self.form_channel_id,
                uid_length=length,
                valid_reaction=self.form_valid_reaction or "✅",
                duplicate_reaction=self.form_duplicate_reaction or "❌",
                msg_overlap=self.form_msg_overlap or None,
                msg_multiple=self.form_msg_multiple or None,
                msg_length=self.form_msg_length or None,
                started_at=started, end_at=ended,
            )
            if cid == -1:
                self.toast = "该频道已被其他进程占用，无法创建"
                yield
                await asyncio.sleep(2)
                self.toast = ""
                return
            self.toast = "✅ 进程已创建并开始运行"
        else:
            ok = crud.uid_update_campaign(bot_id, self.form_id, {
                "name": self.form_name,
                "guild_id": self.form_guild_id,
                "channel_id": self.form_channel_id,
                "uid_length": length,
                "valid_reaction": self.form_valid_reaction or "✅",
                "duplicate_reaction": self.form_duplicate_reaction or "❌",
                "msg_overlap": self.form_msg_overlap or None,
                "msg_multiple": self.form_msg_multiple or None,
                "msg_length": self.form_msg_length or None,
                "started_at": started, "end_at": ended,
            })
            if not ok:
                self.toast = "更新失败（频道可能已被其他进程占用）"
                yield
                await asyncio.sleep(2)
                self.toast = ""
                return
            self.toast = "✅ 进程已更新"
        yield
        await asyncio.sleep(2)
        self.toast = ""
        return

    # ===== 进程操作 =====
    async def set_status(self, campaign_id: int, status: str):
        bot_id = self._bot_id()
        ok, msg = crud.uid_set_campaign_status(bot_id, campaign_id, status)
        if ok:
            self.toast = msg
        else:
            self.error = msg
            yield
            await asyncio.sleep(2)
            self.error = ""
            return
        await self.load_campaigns()
        yield
        await asyncio.sleep(2)
        self.toast = ""

    async def delete_campaign(self, campaign_id: int):
        bot_id = self._bot_id()
        crud.uid_delete_campaign(bot_id, campaign_id)
        self.toast = "已删除进程"
        await self.load_campaigns()
        yield
        await asyncio.sleep(2)
        self.toast = ""

    # ===== 详情页 =====
    async def load_campaign_detail(self):
        # campaign_id 是动态路由参数，从 router._page.params 读取（不依赖注入时机的动态 var）
        campaign_id = self.router._page.params.get("campaign_id", "")
        if campaign_id is None or str(campaign_id) == "":
            self.error = "缺少进程 ID"
            return
        try:
            campaign_id = int(campaign_id)
        except (TypeError, ValueError):
            self.error = "进程 ID 无效"
            return
        bot_id = self._bot_id()
        c = crud.uid_get_campaign(bot_id, campaign_id)
        if not c:
            self.error = "进程不存在"
            return
        # 补名称
        for g in crud.get_guilds_monitor(bot_id):
            if g["guild_id"] == c["guild_id"]:
                c["guild_name"] = g["guild_name"] or ""
                break
        for g in crud.get_channels_by_guild(bot_id):
            for ch in g["channels"]:
                if ch["channel_id"] == c["channel_id"]:
                    c["channel_name"] = ch["channel_name"]
                    break
        self.current_campaign = UIDCampaignItem(**c)
        self._load_report(bot_id, campaign_id)
        self.load_scan_tasks(bot_id, campaign_id)

    def _load_report(self, bot_id: str, campaign_id: int):
        status = None if self.filter_status == "all" else self.filter_status
        start = self.filter_start or None
        end = self.filter_end or None
        self.stats = UIDStats(**crud.uid_get_statistics(bot_id, campaign_id, start=start, end=end))
        raw = crud.uid_get_records(bot_id, campaign_id, start=start, end=end, status=status)
        self.records = [UIDRecordItem(**r) for r in raw]
        self.uid_list = crud.uid_get_uid_list(bot_id, campaign_id, start=start, end=end)

    async def load_report(self):
        bot_id = self._bot_id()
        cid = self.current_campaign.id
        self._load_report(bot_id, cid)

    # ===== 手动扫描（查漏补缺） =====
    def load_scan_tasks(self, bot_id: str = None, campaign_id: int = None):
        """加载某进程的扫描任务历史。"""
        bot_id = bot_id or self._bot_id()
        campaign_id = campaign_id or (self.current_campaign.id if self.current_campaign else 0)
        if not campaign_id:
            return
        raw = crud.uid_get_scan_tasks(bot_id, campaign_id, limit=10)
        items = []
        for t in raw:
            res = t.get("result") or {}
            items.append(ScanTaskItem(
                id=t.get("id", 0),
                status=t.get("status", ""),
                error=t.get("error", ""),
                created_at=t.get("created_at", ""),
                processed_at=t.get("processed_at", ""),
                scanned_new=res.get("scanned_new", 0),
                scanned_dup=res.get("scanned_dup", 0),
                out_of_window=res.get("out_of_window", 0),
            ))
        self.scan_tasks = items

    async def manual_scan(self):
        """触发一次手动扫描（后台写入任务，bot 轮询执行）。"""
        bot_id = self._bot_id()
        cid = self.current_campaign.id
        if not cid:
            self.error = "进程不存在"
            yield
            await asyncio.sleep(2)
            self.error = ""
            return
        # 检查是否已有未完成的扫描任务
        pending = [t for t in self.scan_tasks if t["status"] in ("pending", "processing")]
        if pending:
            self.error = "已有扫描任务进行中，请稍后再试"
            yield
            await asyncio.sleep(2)
            self.error = ""
            return
        task_id = crud.uid_create_scan_task(bot_id, cid)
        if task_id == -1:
            self.error = "已有待执行的扫描任务，请等待完成"
            yield
            await asyncio.sleep(2)
            self.error = ""
            return
        self.toast = "已提交手动扫描，bot 将在数秒内执行，完成后可查看结果"
        self.load_scan_tasks(bot_id, cid)
        yield
        await asyncio.sleep(2)
        self.toast = ""

    async def refresh_scan_result(self):
        """刷新扫描任务状态，若刚完成的扫描展示结果。"""
        bot_id = self._bot_id()
        cid = self.current_campaign.id
        self.load_scan_tasks(bot_id, cid)
        if self.scan_tasks:
            latest = self.scan_tasks[0]
            if latest["status"] == "done" and latest["result"]:
                self.scan_result = latest["result"]
                self.scan_result_title = f"扫描完成（{latest['processed_at']}）"
                self.scan_show_result = True
            elif latest["status"] == "failed":
                self.scan_result = {"error": latest["error"]}
                self.scan_result_title = "扫描失败"
                self.scan_show_result = True

    def close_scan_result(self):
        self.scan_show_result = False

    def on_filter_status_change(self, v: str): self.filter_status = v
    def on_filter_start_change(self, v: str): self.filter_start = v
    def on_filter_end_change(self, v: str): self.filter_end = v

    def copy_uid_list(self) -> str:
        return "\n".join(self.uid_list)

    def clear_toast(self):
        self.toast = ""
        self.error = ""
