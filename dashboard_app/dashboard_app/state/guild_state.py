import reflex as rx
from shared_lib import crud
from pydantic import BaseModel
from .bot_state import BotState


class BotStatus(BaseModel):
    bot_id: str = ""
    bot_name: str = ""
    configured: bool = False
    active: bool = False
    online: bool = False
    latency_ms: int | None = None
    last_seen: str = ""
    seconds_since: int | None = None
    uptime_hours: int = 0
    guild_count: int = 0


class GuildMonitor(BaseModel):
    guild_id: str = ""
    guild_name: str = ""
    icon_url: str = ""
    guild_url: str = ""
    member_count: int = 0
    channel_count: int = 0
    kick_count: int = 0
    config_count: int = 0
    joined_at: str = ""


class MonitorSummary(BaseModel):
    guilds: int = 0
    channels: int = 0
    members: int = 0
    total_kicks: int = 0
    pending_tasks: int = 0
    sent_tasks: int = 0
    failed_tasks: int = 0


class DetailChannel(BaseModel):
    channel_id: str = ""
    channel_name: str = ""
    channel_type: str = ""


class GuildChannels(BaseModel):
    guild_id: str = ""
    guild_name: str = ""
    channel_count: int = 0
    channels: list[DetailChannel] = []


class DetailMember(BaseModel):
    user_id: str = ""
    display_name: str = ""


class GuildMembers(BaseModel):
    guild_id: str = ""
    guild_name: str = ""
    member_count: int = 0
    members: list[DetailMember] = []


class DetailKick(BaseModel):
    user_name: str = ""
    guild_name: str = ""
    channel_name: str = ""
    kicked_at: str = ""
    reason: str = ""


class DetailTask(BaseModel):
    task_id: int = 0
    task_name: str = ""
    guild_name: str = ""
    status: str = ""
    schedule_type: str = ""
    scheduled_at: str = ""
    result_msg: str = ""
    created_at: str = ""


class GuildState(rx.State):
    bot_status: BotStatus = BotStatus()
    guilds: list[GuildMonitor] = []
    summary: MonitorSummary = MonitorSummary()
    loading: bool = False

    # ===== 弹窗明细 =====
    active_modal: str = ""                     # 当前打开的弹窗类型
    detail_channels: list[GuildChannels] = []
    detail_members: list[GuildMembers] = []
    detail_kicks: list[DetailKick] = []
    detail_tasks: list[DetailTask] = []

    async def load_guilds(self):
        """加载监控页数据：机器人状态 + 服务器总览 + 业务汇总"""
        self.loading = True
        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id

        status_raw = crud.get_bot_status(bot_id)
        self.bot_status = BotStatus(
            bot_id=status_raw.get("bot_id", bot_id),
            bot_name=status_raw.get("bot_name", "未命名"),
            configured=status_raw.get("configured", False),
            active=status_raw.get("active", False),
            online=status_raw.get("online", False),
            latency_ms=status_raw.get("latency_ms"),
            last_seen=status_raw.get("last_seen") or "",
            seconds_since=status_raw.get("seconds_since"),
            uptime_hours=status_raw.get("uptime_hours", 0),
            guild_count=status_raw.get("guild_count", 0),
        )

        summary_raw = crud.get_monitor_summary(bot_id)
        self.summary = MonitorSummary(
            guilds=summary_raw.get("guilds", 0),
            channels=summary_raw.get("channels", 0),
            members=summary_raw.get("members", 0),
            total_kicks=summary_raw.get("total_kicks", 0),
            pending_tasks=summary_raw.get("pending_tasks", 0),
            sent_tasks=summary_raw.get("sent_tasks", 0),
            failed_tasks=summary_raw.get("failed_tasks", 0),
        )

        guild_raw = crud.get_guilds_monitor(bot_id)
        self.guilds = [
            GuildMonitor(
                guild_id=g["guild_id"],
                guild_name=g["guild_name"] or "未知服务器",
                icon_url=g.get("icon_url") or "",
                guild_url=g.get("guild_url") or "",
                member_count=g["member_count"],
                channel_count=g["channel_count"],
                kick_count=g["kick_count"],
                config_count=g["config_count"],
                joined_at=g["joined_at"] or "",
            )
            for g in guild_raw
        ]
        self.loading = False

    # ===== 弹窗控制 =====
    def close_modal(self):
        self.active_modal = ""

    def on_modal_change(self, open: bool):
        if not open:
            self.active_modal = ""

    async def open_detail(self, modal_type: str):
        """打开明细弹窗并按类型加载数据"""
        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id
        self.active_modal = modal_type

        if modal_type == "channels":
            raw = crud.get_channels_by_guild(bot_id)
            self.detail_channels = [
                GuildChannels(
                    guild_id=g["guild_id"],
                    guild_name=g["guild_name"],
                    channel_count=g["channel_count"],
                    channels=[
                        DetailChannel(**c) for c in g["channels"]
                    ],
                )
                for g in raw
            ]
        elif modal_type == "members":
            raw = crud.get_members_by_guild(bot_id)
            self.detail_members = [
                GuildMembers(
                    guild_id=g["guild_id"],
                    guild_name=g["guild_name"],
                    member_count=g["member_count"],
                    members=[DetailMember(**m) for m in g["members"]],
                )
                for g in raw
            ]
        elif modal_type == "kicks":
            raw = crud.get_kick_logs_global(bot_id)
            self.detail_kicks = [DetailKick(**k) for k in raw]
        elif modal_type in ("pending", "sent", "failed"):
            raw = crud.get_message_tasks_by_status(bot_id, modal_type)
            self.detail_tasks = [DetailTask(**t) for t in raw]
