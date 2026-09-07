from .models import SessionLocal, Bot, GuildConfig, SystemEvent, Guild, ChannelCache, TrapConfig, TrapLog
from .models import GiftCodeBatch, GiftCode, GiftClaimLog
from .models import BotMessage, DEFAULT_BOT_MESSAGES, BOT_MESSAGE_META
from .models import MessageTask, MessageAttachment, MemberCache
from .models import TARGET_CHANNEL, TARGET_FORUM_NEW, TARGET_FORUM_REPLY
from .models import SCHEDULE_IMMEDIATE, SCHEDULE_TIMED, STATUS_PENDING, STATUS_PROCESSING, STATUS_SENT, STATUS_FAILED, STATUS_DRAFT
from .models import Raffle, RaffleParticipant
from .models import InstantLottery, LotteryPrize, LotteryDrawRecord, LotteryPoolSlot
from .models import UIDRecord, UID_STATUS_VALID, UID_STATUS_DUPLICATE, UID_STATUS_INVALID
from .models import UID_REASON_OVERLAP, UID_REASON_MULTIPLE, UID_REASON_LENGTH
from .models import UIDCampaign, UID_CAMPAIGN_RUNNING, UID_CAMPAIGN_PAUSED, UID_CAMPAIGN_ENDED
from .models import UIDScanTask, UID_SCAN_TASK_PENDING, UID_SCAN_TASK_PROCESSING, UID_SCAN_TASK_DONE, UID_SCAN_TASK_FAILED
from .utils.time_utils import parse_datetime_to_utc, now_utc, BEIJING_TZ
import datetime
from datetime import timezone as _dt_timezone
import threading
import random
import openpyxl
import io
import base64

# ----- 预留：获取当前使用的 Bot ID（V1写死，未来动态）-----
DEFAULT_BOT_ID = "default_bot"

def get_default_bot_id():
    return DEFAULT_BOT_ID

def migrate_bot_id_to_default():
    """一次性迁移：清除旧 bot_id 的 guild 数据，其余表统一 bot_id。
    下次 bot 重启时 events.py 会用 DEFAULT_BOT_ID 重新同步 guilds。"""
    session = SessionLocal()
    try:
        target = DEFAULT_BOT_ID

        # 步骤 1：删除非默认 bot_id 的 guilds（events 下次重启会重新同步）
        deleted = session.query(Guild).filter(Guild.bot_id != target).delete(
            synchronize_session=False
        )
        # 同时清理对应的 channels / members
        session.query(ChannelCache).filter(ChannelCache.bot_id != target).delete(
            synchronize_session=False
        )
        session.query(MemberCache).filter(MemberCache.bot_id != target).delete(
            synchronize_session=False
        )

        # 步骤 2：message_tasks 保留 → 只更新 bot_id
        session.query(MessageTask).filter(
            MessageTask.bot_id != target
        ).update({"bot_id": target}, synchronize_session=False)

        session.commit()
        print(f"[DB] bot_id 迁移完成 (删除 {deleted} 条旧 guild) → 统一为 '{target}'")
    except Exception as e:
        session.rollback()
        print(f"[DB] 迁移失败: {e}")
    finally:
        session.close()


# ----- 统一时间格式化：数据库存的是 naive UTC，展示统一转北京时间 -----
def _fmt_bj(dt, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """把 naive UTC（或带 UTC 时区）的 datetime 转成北京时间字符串。

    用于所有前端展示的时间字段。若 dt 为 None 返回空字符串。
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        # naive 按 UTC 解释（项目约定数据库存 UTC）
        dt = dt.replace(tzinfo=_dt_timezone.utc)
    return dt.astimezone(BEIJING_TZ).strftime(fmt)


def migrate_lottery_schema():
    """迁移：为 instant_lotteries 添加固定奖池字段 + 创建 lottery_pool_slots 表"""
    from sqlalchemy import text, inspect
    from .models import engine, Base, LotteryPoolSlot
    session = SessionLocal()
    try:
        inspector = inspect(engine)
        cols = [c["name"] for c in inspector.get_columns("instant_lotteries")]

        if "total_slots" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE instant_lotteries ADD COLUMN total_slots INTEGER DEFAULT 100"))
                conn.execute(text("ALTER TABLE instant_lotteries ADD COLUMN slots_drawn INTEGER DEFAULT 0"))
                conn.execute(text("ALTER TABLE instant_lotteries ADD COLUMN max_draws_per_user INTEGER DEFAULT 3"))
                conn.commit()
            print("[DB] instant_lotteries 列迁移完成")

        # 新表
        LotteryPoolSlot.__table__.create(engine, checkfirst=True)
        print("[DB] lottery_pool_slots 表就绪")
    except Exception as e:
        print(f"[DB] migrate_lottery_schema 失败: {e}")
    finally:
        session.close()


def migrate_bot_heartbeat():
    """迁移：为 bots 表添加心跳相关列（last_seen / last_latency_ms）"""
    from sqlalchemy import text, inspect
    from .models import engine
    try:
        inspector = inspect(engine)
        cols = [c["name"] for c in inspector.get_columns("bots")]
        added = []
        if "last_seen" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE bots ADD COLUMN last_seen DATETIME"))
                added.append("last_seen")
        if "last_latency_ms" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE bots ADD COLUMN last_latency_ms INTEGER"))
                added.append("last_latency_ms")
        if "last_error" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE bots ADD COLUMN last_error TEXT"))
                added.append("last_error")
        if added:
            with engine.connect() as conn:
                # 强制 WAL checkpoint，确保多进程（run.py / Reflex）都能立即看到新列，
                # 避免 ALTER 停留在 WAL 中导致其他连接报 no such column
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                conn.commit()
            print(f"[DB] bots 表心跳列迁移完成: {added}")
    except Exception as e:
        print(f"[DB] migrate_bot_heartbeat 失败: {e}")


# 模块导入时即执行一次迁移（确保所有进程：run.py / Reflex 子进程启动时都具备最新表结构）
try:
    migrate_bot_heartbeat()
except Exception:
    pass


# ----- Bot 相关 -----
def init_default_bot():
    """启动时调用，确保默认机器人存在（token 留空等待用户配置）"""
    session = SessionLocal()
    try:
        if not session.query(Bot).filter_by(bot_id=DEFAULT_BOT_ID).first():
            default_bot = Bot(
                bot_id=DEFAULT_BOT_ID, 
                bot_name="未配置",
                token_encrypted="",
                is_active=False,
            )
            session.add(default_bot)
            session.commit()
            print(f"[DB] 初始化默认机器人: {DEFAULT_BOT_ID}")
    finally:
        session.close()


def generate_bot_id() -> str:
    """生成一个唯一的 bot_id（形如 bot_xxxx，避免与 default_bot 冲突）"""
    import string
    session = SessionLocal()
    try:
        while True:
            suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            candidate = f"bot_{suffix}"
            if not session.query(Bot).filter_by(bot_id=candidate).first():
                return candidate
    finally:
        session.close()


def create_bot(bot_name: str) -> str | None:
    """新增一个机器人记录（is_active=False，等待用户填 Token 激活）。

    返回新创建的 bot_id；若 bot_name 已存在则复用已有记录并返回其 bot_id。
    """
    name = (bot_name or "").strip() or "未命名机器人"
    session = SessionLocal()
    try:
        existing = session.query(Bot).filter_by(bot_name=name).first()
        if existing:
            return existing.bot_id
        bot_id = generate_bot_id()
        bot = Bot(
            bot_id=bot_id,
            bot_name=name,
            token_encrypted="",
            is_active=False,
        )
        session.add(bot)
        session.commit()
        print(f"[DB] 新增机器人: {bot_id} ({name})")
        return bot_id
    except Exception as e:
        session.rollback()
        print(f"[DB] create_bot 失败: {e}")
        return None
    finally:
        session.close()


def get_bot(bot_id: str = None) -> dict | None:
    """获取单个 Bot 信息（不返回 token 明文）"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        bot = session.query(Bot).filter_by(bot_id=bot_id).first()
        if bot:
            return {
                "bot_id": bot.bot_id,
                "bot_name": bot.bot_name,
                "has_token": bool(bot.token_encrypted and bot.token_encrypted.strip()),
                "is_active": bot.is_active,
                "created_at": bot.created_at,
            }
        return None
    finally:
        session.close()


def update_bot(bot_id: str, bot_name: str, token: str) -> bool:
    """更新 Bot 名称和 Token，保存后自动激活"""
    session = SessionLocal()
    try:
        bot = session.query(Bot).filter_by(bot_id=bot_id).first()
        if not bot:
            return False
        if bot_name.strip():
            bot.bot_name = bot_name.strip()
        if token.strip():
            bot.token_encrypted = token.strip()
            bot.is_active = True  # 有 token 就激活
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] update_bot 失败: {e}")
        return False
    finally:
        session.close()


def set_bot_active(bot_id: str, active: bool) -> bool:
    """设置机器人启停状态。

    active=True  -> 标记在线，run.py 热加载会自动拉起进程；
    active=False -> 标记停止，run.py 会终止对应进程。
    未配置 Token 时不允许启动（返回 False）。
    """
    session = SessionLocal()
    try:
        bot = session.query(Bot).filter_by(bot_id=bot_id).first()
        if not bot:
            return False
        if active and not (bot.token_encrypted and bot.token_encrypted.strip()):
            return False  # 没有 Token 无法启动
        bot.is_active = active
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] set_bot_active 失败: {e}")
        return False
    finally:
        session.close()


def set_bot_error(bot_id: str, error: str = None):
    """记录机器人最近一次启动失败原因（供后台展示）；传入 None 可清除错误"""
    session = SessionLocal()
    try:
        bot = session.query(Bot).filter_by(bot_id=bot_id).first()
        if bot:
            bot.last_error = error
            session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB] set_bot_error 失败: {e}")
    finally:
        session.close()


def get_bot_token(bot_id: str = None) -> str:
    """从数据库读取 Bot Token（供 Bot 进程启动使用）"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        bot = session.query(Bot).filter_by(bot_id=bot_id).first()
        if bot and bot.token_encrypted and bot.token_encrypted.strip():
            return bot.token_encrypted.strip()
        return ""
    finally:
        session.close()


# ----- 机器人在线状态（心跳监控）-----
HEARTBEAT_TIMEOUT_SECONDS = 90  # 超过该时间未心跳视为离线

def update_bot_heartbeat(bot_id: str = None, latency_ms: int = None):
    """Bot 进程定期调用，更新心跳时间戳与延迟"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        bot = session.query(Bot).filter_by(bot_id=bot_id).first()
        if bot:
            bot.last_seen = datetime.datetime.utcnow()
            if latency_ms is not None:
                bot.last_latency_ms = int(latency_ms)
            session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB] update_bot_heartbeat 失败: {e}")
    finally:
        session.close()


def get_bot_status(bot_id: str = None) -> dict:
    """返回机器人运行状态（是否在线、延迟、上线时长等）"""
    bot_id = bot_id or DEFAULT_BOT_ID
    bot = get_bot(bot_id)
    if not bot:
        return {"bot_id": bot_id, "online": False, "configured": False}
    session = SessionLocal()
    try:
        row = session.query(Bot).filter_by(bot_id=bot_id).first()
        now = datetime.datetime.utcnow()
        last_seen = row.last_seen
        online = False
        seconds_since = None
        if last_seen is not None:
            # SQLite 存的是 naive UTC；统一转 naive 比较，避免时区差异导致误判
            last_seen_naive = last_seen.replace(tzinfo=None) if last_seen.tzinfo else last_seen
            now_naive = now.replace(tzinfo=None)
            seconds_since = int((now_naive - last_seen_naive).total_seconds())
            online = seconds_since <= HEARTBEAT_TIMEOUT_SECONDS

        # last_seen 数据库存的是 naive UTC，展示时统一转北京时间
        def _fmt_last_seen(ts):
            if ts is None:
                return None
            naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
            return naive.replace(tzinfo=_dt_timezone.utc).astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")

        # 首次启动时间（uptime 起点取 created_at）
        uptime_hours = 0
        if row.created_at:
            created_naive = row.created_at.replace(tzinfo=None) if row.created_at.tzinfo else row.created_at
            now_naive = now.replace(tzinfo=None)
            uptime_hours = max(0, int((now_naive - created_naive).total_seconds() // 3600))

        return {
            "bot_id": bot_id,
            "bot_name": bot.get("bot_name", "未命名"),
            "configured": bot.get("has_token", False),
            "active": bot.get("is_active", False),
            "online": online,
            "latency_ms": row.last_latency_ms,
            "last_seen": _fmt_last_seen(last_seen),
            "seconds_since": seconds_since,
            "uptime_hours": uptime_hours,
            "guild_count": session.query(Guild).filter_by(bot_id=bot_id).count(),
            "last_error": row.last_error,
        }
    finally:
        session.close()


def get_guilds_monitor(bot_id: str = None) -> list[dict]:
    """服务器总览：每个服务器的成员数 / 频道数 / 踢人日志数 / 配置项数"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        guilds = session.query(Guild).filter_by(bot_id=bot_id).order_by(Guild.member_count.desc()).all()
        result = []
        for g in guilds:
            channel_count = session.query(ChannelCache).filter_by(
                bot_id=bot_id, guild_id=g.guild_id
            ).count()
            kick_count = session.query(TrapLog).filter_by(
                guild_id=g.guild_id
            ).count()
            config_count = session.query(GuildConfig).filter_by(
                bot_id=bot_id, guild_id=g.guild_id
            ).count()
            result.append({
                "guild_id": g.guild_id,
                "guild_name": g.guild_name,
                "icon_url": g.icon_url or "",
                "guild_url": f"https://discord.com/channels/{g.guild_id}",
                "member_count": g.member_count,
                "channel_count": channel_count,
                "kick_count": kick_count,
                "config_count": config_count,
                "joined_at": _fmt_bj(g.joined_at, "%Y-%m-%d") or None,
            })
        return result
    finally:
        session.close()


def get_monitor_summary(bot_id: str = None) -> dict:
    """监控页顶部汇总：机器人状态 + 全局业务计数"""
    bot_id = bot_id or DEFAULT_BOT_ID
    status = get_bot_status(bot_id)
    session = SessionLocal()
    try:
        summary = {
            "guilds": session.query(Guild).filter_by(bot_id=bot_id).count(),
            "channels": session.query(ChannelCache).filter_by(bot_id=bot_id).count(),
            "members": session.query(MemberCache).filter_by(bot_id=bot_id).count(),
            "total_kicks": session.query(TrapLog).count(),
            "pending_tasks": session.query(MessageTask).filter(
                MessageTask.status == "pending"
            ).count(),
            "sent_tasks": session.query(MessageTask).filter(
                MessageTask.status == "sent"
            ).count(),
            "failed_tasks": session.query(MessageTask).filter(
                MessageTask.status == "failed"
            ).count(),
        }
        summary.update(status)
        return summary
    finally:
        session.close()


# ----- 监控明细（板块弹窗数据）-----
def get_channels_by_guild(bot_id: str = None) -> list[dict]:
    """频道明细：按服务器分组列出所有缓存频道"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        guilds = session.query(Guild).filter_by(bot_id=bot_id).all()
        guild_names = {g.guild_id: g.guild_name or g.guild_id for g in guilds}
        channels = session.query(ChannelCache).filter_by(
            bot_id=bot_id
        ).order_by(ChannelCache.guild_id, ChannelCache.channel_name).all()
        # 按服务器分组
        result = []
        by_guild = {}
        for c in channels:
            gid = c.guild_id
            by_guild.setdefault(gid, []).append({
                "channel_id": c.channel_id or "",
                "channel_name": c.channel_name or "",
                "channel_type": c.channel_type or "",
            })
        for gid, items in by_guild.items():
            result.append({
                "guild_id": gid,
                "guild_name": guild_names.get(gid, gid),
                "channel_count": len(items),
                "channels": items,
            })
        result.sort(key=lambda x: -x["channel_count"])
        return result
    finally:
        session.close()


def get_members_by_guild(bot_id: str = None, limit: int = 500) -> list[dict]:
    """成员明细：按服务器分组列出缓存成员（供监控弹窗展示）"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        guilds = session.query(Guild).filter_by(bot_id=bot_id).all()
        guild_names = {g.guild_id: g.guild_name or g.guild_id for g in guilds}
        members = session.query(MemberCache).filter_by(
            bot_id=bot_id
        ).order_by(MemberCache.guild_id, MemberCache.display_name).limit(limit).all()
        result = []
        by_guild = {}
        for m in members:
            gid = m.guild_id
            by_guild.setdefault(gid, []).append({
                "user_id": m.user_id or "",
                "display_name": m.display_name or m.username or m.user_id or "",
            })
        for gid, items in by_guild.items():
            result.append({
                "guild_id": gid,
                "guild_name": guild_names.get(gid, gid),
                "member_count": len(items),
                "members": items,
            })
        result.sort(key=lambda x: -x["member_count"])
        return result
    finally:
        session.close()


def get_kick_logs_global(bot_id: str = None, limit: int = 50) -> list[dict]:
    """全局最近踢人记录（跨服务器，按时间倒序）"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        guilds = session.query(Guild).filter_by(bot_id=bot_id).all()
        guild_names = {g.guild_id: g.guild_name or g.guild_id for g in guilds}
        logs = session.query(TrapLog).order_by(TrapLog.kicked_at.desc()).limit(limit).all()
        return [
            {
                "user_name": r.user_name or "",
                "guild_id": r.guild_id or "",
                "guild_name": guild_names.get(r.guild_id, r.guild_id or ""),
                "channel_id": r.channel_id or "",
                "channel_name": f"#{r.channel_id}" if r.channel_id else "",
                "kicked_at": _fmt_bj(r.kicked_at),
                "reason": r.reason or "",
            }
            for r in logs
        ]
    finally:
        session.close()


def get_message_tasks_by_status(bot_id: str = None, status: str = "pending", limit: int = 100) -> list[dict]:
    """按状态返回消息任务列表（供监控弹窗展示）"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        guilds = session.query(Guild).filter_by(bot_id=bot_id).all()
        guild_names = {g.guild_id: g.guild_name or g.guild_id for g in guilds}
        tasks = session.query(MessageTask).filter_by(
            bot_id=bot_id, status=status
        ).order_by(MessageTask.created_at.desc()).limit(limit).all()
        return [
            {
                "task_id": t.id,
                "task_name": t.task_name,
                "guild_id": t.guild_id,
                "guild_name": guild_names.get(t.guild_id, t.guild_id or "全局"),
                "channel_id": t.channel_id or "",
                "status": t.status or "",
                "schedule_type": t.schedule_type or "",
                "scheduled_at": _fmt_bj(t.scheduled_at, "%Y-%m-%d %H:%M"),
                "result_msg": t.result_msg or "",
                "created_at": _fmt_bj(t.created_at, "%Y-%m-%d %H:%M"),
            }
            for t in tasks
        ]
    finally:
        session.close()

# ----- 配置读取（强制带 bot_id 和 guild_id，预留扩展）-----
def get_guild_config(bot_id: str, guild_id: str, config_key: str):
    session = SessionLocal()
    try:
        record = session.query(GuildConfig).filter_by(
            bot_id=bot_id, 
            guild_id=guild_id, 
            config_key=config_key
        ).first()
        return record.config_value if record else None
    finally:
        session.close()

def set_guild_config(bot_id: str, guild_id: str, config_key: str, config_value: str):
    session = SessionLocal()
    try:
        record = session.query(GuildConfig).filter_by(
            bot_id=bot_id, guild_id=guild_id, config_key=config_key
        ).first()
        if record:
            record.config_value = config_value
        else:
            record = GuildConfig(
                bot_id=bot_id, guild_id=guild_id, 
                config_key=config_key, config_value=config_value
            )
            session.add(record)
        session.commit()
    finally:
        session.close()

# ----- 事件日志（机器人和Web共用）-----
def add_system_event(source: str, event_type: str, message: str):
    session = SessionLocal()
    try:
        event = SystemEvent(event_source=source, event_type=event_type, message=message)
        session.add(event)
        session.commit()
    finally:
        session.close()

def get_recent_events(limit: int = 10):
    session = SessionLocal()
    try:
        records = session.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(limit).all()
        return records
    finally:
        session.close()


# ===== UID 采集进程（Campaign）=====

def _uid_campaign_to_dict(c: UIDCampaign) -> dict:
    return {
        "id": c.id,
        "name": c.name or "未命名采集",
        "status": c.status,
        "bot_id": c.bot_id,
        "guild_id": c.guild_id,
        "channel_id": c.channel_id,
        "uid_length": c.uid_length or 8,
        "valid_reaction": c.valid_reaction or "✅",
        "duplicate_reaction": c.duplicate_reaction or "❌",
        "msg_overlap": c.msg_overlap or "",
        "msg_multiple": c.msg_multiple or "",
        "msg_length": c.msg_length or "",
        "started_at": _fmt_bj(c.started_at, "%Y-%m-%d %H:%M") if c.started_at else "",
        "end_at": _fmt_bj(c.end_at, "%Y-%m-%d %H:%M") if c.end_at else "",
        "last_scan_message_id": c.last_scan_message_id or "",
        "created_at": _fmt_bj(c.created_at, "%Y-%m-%d %H:%M") if c.created_at else "",
        "updated_at": _fmt_bj(c.updated_at, "%Y-%m-%d %H:%M") if c.updated_at else "",
    }


# 默认质询模板（中英双语）
_DEFAULT_MSG_OVERLAP = (
    "{user} 你提交的 UID **{uid}** 与之前某条消息重叠，请确认是否有误。\n"
    "{user} The UID **{uid}** you submitted matches that of a previous message. "
    "Please check to see if there is an error."
)
_DEFAULT_MSG_MULTIPLE = (
    "{user} 每个用户只能提交一个 UID，最新的 UID **{uid}** 作废，以你首次提交的为准。\n"
    "{user} Each user may submit only one UID. The most recent UID, **{uid}**, is invalid; "
    "the one you submitted first will be used."
)
_DEFAULT_MSG_LENGTH = (
    "{user} 你消息里的数字位数与要求不符，请确认是否为 {uid_length} 位 UID。\n"
    "{user} The number of digits in your message does not match the requirements. "
    "Please verify that your UID is {uid_length} digits long."
)


def uid_create_campaign(bot_id: str, name: str, guild_id: str, channel_id: str,
                        uid_length: int = 8, valid_reaction: str = "✅",
                        duplicate_reaction: str = "❌",
                        msg_overlap: str = None, msg_multiple: str = None,
                        msg_length: str = None, started_at=None, end_at=None) -> int:
    """新建采集进程。若该频道已被其他 running/paused 进程占用，返回 -1。"""
    session = SessionLocal()
    try:
        occupied = session.query(UIDCampaign).filter(
            UIDCampaign.bot_id == bot_id,
            UIDCampaign.channel_id == channel_id,
            UIDCampaign.status.in_([UID_CAMPAIGN_RUNNING, UID_CAMPAIGN_PAUSED]),
        ).first()
        if occupied:
            return -1
        camp = UIDCampaign(
            name=name, status=UID_CAMPAIGN_RUNNING, bot_id=bot_id,
            guild_id=guild_id, channel_id=channel_id, uid_length=uid_length or 8,
            valid_reaction=valid_reaction or "✅",
            duplicate_reaction=duplicate_reaction or "❌",
            msg_overlap=msg_overlap if msg_overlap is not None else _DEFAULT_MSG_OVERLAP,
            msg_multiple=msg_multiple if msg_multiple is not None else _DEFAULT_MSG_MULTIPLE,
            msg_length=msg_length if msg_length is not None else _DEFAULT_MSG_LENGTH,
            started_at=started_at, end_at=end_at,
        )
        session.add(camp)
        session.commit()
        return camp.id
    except Exception as e:
        session.rollback()
        print(f"[DB] uid_create_campaign 失败: {e}")
        return -1
    finally:
        session.close()


def uid_get_campaigns(bot_id: str) -> list[dict]:
    """获取该 bot 下所有采集进程（含各进程统计摘要）"""
    session = SessionLocal()
    try:
        camps = session.query(UIDCampaign).filter_by(bot_id=bot_id).order_by(
            UIDCampaign.created_at.desc()).all()
        result = []
        for c in camps:
            d = _uid_campaign_to_dict(c)
            d["stats"] = _uid_stats_for(session, c.id)
            result.append(d)
        return result
    finally:
        session.close()


def uid_get_campaign(bot_id: str, campaign_id: int) -> dict:
    session = SessionLocal()
    try:
        c = session.query(UIDCampaign).filter_by(
            bot_id=bot_id, id=campaign_id).first()
        return _uid_campaign_to_dict(c) if c else None
    finally:
        session.close()


def uid_update_campaign(bot_id: str, campaign_id: int, updates: dict) -> bool:
    """更新进程。若更新频道与其他 running/paused 进程冲突则返回 False。"""
    session = SessionLocal()
    try:
        c = session.query(UIDCampaign).filter_by(
            bot_id=bot_id, id=campaign_id).first()
        if not c:
            return False
        # 频道占用查重（排除自身）
        new_channel = updates.get("channel_id")
        if new_channel and new_channel != c.channel_id:
            occupied = session.query(UIDCampaign).filter(
                UIDCampaign.bot_id == bot_id,
                UIDCampaign.channel_id == new_channel,
                UIDCampaign.id != campaign_id,
                UIDCampaign.status.in_([UID_CAMPAIGN_RUNNING, UID_CAMPAIGN_PAUSED]),
            ).first()
            if occupied:
                return False
        for k, v in updates.items():
            if hasattr(c, k):
                setattr(c, k, v)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] uid_update_campaign 失败: {e}")
        return False
    finally:
        session.close()


def uid_set_campaign_status(bot_id: str, campaign_id: int, status: str) -> tuple[bool, str]:
    """设置进程状态（running/paused/ended），返回 (是否成功, 提示消息)。

    状态操作严格受进程时间范围约束：
    - 置为 running 时：若结束时间已过，则拒绝（不允许把已到期的进程继续运行）。
      开始时间未到则允许（bot 侧会等到开始时间再扫描）。
    - paused/ended：不限时间。
    """
    import datetime as _dt
    now = _dt.datetime.utcnow()
    session = SessionLocal()
    try:
        c = session.query(UIDCampaign).filter_by(bot_id=bot_id, id=campaign_id).first()
        if not c:
            return False, "进程不存在"
        if status == UID_CAMPAIGN_RUNNING:
            if c.end_at is not None and now > c.end_at:
                return False, "该进程已过结束时间，不能继续运行"
        c.status = status
        session.commit()
        if status == UID_CAMPAIGN_RUNNING:
            return True, "进程已恢复运行"
        if status == UID_CAMPAIGN_PAUSED:
            return True, "进程已暂停"
        return True, "进程已结束"
    except Exception as e:
        session.rollback()
        print(f"[DB] uid_set_campaign_status 失败: {e}")
        return False, "操作失败"
    finally:
        session.close()


def uid_delete_campaign(bot_id: str, campaign_id: int) -> bool:
    """删除进程及其所有采集记录"""
    session = SessionLocal()
    try:
        c = session.query(UIDCampaign).filter_by(
            bot_id=bot_id, id=campaign_id).first()
        if not c:
            return False
        session.query(UIDRecord).filter_by(campaign_id=campaign_id).delete(
            synchronize_session=False)
        session.delete(c)
        session.commit()
        return True
    finally:
        session.close()


def uid_is_channel_occupied(bot_id: str, channel_id: str, exclude_campaign_id: int = None) -> bool:
    """该频道是否已被 running/paused 进程占用"""
    session = SessionLocal()
    try:
        q = session.query(UIDCampaign).filter(
            UIDCampaign.bot_id == bot_id,
            UIDCampaign.channel_id == channel_id,
            UIDCampaign.status.in_([UID_CAMPAIGN_RUNNING, UID_CAMPAIGN_PAUSED]),
        )
        if exclude_campaign_id:
            q = q.filter(UIDCampaign.id != exclude_campaign_id)
        return q.first() is not None
    finally:
        session.close()


def uid_get_running_campaigns(bot_id: str) -> list:
    """获取所有运行中的进程（供 bot 采集用）"""
    session = SessionLocal()
    try:
        return session.query(UIDCampaign).filter_by(
            bot_id=bot_id, status=UID_CAMPAIGN_RUNNING).all()
    finally:
        session.close()


def uid_end_expired_campaigns(bot_id: str, now_utc=None) -> int:
    """把已过结束时间的 running 进程自动置为 ended，返回结案数"""
    import datetime as _dt
    now = now_utc or _dt.datetime.utcnow()
    session = SessionLocal()
    try:
        rows = session.query(UIDCampaign).filter(
            UIDCampaign.bot_id == bot_id,
            UIDCampaign.status == UID_CAMPAIGN_RUNNING,
            UIDCampaign.end_at.isnot(None),
            UIDCampaign.end_at <= now,
        ).all()
        n = 0
        for r in rows:
            r.status = UID_CAMPAIGN_ENDED
            n += 1
        if n:
            session.commit()
        return n
    except Exception as e:
        session.rollback()
        print(f"[DB] uid_end_expired_campaigns 失败: {e}")
        return 0
    finally:
        session.close()


def uid_set_last_scan(bot_id: str, campaign_id: int, message_id: str):
    """记录某进程的增量扫描游标"""
    session = SessionLocal()
    try:
        c = session.query(UIDCampaign).filter_by(
            bot_id=bot_id, id=campaign_id).first()
        if c:
            c.last_scan_message_id = str(message_id)
            session.commit()
    finally:
        session.close()


# ===== UID 采集记录 =====

def _uid_to_dict(r: UIDRecord) -> dict:
    """把 UIDRecord 转成前端可用的 dict。DB 里可空字段可能是 None，
    统一转成空字符串，避免 Pydantic str 字段校验失败。"""
    created = _fmt_bj(r.created_at, "%Y-%m-%d %H:%M")
    return {
        "id": r.id,
        "campaign_id": r.campaign_id,
        "bot_id": r.bot_id,
        "guild_id": r.guild_id,
        "channel_id": r.channel_id,
        "message_id": r.message_id,
        "user_id": r.user_id,
        "user_name": r.user_name or "",
        "uid": r.uid or "",
        "answer": r.answer or "",
        "status": r.status or "",
        "invalid_reason": r.invalid_reason or "",
        "raw_content": r.raw_content or "",
        "mentioned_users": r.mentioned_users or "[]",
        "scanned": bool(r.scanned),
        "created_at": created or "",
    }


def uid_record_exists(bot_id: str, campaign_id: int, message_id: str) -> bool:
    """该消息在该进程内是否已处理过（message_id 去重）"""
    session = SessionLocal()
    try:
        return session.query(UIDRecord).filter_by(
            bot_id=bot_id, campaign_id=campaign_id, message_id=message_id
        ).first() is not None
    finally:
        session.close()


def uid_find_valid_by_uid(bot_id: str, campaign_id: int, uid: str) -> list:
    """查找该进程内该 UID 已存在的有效记录（用于判定重叠）"""
    session = SessionLocal()
    try:
        return session.query(UIDRecord).filter_by(
            bot_id=bot_id, campaign_id=campaign_id, uid=uid, status=UID_STATUS_VALID
        ).order_by(UIDRecord.created_at.asc()).all()
    finally:
        session.close()


def uid_find_valid_by_user(bot_id: str, campaign_id: int, user_id: str) -> list:
    """查找该进程内该用户已提交的有效 UID 记录（用于判定同一人多发）"""
    session = SessionLocal()
    try:
        return session.query(UIDRecord).filter_by(
            bot_id=bot_id, campaign_id=campaign_id, user_id=user_id,
            status=UID_STATUS_VALID,
        ).order_by(UIDRecord.created_at.asc()).all()
    finally:
        session.close()


def uid_upsert_record(bot_id: str, campaign_id: int, guild_id: str, channel_id: str,
                      message_id: str, user_id: str, user_name: str, uid: str,
                      answer: str, status: str, invalid_reason: str = None,
                      raw_content: str = "", mentioned_users: list = None,
                      scanned: bool = False) -> bool:
    """新增/更新一条 UID 记录。同进程内已存在（同 message_id）则更新。"""
    import json
    session = SessionLocal()
    try:
        rec = session.query(UIDRecord).filter_by(
            bot_id=bot_id, campaign_id=campaign_id, message_id=message_id
        ).first()
        mentioned_json = json.dumps(mentioned_users or [], ensure_ascii=False)
        if rec:
            rec.guild_id = guild_id
            rec.channel_id = channel_id
            rec.user_id = user_id
            rec.user_name = user_name
            rec.uid = uid
            rec.answer = answer
            rec.status = status
            rec.invalid_reason = invalid_reason
            rec.raw_content = raw_content
            rec.mentioned_users = mentioned_json
            rec.scanned = scanned
        else:
            rec = UIDRecord(
                campaign_id=campaign_id, bot_id=bot_id, guild_id=guild_id,
                channel_id=channel_id, message_id=message_id, user_id=user_id,
                user_name=user_name, uid=uid, answer=answer, status=status,
                invalid_reason=invalid_reason, raw_content=raw_content,
                mentioned_users=mentioned_json, scanned=scanned,
            )
            session.add(rec)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] uid_upsert_record 失败: {e}")
        return False
    finally:
        session.close()


def uid_get_records(bot_id: str, campaign_id: int = None,
                    start: str = None, end: str = None,
                    status: str = None) -> list[dict]:
    """查询 UID 记录（按进程隔离），支持时间范围（北京时间）与状态筛选。"""
    session = SessionLocal()
    try:
        q = session.query(UIDRecord).filter(UIDRecord.bot_id == bot_id)
        if campaign_id:
            q = q.filter(UIDRecord.campaign_id == campaign_id)
        if status:
            q = q.filter(UIDRecord.status == status)
        if start:
            q = q.filter(UIDRecord.created_at >= parse_datetime_to_utc(start))
        if end:
            q = q.filter(UIDRecord.created_at <= parse_datetime_to_utc(end))
        rows = q.order_by(UIDRecord.created_at.desc()).all()
        return [_uid_to_dict(r) for r in rows]
    finally:
        session.close()


def uid_get_statistics(bot_id: str, campaign_id: int = None,
                       start: str = None, end: str = None) -> dict:
    """UID 采集统计报告（按进程隔离）"""
    session = SessionLocal()
    try:
        return _uid_stats_for(session, campaign_id, start, end)
    finally:
        session.close()


def _uid_stats_for(session, campaign_id: int = None,
                   start: str = None, end: str = None) -> dict:
    q = session.query(UIDRecord)
    if campaign_id:
        q = q.filter(UIDRecord.campaign_id == campaign_id)
    if start:
        q = q.filter(UIDRecord.created_at >= parse_datetime_to_utc(start))
    if end:
        q = q.filter(UIDRecord.created_at <= parse_datetime_to_utc(end))
    rows = q.all()
    total = len(rows)
    valid = sum(1 for r in rows if r.status == UID_STATUS_VALID)
    duplicate = sum(1 for r in rows if r.status == UID_STATUS_DUPLICATE)
    invalid = sum(1 for r in rows if r.status == UID_STATUS_INVALID)
    unique_uids = len({r.uid for r in rows if r.status == UID_STATUS_VALID})
    return {
        "total": total,
        "valid": valid,
        "duplicate": duplicate,
        "invalid": invalid,
        "unique_uids": unique_uids,
    }


def uid_get_uid_list(bot_id: str, campaign_id: int = None,
                     start: str = None, end: str = None) -> list[str]:
    """获取有效 UID 的简略去重列表（纯字符串，便于导出/复制）"""
    records = uid_get_records(bot_id, campaign_id, start, end, status=UID_STATUS_VALID)
    seen = set()
    result = []
    for r in records:
        if r["uid"] not in seen:
            seen.add(r["uid"])
            result.append(r["uid"])
    return result


def uid_clear_records(bot_id: str, campaign_id: int = None) -> int:
    """清空某进程（或全部）的 UID 记录，返回删除条数"""
    session = SessionLocal()
    try:
        q = session.query(UIDRecord).filter(UIDRecord.bot_id == bot_id)
        if campaign_id:
            q = q.filter(UIDRecord.campaign_id == campaign_id)
        n = q.delete(synchronize_session=False)
        session.commit()
        return n
    finally:
        session.close()


# ===== UID 手动扫描任务（查漏补缺） =====

def uid_create_scan_task(bot_id: str, campaign_id: int) -> int:
    """创建一条手动扫描任务。若该进程已有 pending 任务则返回 -1。"""
    session = SessionLocal()
    try:
        existing = session.query(UIDScanTask).filter_by(
            bot_id=bot_id, campaign_id=campaign_id,
            status=UID_SCAN_TASK_PENDING,
        ).first()
        if existing:
            return -1
        task = UIDScanTask(bot_id=bot_id, campaign_id=campaign_id,
                           status=UID_SCAN_TASK_PENDING)
        session.add(task)
        session.commit()
        return task.id
    except Exception as e:
        session.rollback()
        print(f"[DB] uid_create_scan_task 失败: {e}")
        return -1
    finally:
        session.close()


def uid_get_pending_scan_tasks(bot_id: str) -> list:
    """获取该 bot 下所有待执行的扫描任务（供 bot 轮询领取）"""
    session = SessionLocal()
    try:
        return session.query(UIDScanTask).filter_by(
            bot_id=bot_id, status=UID_SCAN_TASK_PENDING,
        ).order_by(UIDScanTask.created_at.asc()).all()
    finally:
        session.close()


def uid_claim_scan_task(task_id: int) -> bool:
    """原子领取扫描任务：pending → processing，成功返回 True。"""
    from sqlalchemy import text
    session = SessionLocal()
    try:
        r = session.execute(
            text("UPDATE uid_scan_tasks SET status=:p WHERE id=:tid AND status=:pending"),
            {"p": UID_SCAN_TASK_PROCESSING, "tid": task_id, "pending": UID_SCAN_TASK_PENDING},
        )
        session.commit()
        return r.rowcount == 1
    except Exception as e:
        session.rollback()
        print(f"[DB] uid_claim_scan_task 失败: {e}")
        return False
    finally:
        session.close()


def uid_finish_scan_task(task_id: int, result: dict = None, error: str = ""):
    """扫描完成，写回结果或错误信息。"""
    import json
    session = SessionLocal()
    try:
        t = session.query(UIDScanTask).filter_by(id=task_id).first()
        if not t:
            return
        t.status = UID_SCAN_TASK_FAILED if error else UID_SCAN_TASK_DONE
        t.result = json.dumps(result or {}, ensure_ascii=False)
        t.error = error
        t.processed_at = datetime.datetime.utcnow()
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB] uid_finish_scan_task 失败: {e}")
    finally:
        session.close()


def uid_get_scan_tasks(bot_id: str, campaign_id: int, limit: int = 10) -> list[dict]:
    """获取某进程的扫描任务记录（倒序，供后台展示）。"""
    import json
    session = SessionLocal()
    try:
        rows = session.query(UIDScanTask).filter_by(
            bot_id=bot_id, campaign_id=campaign_id,
        ).order_by(UIDScanTask.id.desc()).limit(limit).all()
        result = []
        for r in rows:
            try:
                res = json.loads(r.result) if r.result else {}
            except Exception:
                res = {}
            result.append({
                "id": r.id,
                "status": r.status,
                "result": res,
                "error": r.error or "",
                "created_at": _fmt_bj(r.created_at),
                "processed_at": _fmt_bj(r.processed_at),
            })
        return result
    finally:
        session.close()


def sync_guilds_from_discord(bot_id: str, discord_guilds_list):
    """
    入参：bot_id, 以及从 discord.py 获取的 bot.guilds 列表
    功能：全量同步（对比差异，新增不存在的，更新已存在的）
    """
    session = SessionLocal()
    try:
        # 获取当前数据库中该 bot 已有的服务器ID
        existing_ids = {g.guild_id for g in session.query(Guild).filter_by(bot_id=bot_id).all()}
        
        # 遍历 Discord 返回的真实列表
        for g in discord_guilds_list:
            guild_id = str(g.id)
            # 更新或插入
            record = session.query(Guild).filter_by(bot_id=bot_id, guild_id=guild_id).first()
            if record:
                # 更新名称和人数（万一名称变了）
                record.guild_name = g.name
                record.member_count = g.member_count
            else:
                # 新增记录
                new_guild = Guild(
                    bot_id=bot_id,
                    guild_id=guild_id,
                    guild_name=g.name,
                    member_count=g.member_count,
                    joined_at=g.me.joined_at if g.me else datetime.datetime.utcnow()
                )
                session.add(new_guild)
            
            # 【预留逻辑】同时检查该服务器的默认配置是否存在，没有则自动创建
            # 这里先简单查一下 welcome_msg 是否存在，不存在就给个默认值
            default_config = session.query(GuildConfig).filter_by(
                bot_id=bot_id, guild_id=guild_id, config_key="welcome_msg"
            ).first()
            if not default_config:
                session.add(GuildConfig(
                    bot_id=bot_id, 
                    guild_id=guild_id, 
                    config_key="welcome_msg", 
                    config_value="🎉 欢迎新成员！"
                ))
        
        # （可选）如果发现数据库里有某个服务器，但 Discord 返回列表里没有，说明机器人被踢了，可以标记为 inactive，这里先不做删除，保留数据）
        session.commit()
        print(f"[DB] 成功同步 {len(discord_guilds_list)} 个真实服务器")
    except Exception as e:
        print(f"[DB] 同步失败: {e}")
        session.rollback()
    finally:
        session.close()

# --- 新增：Web 后台获取带名称的服务器配置列表 ---
def get_guilds_with_config(bot_id: str):
    """
    供 Web 后台展示：左连接查询，显示每个服务器的名称和它的配置项
    返回结构：[{"guild_id": "...", "guild_name": "...", "configs": {"welcome_msg": "..."}}]
    """
    session = SessionLocal()
    try:
        # 查询该 bot 下的所有真实服务器
        guilds = session.query(Guild).filter_by(bot_id=bot_id).all()
        result = []
        for g in guilds:
            # 查询这个服务器的所有配置（键值对）
            configs = session.query(GuildConfig).filter_by(bot_id=bot_id, guild_id=g.guild_id).all()
            config_dict = {c.config_key: c.config_value for c in configs}
            result.append({
                "guild_id": g.guild_id,
                "guild_name": g.guild_name,
                "member_count": g.member_count,
                "configs": config_dict
            })
        return result
    finally:
        session.close()

def get_active_bots() -> list[tuple]:
    """获取所有已激活的 Bot 列表，返回 [(bot_id, bot_name), ...]"""
    session = SessionLocal()
    try:
        bots = session.query(Bot).filter_by(is_active=True).all()
        return [(b.bot_id, b.bot_name) for b in bots]
    finally:
        session.close()


def get_all_bots() -> list[tuple]:
    """获取所有 Bot 列表（含未激活），返回 [(bot_id, bot_name), ...]，
    供后台机器人管理弹窗显示与切换（未激活的也可切回配置）"""
    session = SessionLocal()
    try:
        bots = session.query(Bot).order_by(Bot.bot_id).all()
        return [(b.bot_id, b.bot_name) for b in bots]
    finally:
        session.close()

def get_guilds(bot_id: str) -> list[dict]:
    """获取某个机器人的所有服务器列表"""
    session = SessionLocal()
    try:
        guilds = session.query(Guild).filter_by(bot_id=bot_id).all()
        return [
            {
                "guild_id": g.guild_id,
                "guild_name": g.guild_name,
                "member_count": g.member_count
            }
            for g in guilds
        ]
    finally:
        session.close()

# ========== 频道缓存 CRUD ==========

def upsert_channel(bot_id: str, guild_id: str, channel_id: str, channel_name: str,
                   channel_type: str = "text", parent_channel_id: str = None):
    """
    插入或更新频道缓存
    用于机器人启动时同步所有可见的频道（文字/论坛/帖子）
    """
    session = SessionLocal()
    try:
        record = session.query(ChannelCache).filter_by(
            bot_id=bot_id,
            channel_id=channel_id
        ).first()
        if record:
            # 更新已有记录
            record.guild_id = guild_id
            record.channel_name = channel_name
            record.channel_type = channel_type
            record.is_available = True
            record.parent_channel_id = parent_channel_id
            record.updated_at = datetime.datetime.utcnow()
        else:
            # 插入新记录
            new_channel = ChannelCache(
                bot_id=bot_id,
                guild_id=guild_id,
                channel_id=channel_id,
                channel_name=channel_name,
                channel_type=channel_type,
                is_available=True,
                parent_channel_id=parent_channel_id,
            )
            session.add(new_channel)
        session.commit()
        return True
    except Exception as e:
        print(f"[DB] upsert_channel 失败: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def bulk_upsert_channels(bot_id: str, guild_id: str, channels: list[dict]) -> int:
    """批量插入/更新频道缓存，一次事务完成，避免逐个提交带来锁竞争与卡顿。

    channels: [{"channel_id": str, "channel_name": str, "channel_type": str,
                "parent_channel_id": str|None}, ...]
    返回成功写入/更新的条数。
    """
    if not channels:
        return 0
    session = SessionLocal()
    try:
        existing = {
            c.channel_id: c
            for c in session.query(ChannelCache).filter_by(
                bot_id=bot_id, guild_id=guild_id
            ).all()
        }
        now = datetime.datetime.utcnow()
        to_add = []
        for ch in channels:
            cid = str(ch.get("channel_id", ""))
            if not cid:
                continue
            rec = existing.get(cid)
            if rec:
                rec.channel_name = ch.get("channel_name", "") or ""
                rec.channel_type = ch.get("channel_type", "text") or "text"
                rec.parent_channel_id = ch.get("parent_channel_id") or None
                rec.is_available = True
                rec.updated_at = now
            else:
                to_add.append(ChannelCache(
                    bot_id=bot_id, guild_id=guild_id, channel_id=cid,
                    channel_name=ch.get("channel_name", "") or "",
                    channel_type=ch.get("channel_type", "text") or "text",
                    parent_channel_id=ch.get("parent_channel_id") or None,
                    is_available=True,
                ))
        session.add_all(to_add)
        session.commit()
        return len(existing) + len(to_add)
    except Exception as e:
        session.rollback()
        print(f"[DB] bulk_upsert_channels 失败: {e}")
        return 0
    finally:
        session.close()


def get_channels(bot_id: str, guild_id: str = None) -> list[dict]:
    """
    获取某个机器人可见的所有文字频道
    如果指定 guild_id，则只返回该服务器的频道
    返回结构: [{"channel_id": "...", "channel_name": "...", "guild_id": "..."}]
    """
    session = SessionLocal()
    try:
        query = session.query(ChannelCache).filter_by(
            bot_id=bot_id,
            is_available=True
        )
        if guild_id:
            query = query.filter_by(guild_id=guild_id)
        # 只返回文字频道
        query = query.filter_by(channel_type="text")
        results = query.order_by(ChannelCache.channel_name).all()
        return [
            {
                "channel_id": r.channel_id,
                "channel_name": r.channel_name,
                "guild_id": r.guild_id
            }
            for r in results
        ]
    finally:
        session.close()


# ========== 陷阱配置 CRUD ==========

def get_trap_config(bot_id: str, guild_id: str) -> TrapConfig | None:
    """
    获取某个服务器的陷阱配置
    如果不存在则返回 None
    """
    session = SessionLocal()
    try:
        return session.query(TrapConfig).filter_by(
            bot_id=bot_id,
            guild_id=guild_id
        ).first()
    finally:
        session.close()


def get_or_create_trap_config(bot_id: str, guild_id: str) -> TrapConfig:
    """
    获取或创建陷阱配置（如果不存在则创建默认配置）
    """
    session = SessionLocal()
    try:
        config = session.query(TrapConfig).filter_by(
            bot_id=bot_id,
            guild_id=guild_id
        ).first()
        if not config:
            config = TrapConfig(
                bot_id=bot_id,
                guild_id=guild_id,
                trap_channel_id=None,
                is_enabled=False,
                whitelist_roles="",
                whitelist_users="",
                kick_message="⚠️ 本频道禁止非授权成员发言"
            )
            session.add(config)
            session.commit()
        return config
    finally:
        session.close()


def set_trap_config(
    bot_id: str,
    guild_id: str,
    trap_channel_id: str = None,
    is_enabled: bool = False,
    whitelist_roles: str = "",
    whitelist_users: str = "",
    kick_message: str = "⚠️ 本频道禁止非授权成员发言"
) -> bool:
    """
    保存陷阱配置
    如果配置不存在则自动创建
    """
    session = SessionLocal()
    try:
        config = session.query(TrapConfig).filter_by(
            bot_id=bot_id,
            guild_id=guild_id
        ).first()
        if not config:
            config = TrapConfig(
                bot_id=bot_id,
                guild_id=guild_id
            )
            session.add(config)

        config.trap_channel_id = trap_channel_id
        config.is_enabled = is_enabled
        config.whitelist_roles = whitelist_roles
        config.whitelist_users = whitelist_users
        config.kick_message = kick_message
        config.updated_at = datetime.datetime.utcnow()
        session.commit()
        return True
    except Exception as e:
        print(f"[DB] set_trap_config 失败: {e}")
        session.rollback()
        return False
    finally:
        session.close()


# ========== 踢人日志 CRUD ==========

def add_trap_log(
    bot_id: str,
    guild_id: str,
    channel_id: str,
    user_id: str,
    user_name: str,
    reason: str = "在陷阱频道发言"
) -> bool:
    """记录一条踢人日志"""
    session = SessionLocal()
    try:
        log = TrapLog(
            bot_id=bot_id,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            user_name=user_name,
            reason=reason
        )
        session.add(log)
        session.commit()
        return True
    except Exception as e:
        print(f"[DB] add_trap_log 失败: {e}")
        session.rollback()
        return False
    finally:
        session.close()


def get_trap_logs(bot_id: str, guild_id: str = None, limit: int = 50) -> list[dict]:
    """
    获取踢人日志
    如果指定 guild_id，只获取该服务器的日志
    """
    session = SessionLocal()
    try:
        query = session.query(TrapLog).filter_by(bot_id=bot_id)
        if guild_id:
            query = query.filter_by(guild_id=guild_id)
        results = query.order_by(TrapLog.kicked_at.desc()).limit(limit).all()

        # 批量查询频道名称映射（找不到时回退为 #channel_id）
        channel_ids = list({r.channel_id for r in results if r.channel_id})
        channel_map = {}
        if channel_ids:
            channels = session.query(ChannelCache).filter(
                ChannelCache.channel_id.in_(channel_ids)
            ).all()
            channel_map = {c.channel_id: c.channel_name for c in channels}

        return [
            {
                "user_name": r.user_name,
                "user_id": r.user_id,
                "channel_id": r.channel_id,
                "channel_name": channel_map.get(r.channel_id, f"#{r.channel_id}"),
                "guild_id": r.guild_id,
                "kicked_at": _fmt_bj(r.kicked_at),
                "reason": r.reason
            }
            for r in results
        ]
    finally:
        session.close()


# ========== 礼包码系统 CRUD ==========

# 全局锁：保证领取操作的原子性（SQLite 单写锁 + 应用层串行化）
_gift_lock = threading.Lock()


def read_xlsx_headers(file_bytes: bytes) -> list[str]:
    """
    读取 xlsx 文件第一行的列名，供前端选择礼包码所在列
    返回: 列名列表，如 ["礼包id", "激活码", "礼包名称", "使用标识"]
    """
    columns = []
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    ws = wb.active
    for cell in ws[1]:
        if cell.value is not None:
            columns.append(str(cell.value).strip())
    wb.close()
    return columns


def parse_codes_from_xlsx(file_bytes: bytes, col_index: int = 1) -> list[str]:
    """
    从 xlsx 文件的字节流中解析礼包码列表
    col_index: 从 1 开始的列索引（1=A列, 2=B列...），默认 1
    """
    codes = []
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    ws = wb.active
    for row in ws.iter_rows(min_col=col_index, max_col=col_index, min_row=2, values_only=True):
        val = row[0]
        if val is not None and str(val).strip():
            codes.append(str(val).strip())
    wb.close()
    return codes


def create_gift_code_batch(
    bot_id: str,
    guild_id: str,
    batch_name: str,
    command_text: str,
    codes: list[str],
) -> dict:
    """
    创建一个新的礼包码批次，批量插入礼包码
    返回: {"success": bool, "batch_id": int, "message": str}
    """
    if not codes:
        return {"success": False, "batch_id": None, "message": "礼包码列表不能为空"}

    session = SessionLocal()
    try:
        # 检查同一服务器下口令是否重复
        existing = session.query(GiftCodeBatch).filter_by(
            bot_id=bot_id,
            guild_id=guild_id,
            command_text=command_text,
        ).first()
        if existing:
            return {"success": False, "batch_id": None, "message": f"口令 '{command_text}' 已存在，请使用不同的口令"}

        # 创建批次
        batch = GiftCodeBatch(
            bot_id=bot_id,
            guild_id=guild_id,
            batch_name=batch_name,
            command_text=command_text,
            total_count=len(codes),
            claimed_count=0,
            is_active=True,
        )
        session.add(batch)
        session.flush()  # 获取 batch.id

        # 批量插入礼包码
        code_objects = [GiftCode(batch_id=batch.id, code=c) for c in codes]
        session.add_all(code_objects)
        session.commit()

        print(f"[DB] 创建礼包码批次 '{batch_name}', 口令='{command_text}', 共 {len(codes)} 个码")
        return {
            "success": True,
            "batch_id": batch.id,
            "message": f"批次 '{batch_name}' 创建成功，共导入 {len(codes)} 个礼包码",
        }
    except Exception as e:
        session.rollback()
        print(f"[DB] create_gift_code_batch 失败: {e}")
        return {"success": False, "batch_id": None, "message": f"创建失败: {str(e)}"}
    finally:
        session.close()


def check_active_batch_exists(bot_id: str, guild_id: str, command_text: str) -> bool:
    """
    快速检查是否存在匹配的活跃批次（不加锁，供 on_message 预过滤用）。
    避免每条频道消息都去争全局锁。
    """
    session = SessionLocal()
    try:
        exists = session.query(GiftCodeBatch).filter_by(
            bot_id=bot_id,
            guild_id=guild_id,
            command_text=command_text.strip().lower(),
            is_active=True,
        ).first()
        return exists is not None
    finally:
        session.close()


def claim_gift_code(
    bot_id: str,
    guild_id: str,
    channel_id: str,
    user_id: str,
    user_name: str,
    command_text: str,
) -> dict:
    """
    【原子操作】用户通过口令领取一个礼包码
    使用全局锁 + 事务保证：
      1. 同个礼包码不会发给多人
      2. 同个用户同批次只能领一次
    返回: {"success": bool, "code": str|None, "message": str, "already_claimed": bool}
    """
    with _gift_lock:
        session = SessionLocal()
        try:
            # 1. 查找启用的批次
            batch = session.query(GiftCodeBatch).filter_by(
                bot_id=bot_id,
                guild_id=guild_id,
                command_text=command_text.strip().lower(),
                is_active=True,
            ).first()

            if not batch:
                return {
                    "success": False, "code": None,
                    "message": _msg("claim_not_found", bot_id, command_text=command_text),
                    "already_claimed": False,
                }

            # 2. 检查该用户在本批次是否已领取过
            existing = session.query(GiftCode).filter_by(
                batch_id=batch.id,
                claimed_by_user_id=user_id,
                is_claimed=True,
            ).first()

            if existing:
                return {
                    "success": True, "code": existing.code,
                    "message": _msg("claim_already_claimed", bot_id, batch_name=batch.batch_name, code_value=existing.code),
                    "already_claimed": True,
                }

            # 3. 原子分配：子查询选一条未领取的码，UPDATE 时再次检查 is_claimed=0
            from sqlalchemy import text

            now = datetime.datetime.utcnow()
            result = session.execute(
                text("""
                    UPDATE gift_codes
                    SET is_claimed = 1,
                        claimed_by_user_id = :uid,
                        claimed_by_user_name = :uname,
                        claimed_at = :now
                    WHERE id = (
                        SELECT id FROM gift_codes
                        WHERE batch_id = :bid AND is_claimed = 0
                        LIMIT 1
                    ) AND is_claimed = 0
                """),
                {"uid": user_id, "uname": user_name, "now": now, "bid": batch.id},
            )

            if result.rowcount == 0:
                return {
                    "success": False, "code": None,
                    "message": _msg("claim_sold_out", bot_id, batch_name=batch.batch_name),
                    "already_claimed": False,
                }

            # 4. 读取刚分配到的礼包码
            claimed = session.query(GiftCode).filter_by(
                batch_id=batch.id, claimed_by_user_id=user_id
            ).order_by(GiftCode.claimed_at.desc()).first()

            code_value = claimed.code if claimed else ""

            # 5. 更新批次已领取计数
            new_count = session.query(GiftCode).filter_by(
                batch_id=batch.id, is_claimed=True
            ).count()
            batch.claimed_count = new_count

            # 6. 记录领取日志
            log = GiftClaimLog(
                batch_id=batch.id,
                bot_id=bot_id,
                guild_id=guild_id,
                channel_id=channel_id,
                code=code_value,
                user_id=user_id,
                user_name=user_name,
            )
            session.add(log)
            session.commit()

            print(f"[DB] 用户 {user_name}({user_id}) 领取了批次 '{batch.batch_name}' 的礼包码: {code_value}")
            return {
                "success": True, "code": code_value,
                "message": _msg("claim_success", bot_id, batch_name=batch.batch_name, code_value=code_value),
                "already_claimed": False,
            }

        except Exception as e:
            session.rollback()
            print(f"[DB] claim_gift_code 失败: {e}")
            return {
                "success": False, "code": None,
                "message": _msg("claim_failed", bot_id),
                "already_claimed": False,
            }
        finally:
            session.close()


def get_gift_code_batches(bot_id: str, guild_id: str) -> list[dict]:
    """获取某个服务器的所有礼包码批次"""
    session = SessionLocal()
    try:
        batches = session.query(GiftCodeBatch).filter_by(
            bot_id=bot_id, guild_id=guild_id
        ).order_by(GiftCodeBatch.created_at.desc()).all()
        return [
            {
                "id": b.id,
                "batch_name": b.batch_name,
                "command_text": b.command_text,
                "total_count": b.total_count,
                "claimed_count": b.claimed_count,
                "is_active": b.is_active,
                "created_at": _fmt_bj(b.created_at),
            }
            for b in batches
        ]
    finally:
        session.close()


def get_batch_detail(batch_id: int) -> dict | None:
    """获取某个批次的详细信息（含所有礼包码状态）"""
    session = SessionLocal()
    try:
        batch = session.query(GiftCodeBatch).filter_by(id=batch_id).first()
        if not batch:
            return None

        codes = session.query(GiftCode).filter_by(batch_id=batch_id).order_by(GiftCode.id).all()
        return {
            "id": batch.id,
            "batch_name": batch.batch_name,
            "command_text": batch.command_text,
            "total_count": batch.total_count,
            "claimed_count": batch.claimed_count,
            "is_active": batch.is_active,
            "created_at": _fmt_bj(batch.created_at),
            "codes": [
                {
                    "id": c.id,
                    "code": c.code,
                    "is_claimed": c.is_claimed,
                    "claimed_by_user_name": c.claimed_by_user_name or "",
                    "claimed_at": _fmt_bj(c.claimed_at),
                }
                for c in codes
            ],
        }
    finally:
        session.close()


def get_claim_logs_for_batch(bot_id: str, guild_id: str, batch_id: int = None, limit: int = 100) -> list[dict]:
    """获取领取日志，可按批次筛选"""
    session = SessionLocal()
    try:
        query = session.query(GiftClaimLog).filter_by(bot_id=bot_id, guild_id=guild_id)
        if batch_id:
            query = query.filter_by(batch_id=batch_id)
        results = query.order_by(GiftClaimLog.claimed_at.desc()).limit(limit).all()

        # 批量查询频道名称映射
        channel_ids = list({r.channel_id for r in results if r.channel_id})
        channel_map = {}
        if channel_ids:
            channels = session.query(ChannelCache).filter(
                ChannelCache.channel_id.in_(channel_ids)
            ).all()
            channel_map = {c.channel_id: c.channel_name for c in channels}

        return [
            {
                "id": r.id,
                "batch_id": r.batch_id,
                "code": r.code,
                "user_name": r.user_name,
                "user_id": r.user_id,
                "channel_id": r.channel_id,
                "channel_name": channel_map.get(r.channel_id, f"#{r.channel_id}"),
                "claimed_at": _fmt_bj(r.claimed_at),
            }
            for r in results
        ]
    finally:
        session.close()


def toggle_batch_status(batch_id: int, is_active: bool) -> bool:
    """启用/停用批次"""
    session = SessionLocal()
    try:
        batch = session.query(GiftCodeBatch).filter_by(id=batch_id).first()
        if not batch:
            return False
        batch.is_active = is_active
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] toggle_batch_status 失败: {e}")
        return False
    finally:
        session.close()


def delete_batch(batch_id: int) -> bool:
    """删除批次及其所有礼包码和日志"""
    session = SessionLocal()
    try:
        session.query(GiftClaimLog).filter_by(batch_id=batch_id).delete()
        session.query(GiftCode).filter_by(batch_id=batch_id).delete()
        session.query(GiftCodeBatch).filter_by(id=batch_id).delete()
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] delete_batch 失败: {e}")
        return False
    finally:
        session.close()

# ========== 消息模板系统 ==========

def _msg(key: str, bot_id: str = None, **kwargs) -> str:
    """
    从数据库实时读取消息模板，若不存在则使用默认值
    用法: _msg("claim_success", bot_id, batch_name="BUG", code_value="ABC123")
    """
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        record = session.query(BotMessage).filter_by(
            message_key=key, bot_id=bot_id
        ).first()
        text = record.message_text if record else None
    finally:
        session.close()

    if text is None:
        default = DEFAULT_BOT_MESSAGES.get(key, {})
        text = default.get("text", key)
    return text.format(**kwargs)


def init_bot_messages():
    """初始化默认消息模板（启动时调用），已存在的消息不会覆盖"""
    session = SessionLocal()
    try:
        for key, info in DEFAULT_BOT_MESSAGES.items():
            exists = session.query(BotMessage).filter_by(
                message_key=key, bot_id=DEFAULT_BOT_ID
            ).first()
            if not exists:
                session.add(BotMessage(
                    message_key=key,
                    bot_id=DEFAULT_BOT_ID,
                    message_text=info["text"],
                    description=info["description"],
                ))
        session.commit()
        print("[DB] 消息模板初始化完成")
    except Exception as e:
        session.rollback()
        print(f"[DB] init_bot_messages 失败: {e}")
    finally:
        session.close()


def get_message_text(bot_id: str, key: str, **kwargs) -> str:
    """
    获取消息模板文本并渲染变量。
    优先从 DB 读取自定义模板，不存在时使用 DEFAULT_BOT_MESSAGES 兜底。
    """
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        msg = session.query(BotMessage).filter_by(
            bot_id=bot_id, message_key=key
        ).first()
        if msg:
            template = msg.message_text
        else:
            default = DEFAULT_BOT_MESSAGES.get(key)
            template = default["text"] if default else ""
        return template.format(**kwargs) if template else ""
    except KeyError as e:
        print(f"[get_message_text] 缺少变量 {e}，key={key}, kwargs={kwargs}")
        return template
    except Exception as e:
        print(f"[get_message_text] 异常 key={key}: {e}")
        return str(kwargs.get("description", ""))
    finally:
        session.close()


def get_all_bot_messages(bot_id: str = None) -> list[dict]:
    """获取所有消息模板（含默认值补齐）"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        db_msgs = {
            m.message_key: m
            for m in session.query(BotMessage).filter_by(bot_id=bot_id).all()
        }
        result = []
        for key, info in DEFAULT_BOT_MESSAGES.items():
            db_m = db_msgs.get(key)
            meta = BOT_MESSAGE_META.get(key, {})
            result.append({
                "message_key": key,
                "message_text": db_m.message_text if db_m else info["text"],
                "description": info["description"],
                "variables": info["variables"],
                "display_name": meta.get("display_name", key),
                "variable_descriptions": meta.get("variable_descriptions", {}),
                "is_customized": db_m is not None,
            })
        return result
    finally:
        session.close()


def update_bot_message(bot_id: str, key: str, text: str) -> bool:
    """创建或更新一条消息模板"""
    session = SessionLocal()
    try:
        msg = session.query(BotMessage).filter_by(
            message_key=key, bot_id=bot_id
        ).first()
        if msg:
            msg.message_text = text
            msg.updated_at = datetime.datetime.utcnow()
        else:
            default_info = DEFAULT_BOT_MESSAGES.get(key, {})
            session.add(BotMessage(
                message_key=key,
                bot_id=bot_id,
                message_text=text,
                description=default_info.get("description", ""),
            ))
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] update_bot_message 失败: {e}")
        return False
    finally:
        session.close()


def reset_bot_message(bot_id: str, key: str) -> str | None:
    """重置某条消息为默认值，返回默认文本"""
    default = DEFAULT_BOT_MESSAGES.get(key, {})
    default_text = default.get("text", "")

    session = SessionLocal()
    try:
        msg = session.query(BotMessage).filter_by(
            message_key=key, bot_id=bot_id
        ).first()
        if msg:
            msg.message_text = default_text
            msg.updated_at = datetime.datetime.utcnow()
            session.commit()
        return default_text
    except Exception as e:
        session.rollback()
        print(f"[DB] reset_bot_message 失败: {e}")
        return None
    finally:
        session.close()


# ========== 成员缓存 CRUD ==========

def upsert_member(bot_id: str, guild_id: str, user_id: str,
                  username: str = "", nickname: str = "", avatar_url: str = "") -> bool:
    """插入或更新成员缓存"""
    display_name = nickname if nickname else username
    session = SessionLocal()
    try:
        record = session.query(MemberCache).filter_by(
            bot_id=bot_id, guild_id=guild_id, user_id=user_id
        ).first()
        if record:
            record.username = username
            record.nickname = nickname
            record.display_name = display_name
            record.avatar_url = avatar_url
            record.updated_at = datetime.datetime.utcnow()
        else:
            session.add(MemberCache(
                bot_id=bot_id, guild_id=guild_id, user_id=user_id,
                username=username, nickname=nickname,
                display_name=display_name, avatar_url=avatar_url,
            ))
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] upsert_member 失败: {e}")
        return False
    finally:
        session.close()


def bulk_upsert_members(bot_id: str, guild_id: str, members: list[dict]) -> int:
    """批量插入/更新成员缓存，一次事务完成，避免逐个提交带来的锁竞争与卡顿。

    members: [{"user_id": str, "username": str, "nickname": str, "avatar_url": str}, ...]
    返回成功写入/更新的条数。
    """
    if not members:
        return 0
    session = SessionLocal()
    try:
        # 一次性查出现有记录，减少查询次数
        existing = {
            r.user_id: r
            for r in session.query(MemberCache).filter_by(
                bot_id=bot_id, guild_id=guild_id
            ).all()
        }
        now = datetime.datetime.utcnow()
        to_add = []
        for m in members:
            uid = str(m.get("user_id", ""))
            if not uid:
                continue
            username = m.get("username", "") or ""
            nickname = m.get("nickname", "") or ""
            display_name = nickname if nickname else username
            avatar_url = m.get("avatar_url", "") or ""
            rec = existing.get(uid)
            if rec:
                rec.username = username
                rec.nickname = nickname
                rec.display_name = display_name
                rec.avatar_url = avatar_url
                rec.updated_at = now
            else:
                to_add.append(MemberCache(
                    bot_id=bot_id, guild_id=guild_id, user_id=uid,
                    username=username, nickname=nickname,
                    display_name=display_name, avatar_url=avatar_url,
                ))
        session.add_all(to_add)
        session.commit()
        return len(existing) + len(to_add)
    except Exception as e:
        session.rollback()
        print(f"[DB] bulk_upsert_members 失败: {e}")
        return 0
    finally:
        session.close()


def get_members(bot_id: str, guild_id: str) -> list[dict]:
    """获取某服务器所有成员"""
    session = SessionLocal()
    try:
        records = session.query(MemberCache).filter_by(
            bot_id=bot_id, guild_id=guild_id
        ).order_by(MemberCache.display_name).all()
        return [
            {
                "user_id": r.user_id,
                "username": r.username,
                "nickname": r.nickname,
                "display_name": r.display_name,
                "avatar_url": r.avatar_url,
            }
            for r in records
        ]
    finally:
        session.close()


def search_members(bot_id: str, guild_id: str, query: str, limit: int = 20) -> list[dict]:
    """模糊搜索成员名"""
    session = SessionLocal()
    try:
        like = f"%{query}%"
        records = session.query(MemberCache).filter(
            MemberCache.bot_id == bot_id,
            MemberCache.guild_id == guild_id,
            MemberCache.display_name.like(like)
        ).order_by(MemberCache.display_name).limit(limit).all()
        return [
            {
                "user_id": r.user_id,
                "username": r.username,
                "nickname": r.nickname,
                "display_name": r.display_name,
                "avatar_url": r.avatar_url,
            }
            for r in records
        ]
    finally:
        session.close()


def clear_guild_members(bot_id: str, guild_id: str) -> bool:
    """清除某服务器所有成员缓存（重新同步前使用）"""
    session = SessionLocal()
    try:
        session.query(MemberCache).filter_by(
            bot_id=bot_id, guild_id=guild_id
        ).delete()
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] clear_guild_members 失败: {e}")
        return False
    finally:
        session.close()


# ========== 消息任务 CRUD ==========

def create_message_task(
    bot_id: str, guild_id: str, channel_id: str,
    target_type: str = TARGET_CHANNEL,
    content: str = "", task_name: str = "",
    thread_id: str = "", thread_name: str = "",
    schedule_type: str = SCHEDULE_IMMEDIATE,
    scheduled_at: datetime.datetime = None,
    created_by: str = "",
    status: str = STATUS_PENDING,
) -> int | None:
    """创建消息任务，返回 task_id"""
    session = SessionLocal()
    try:
        task = MessageTask(
            bot_id=bot_id, guild_id=guild_id, channel_id=channel_id,
            target_type=target_type, content=content, task_name=task_name,
            thread_id=thread_id, thread_name=thread_name,
            schedule_type=schedule_type, scheduled_at=scheduled_at,
            status=status, created_by=created_by,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.id
    except Exception as e:
        session.rollback()
        print(f"[DB] create_message_task 失败: {e}")
        return None
    finally:
        session.close()


def add_attachment(task_id: int, filename: str, file_data: bytes,
                   content_type: str = "", file_size: int = 0) -> bool:
    """为任务添加附件"""
    session = SessionLocal()
    try:
        session.add(MessageAttachment(
            task_id=task_id, filename=filename, file_data=file_data,
            content_type=content_type, file_size=file_size,
        ))
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] add_attachment 失败: {e}")
        return False
    finally:
        session.close()


def get_attachments(task_id: int) -> list[dict]:
    """获取任务的所有附件（不含二进制数据）"""
    session = SessionLocal()
    try:
        records = session.query(MessageAttachment).filter_by(task_id=task_id).all()
        return [
            {"id": r.id, "filename": r.filename,
             "content_type": r.content_type, "file_size": r.file_size}
            for r in records
        ]
    finally:
        session.close()


def get_attachment_data(attachment_id: int) -> bytes | None:
    """获取附件二进制数据"""
    session = SessionLocal()
    try:
        record = session.query(MessageAttachment).filter_by(id=attachment_id).first()
        return record.file_data if record else None
    finally:
        session.close()


def delete_attachment(attachment_id: int) -> bool:
    """删除单个附件"""
    session = SessionLocal()
    try:
        session.query(MessageAttachment).filter_by(id=attachment_id).delete()
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] delete_attachment 失败: {e}")
        return False
    finally:
        session.close()


def get_pending_tasks(bot_id: str, now: datetime.datetime = None) -> list[dict]:
    """
    Bot 轮询接口：获取待发送的消息任务
    条件：status=pending 且 (schedule_type=immediate 或 scheduled_at <= now)
    """
    if now is None:
        now = datetime.datetime.utcnow()

    session = SessionLocal()
    try:
        tasks = session.query(MessageTask).filter(
            MessageTask.bot_id == bot_id,
            MessageTask.status == STATUS_PENDING,
        ).filter(
            (MessageTask.schedule_type == SCHEDULE_IMMEDIATE) |
            ((MessageTask.schedule_type == SCHEDULE_TIMED) &
             (MessageTask.scheduled_at <= now))
        ).order_by(MessageTask.created_at).all()

        result = []
        for t in tasks:
            attachments = session.query(MessageAttachment).filter_by(task_id=t.id).all()
            result.append({
                "id": t.id, "bot_id": t.bot_id, "task_name": t.task_name,
                "guild_id": t.guild_id, "channel_id": t.channel_id,
                "thread_id": t.thread_id, "thread_name": t.thread_name,
                "target_type": t.target_type, "content": t.content,
                "embed_json": t.embed_json,
                "schedule_type": t.schedule_type, "scheduled_at": t.scheduled_at,
                "status": t.status, "created_by": t.created_by,
                "created_at": t.created_at,
                "attachments": [
                    {"id": a.id, "filename": a.filename,
                     "content_type": a.content_type, "file_size": a.file_size}
                    for a in attachments
                ],
            })
        return result
    finally:
        session.close()


def claim_pending_task(task_id: int) -> bool:
    """原子领取待发送任务：将 status 从 pending 置为 processing。

    通过 `UPDATE ... WHERE status=pending` 保证多实例/多进程并发时，
    只有一个进程能成功领取（rowcount==1），从而避免消息重复发送。
    返回 True 表示领取成功，False 表示任务已被他人处理或不存在。
    """
    from sqlalchemy import text
    session = SessionLocal()
    try:
        result = session.execute(
            text(
                "UPDATE message_tasks SET status=:p "
                "WHERE id=:tid AND status=:pending"
            ),
            {"p": STATUS_PROCESSING, "tid": task_id, "pending": STATUS_PENDING},
        )
        session.commit()
        return result.rowcount == 1
    except Exception as e:
        session.rollback()
        print(f"[DB] claim_pending_task 失败: {e}")
        return False
    finally:
        session.close()


def update_task_status(task_id: int, status: str, result_msg: str = "") -> bool:
    """更新任务状态（sent / failed）"""
    session = SessionLocal()
    try:
        task = session.query(MessageTask).filter_by(id=task_id).first()
        if not task:
            return False
        task.status = status
        task.result_msg = result_msg
        if status == STATUS_SENT:
            task.sent_at = datetime.datetime.utcnow()
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] update_task_status 失败: {e}")
        return False
    finally:
        session.close()


def get_task_history(bot_id: str, limit: int = 50,
                     guild_id: str = None, status: str = None) -> list[dict]:
    """获取任务发送历史"""
    session = SessionLocal()
    try:
        query = session.query(MessageTask).filter_by(bot_id=bot_id)
        if guild_id:
            query = query.filter_by(guild_id=guild_id)
        if status:
            query = query.filter_by(status=status)
        tasks = query.order_by(MessageTask.created_at.desc()).limit(limit).all()

        return [
            {
                "id": t.id, "task_name": t.task_name,
                "guild_id": t.guild_id, "channel_id": t.channel_id,
                "thread_id": t.thread_id, "thread_name": t.thread_name,
                "target_type": t.target_type,
                "content": (t.content or "")[:200],
                "schedule_type": t.schedule_type,
                "scheduled_at": _fmt_bj(t.scheduled_at, "%Y-%m-%d %H:%M"),
                "status": t.status, "result_msg": t.result_msg or "",
                "sent_at": _fmt_bj(t.sent_at),
                "created_at": _fmt_bj(t.created_at, "%Y-%m-%d %H:%M"),
            }
            for t in tasks
        ]
    finally:
        session.close()


def get_task_history_paginated(
    bot_id: str,
    guild_id: str = None,
    search: str = "",
    page: int = 1,
    per_page: int = 10,
) -> tuple[list[dict], int]:
    """获取任务发送历史（带分页和搜索）"""
    session = SessionLocal()
    try:
        query = session.query(MessageTask).filter_by(bot_id=bot_id)
        if guild_id:
            query = query.filter_by(guild_id=guild_id)

        # 关键词搜索：任务名 / 内容 / 结果
        if search:
            like_str = f"%{search}%"
            from sqlalchemy import or_
            query = query.filter(or_(
                MessageTask.task_name.ilike(like_str),
                MessageTask.content.ilike(like_str),
                MessageTask.result_msg.ilike(like_str),
            ))

        total = query.count()
        offset = (page - 1) * per_page
        tasks = query.order_by(MessageTask.created_at.desc()).offset(offset).limit(per_page).all()

        result = [
            {
                "id": t.id, "task_name": t.task_name,
                "guild_id": t.guild_id, "channel_id": t.channel_id,
                "thread_id": t.thread_id, "thread_name": t.thread_name,
                "target_type": t.target_type,
                "content": (t.content or "")[:200],
                "schedule_type": t.schedule_type,
                "scheduled_at": _fmt_bj(t.scheduled_at, "%Y-%m-%d %H:%M"),
                "status": t.status, "result_msg": t.result_msg or "",
                "sent_at": _fmt_bj(t.sent_at),
                "created_at": _fmt_bj(t.created_at, "%Y-%m-%d %H:%M"),
            }
            for t in tasks
        ]
        return result, total
    finally:
        session.close()


def delete_message_task(task_id: int) -> bool:
    """删除任务及其附件"""
    session = SessionLocal()
    try:
        session.query(MessageAttachment).filter_by(task_id=task_id).delete()
        session.query(MessageTask).filter_by(id=task_id).delete()
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] delete_message_task 失败: {e}")
        return False
    finally:
        session.close()


# ========== 频道查询扩展（所有类型） ==========

def get_channels_all_types(bot_id: str, guild_id: str | None = None) -> dict:
    """
    获取某服务器下所有频道，按类型分组
    guild_id=None 时不过滤服务器，返回所有服务器的频道
    返回: {
        "text": [{channel_id, channel_name, guild_id}, ...],
        "forum": [...],
        "threads": [{channel_id, channel_name, thread_id, parent_name}, ...]
    }
    """
    session = SessionLocal()
    try:
        query = session.query(ChannelCache).filter(
            ChannelCache.bot_id == bot_id,
            ChannelCache.is_available == True,
        )
        if guild_id is not None:
            query = query.filter(ChannelCache.guild_id == guild_id)
        all_channels = query.order_by(ChannelCache.channel_name).all()

        result = {"text": [], "forum": [], "threads": []}
        for c in all_channels:
            item = {"channel_id": c.channel_id, "channel_name": c.channel_name, "guild_id": c.guild_id}
            if c.channel_type == "forum":
                result["forum"].append(item)
            elif c.channel_type == "thread":
                item["parent_channel_id"] = c.parent_channel_id or ""
                result["threads"].append(item)
            else:
                result["text"].append(item)
        return result
    finally:
        session.close()


# ========== 传统抽奖 CRUD ==========

_raffle_lock = threading.Lock()


def create_raffle(
    bot_id: str, guild_id: str, channel_id: str, title: str,
    description: str = "", winner_count: int = 1,
    draw_time: datetime.datetime | str = None, creator_id: str = "",
) -> dict:
    """创建传统抽奖，返回 {success, raffle_id, message}"""
    session = SessionLocal()
    try:
        raffle = Raffle(
            bot_id=bot_id, guild_id=guild_id,
            channel_id=channel_id,
            announce_channel_id=channel_id,
            creator_id=creator_id,
            title=title, description=description,
            winner_count=winner_count,
            draw_time=parse_datetime_to_utc(draw_time),
        )
        session.add(raffle)
        session.commit()
        session.refresh(raffle)
        return {"success": True, "raffle_id": raffle.id, "message": "抽奖创建成功"}
    except Exception as e:
        session.rollback()
        return {"success": False, "raffle_id": 0, "message": f"创建失败: {e}"}
    finally:
        session.close()


def set_raffle_message_id(raffle_id: int, channel_id: str, message_id: str) -> bool:
    """抽奖公告发送后，记录消息 ID"""
    session = SessionLocal()
    try:
        raffle = session.query(Raffle).filter_by(id=raffle_id).first()
        if not raffle:
            return False
        raffle.channel_id = channel_id
        raffle.message_id = message_id
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] set_raffle_message_id 失败: {e}")
        return False
    finally:
        session.close()


def join_raffle(raffle_id: int, user_id: str, user_name: str) -> dict:
    """参与抽奖，返回 {success, message, already_joined}"""
    with _raffle_lock:
        session = SessionLocal()
        try:
            raffle = session.query(Raffle).filter_by(id=raffle_id).first()
            if not raffle:
                return {"success": False, "already_joined": False, "message": "抽奖不存在"}
            if not raffle.is_active:
                return {"success": False, "already_joined": False, "message": "该抽奖已结束"}
            if raffle.is_drawn:
                return {"success": False, "already_joined": False, "message": "该抽奖已经开奖"}

            exists = session.query(RaffleParticipant).filter_by(
                raffle_id=raffle_id, user_id=user_id
            ).first()
            if exists:
                return {"success": False, "already_joined": True, "message": "你已经参与过了"}

            session.add(RaffleParticipant(
                raffle_id=raffle_id, user_id=user_id, user_name=user_name,
            ))
            session.commit()
            count = session.query(RaffleParticipant).filter_by(raffle_id=raffle_id).count()
            return {"success": True, "already_joined": False, "message": "报名成功！", "count": count}
        except Exception as e:
            session.rollback()
            return {"success": False, "already_joined": False, "message": f"参与失败: {e}"}
        finally:
            session.close()


def draw_raffle_winners(raffle_id: int) -> dict:
    """开奖：随机选出 winner_count 个参与者，返回 {success, winners, message}"""
    with _raffle_lock:
        session = SessionLocal()
        try:
            raffle = session.query(Raffle).filter_by(id=raffle_id).first()
            if not raffle:
                return {"success": False, "winners": [], "message": "抽奖不存在"}
            if raffle.is_drawn:
                return {"success": False, "winners": [], "message": "该抽奖已经开奖"}

            participants = session.query(RaffleParticipant).filter_by(
                raffle_id=raffle_id
            ).all()
            if len(participants) == 0:
                return {"success": False, "winners": [], "message": "无人参与"}

            count = min(raffle.winner_count, len(participants))
            chosen = random.sample(participants, count)
            chosen_ids = {p.id for p in chosen}

            for p in participants:
                p.is_winner = p.id in chosen_ids

            raffle.is_drawn = True
            raffle.drawn_at = now_utc()
            raffle.is_active = False
            session.commit()

            winners = [
                {"user_id": p.user_id, "user_name": p.user_name}
                for p in chosen
            ]
            return {"success": True, "winners": winners, "message": "开奖完成"}
        except Exception as e:
            session.rollback()
            return {"success": False, "winners": [], "message": f"开奖失败: {e}"}
        finally:
            session.close()


def get_raffle(raffle_id: int) -> dict | None:
    """获取单个抽奖详情"""
    session = SessionLocal()
    try:
        r = session.query(Raffle).filter_by(id=raffle_id).first()
        if not r:
            return None
        participants = session.query(RaffleParticipant).filter_by(raffle_id=raffle_id).all()
        winner_ids = {p.user_id for p in participants if p.is_winner}
        return {
            "id": r.id, "bot_id": r.bot_id, "guild_id": r.guild_id,
            "channel_id": r.channel_id, "message_id": r.message_id,
            "announce_channel_id": r.announce_channel_id,
            "creator_id": r.creator_id,
            "title": r.title, "description": r.description or "",
            "winner_count": r.winner_count,
            "draw_time": _fmt_bj(r.draw_time, "%Y-%m-%d %H:%M"),
            "is_active": r.is_active, "is_drawn": r.is_drawn,
            "drawn_at": _fmt_bj(r.drawn_at),
            "created_at": _fmt_bj(r.created_at),
            "participant_count": len(participants),
            "winner_ids": list(winner_ids),
        }
    finally:
        session.close()


def get_raffle_manage_list(bot_id: str, guild_id: str | None = None) -> list[dict]:
    """管理员用：获取所有抽奖（含已结束）。guild_id=None 时不过滤服务器"""
    session = SessionLocal()
    try:
        query = session.query(Raffle).filter(Raffle.bot_id == bot_id)
        if guild_id is not None:
            query = query.filter(Raffle.guild_id == guild_id)
        raffles = query.order_by(Raffle.created_at.desc()).all()
        result = []
        for r in raffles:
            count = session.query(RaffleParticipant).filter_by(raffle_id=r.id).count()
            winner_count = session.query(RaffleParticipant).filter_by(
                raffle_id=r.id, is_winner=True
            ).count()
            result.append({
                "id": r.id, "title": r.title, "description": r.description or "",
                "winner_count": r.winner_count,
                "draw_time": _fmt_bj(r.draw_time, "%Y-%m-%d %H:%M"),
                "channel_id": r.channel_id, "message_id": r.message_id,
                "announce_channel_id": r.announce_channel_id,
                "is_active": r.is_active, "is_drawn": r.is_drawn,
                "drawn_at": _fmt_bj(r.drawn_at),
                "participant_count": count,
                "actual_winners": winner_count,
                "created_at": _fmt_bj(r.created_at),
            })
        return result
    finally:
        session.close()


def get_raffle_participants(raffle_id: int) -> list[dict]:
    """获取参与者列表"""
    session = SessionLocal()
    try:
        records = session.query(RaffleParticipant).filter_by(
            raffle_id=raffle_id
        ).order_by(RaffleParticipant.joined_at).all()
        return [
            {
                "user_id": p.user_id, "user_name": p.user_name,
                "is_winner": p.is_winner,
                "joined_at": _fmt_bj(p.joined_at),
            }
            for p in records
        ]
    finally:
        session.close()


def cancel_raffle(raffle_id: int) -> bool:
    """取消抽奖"""
    session = SessionLocal()
    try:
        raffle = session.query(Raffle).filter_by(id=raffle_id).first()
        if not raffle:
            return False
        raffle.is_active = False
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] cancel_raffle 失败: {e}")
        return False
    finally:
        session.close()


def delete_raffle(raffle_id: int) -> bool:
    """硬删除抽奖（含参与记录）"""
    session = SessionLocal()
    try:
        session.query(RaffleParticipant).filter_by(raffle_id=raffle_id).delete()
        session.query(Raffle).filter_by(id=raffle_id).delete()
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] delete_raffle 失败: {e}")
        return False
    finally:
        session.close()


def delete_lottery(lottery_id: int) -> bool:
    """硬删除即开番赏（含奖品 & 槽位 & 抽取记录）"""
    session = SessionLocal()
    try:
        session.query(LotteryDrawRecord).filter_by(lottery_id=lottery_id).delete()
        session.query(LotteryPoolSlot).filter_by(lottery_id=lottery_id).delete()
        session.query(LotteryPrize).filter_by(lottery_id=lottery_id).delete()
        session.query(InstantLottery).filter_by(id=lottery_id).delete()
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] delete_lottery 失败: {e}")
        return False
    finally:
        session.close()


def get_pending_draw_raffles(now: datetime.datetime = None) -> list[dict]:
    """Bot 轮询：获取到达开奖时间但未开奖的抽奖"""
    if now is None:
        # SQLite 读出的 DateTime 无时区，使用 naive UTC 比较
        now = now_utc().replace(tzinfo=None)
    session = SessionLocal()
    try:
        raffles = session.query(Raffle).filter(
            Raffle.is_active == True,
            Raffle.is_drawn == False,
            Raffle.draw_time.isnot(None),
            Raffle.draw_time <= now,
            Raffle.message_id.isnot(None),
        ).all()
        return [
            {
                "id": r.id, "bot_id": r.bot_id, "guild_id": r.guild_id,
                "title": r.title, "winner_count": r.winner_count,
                "channel_id": r.channel_id, "message_id": r.message_id,
                "announce_channel_id": r.announce_channel_id,
            }
            for r in raffles
        ]
    finally:
        session.close()


def get_all_active_raffle_messages() -> list[dict]:
    """Bot 启动恢复：获取所有活跃抽奖的 message_id"""
    session = SessionLocal()
    try:
        raffles = session.query(Raffle).filter(
            Raffle.is_active == True,
            Raffle.is_drawn == False,
            Raffle.message_id.isnot(None),
        ).all()
        return [
            {"id": r.id, "message_id": r.message_id, "bot_id": r.bot_id, "draw_time": r.draw_time}
            for r in raffles
        ]
    finally:
        session.close()


# ========== 即开型抽奖（一番赏）CRUD ==========

_lottery_lock = threading.Lock()


def create_instant_lottery(
    bot_id: str, guild_id: str, channel_id: str, title: str,
    description: str = "", start_time: datetime.datetime | str = None,
    end_time: datetime.datetime | str = None, creator_id: str = "",
    prizes: list[dict] = None,
    total_slots: int = 100, max_draws_per_user: int = 3,
) -> dict:
    """
    创建即开型抽奖（固定奖池模式）。
    生成 shuffled 槽位数组并写入 lottery_pool_slots。
    prizes: [{tier_label, prize_name, prize_desc, emoji, count}, ...]
    """
    start_time = parse_datetime_to_utc(start_time) or now_utc()
    end_time = parse_datetime_to_utc(end_time) or (start_time + datetime.timedelta(hours=24))

    session = SessionLocal()
    try:
        lottery = InstantLottery(
            bot_id=bot_id, guild_id=guild_id, channel_id=channel_id,
            creator_id=creator_id, title=title, description=description or "",
            start_time=start_time, end_time=end_time,
            total_slots=total_slots, max_draws_per_user=max_draws_per_user,
        )
        session.add(lottery)
        session.flush()

        # 1) 写入奖品配置
        prize_rows = []
        if prizes:
            for idx, p in enumerate(prizes):
                row = LotteryPrize(
                    lottery_id=lottery.id,
                    tier_label=p.get("tier_label", ""),
                    prize_name=p.get("prize_name", ""),
                    prize_desc=p.get("prize_desc", ""),
                    emoji=p.get("emoji", "🎁"),
                    total_count=p.get("count", 1),
                    remaining=p.get("count", 1),  # 保留兼容旧字段
                    sort_order=idx,
                )
                session.add(row)
                session.flush()
                prize_rows.append(row)

        # 2) 生成打乱的槽位数组
        slot_list = []
        for prize in prize_rows:
            for _ in range(prize.total_count):
                slot_list.append({
                    "prize_id": prize.id,
                    "tier_label": prize.tier_label,
                    "prize_name": prize.prize_name,
                    "emoji": prize.emoji or "🎁",
                })

        # 谢谢参与（NULL prize_id）
        null_count = total_slots - len(slot_list)
        if null_count > 0:
            for _ in range(null_count):
                slot_list.append({
                    "prize_id": None,
                    "tier_label": "谢谢参与",
                    "prize_name": "无",
                    "emoji": "😔",
                })

        random.shuffle(slot_list)

        # 3) 批量 INSERT 槽位
        for s in slot_list:
            session.add(LotteryPoolSlot(
                lottery_id=lottery.id,
                prize_id=s["prize_id"],
                tier_label=s["tier_label"],
                prize_name=s["prize_name"],
                emoji=s["emoji"],
            ))

        session.commit()
        session.refresh(lottery)
        return {"success": True, "lottery_id": lottery.id, "message": "抽奖创建成功"}
    except Exception as e:
        session.rollback()
        return {"success": False, "lottery_id": 0, "message": f"创建失败: {e}"}
    finally:
        session.close()


def set_lottery_message_id(lottery_id: int, channel_id: str, message_id: str) -> bool:
    """公告发送后记录消息 ID"""
    session = SessionLocal()
    try:
        lottery = session.query(InstantLottery).filter_by(id=lottery_id).first()
        if not lottery:
            return False
        lottery.channel_id = channel_id
        lottery.message_id = message_id
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] set_lottery_message_id 失败: {e}")
        return False
    finally:
        session.close()


def draw_instant(lottery_id: int, user_id: str, user_name: str) -> dict:
    """
    即开型抽奖（固定池模式）：按 shuffle 顺序抽取下一个槽位。
    返回: {success, prize_id, tier_label, prize_name, emoji, message, closed,
           slots_left, slots_total, my_count, max_draws, blocked}
    """
    with _lottery_lock:
        session = SessionLocal()
        try:
            lottery = session.query(InstantLottery).filter_by(id=lottery_id).first()
            if not lottery:
                return {"success": False, "message": "抽奖不存在", "closed": False}
            if not lottery.is_active:
                return {"success": False, "message": "该抽奖已结束", "closed": True}

            # 检查用户抽取次数
            my_count = session.query(LotteryPoolSlot).filter(
                LotteryPoolSlot.lottery_id == lottery_id,
                LotteryPoolSlot.is_drawn == True,
                LotteryPoolSlot.drawn_by_user_id == user_id,
            ).count()
            if my_count >= lottery.max_draws_per_user:
                return {
                    "success": False, "message": "已达抽取上限",
                    "closed": False, "blocked": True,
                    "my_count": my_count, "max_draws": lottery.max_draws_per_user,
                }

            # 取下一个未抽槽位
            slot = session.query(LotteryPoolSlot).filter(
                LotteryPoolSlot.lottery_id == lottery_id,
                LotteryPoolSlot.is_drawn == False,
            ).order_by(LotteryPoolSlot.id).first()

            if not slot:
                lottery.is_active = False
                session.commit()
                return {"success": False, "message": "所有槽位已被抽取完毕", "closed": True}

            # 标记已抽
            slot.is_drawn = True
            slot.drawn_by_user_id = user_id
            slot.drawn_by_user_name = user_name
            slot.drawn_at = datetime.datetime.utcnow()

            lottery.slots_drawn += 1
            my_count += 1

            # 同步写 LotteryDrawRecord（仅真实奖品）
            if slot.prize_id is not None:
                session.add(LotteryDrawRecord(
                    lottery_id=lottery_id, prize_id=slot.prize_id,
                    user_id=user_id, user_name=user_name,
                ))
                # 同步扣减 LotteryPrize.remaining
                prize = session.query(LotteryPrize).filter_by(id=slot.prize_id).first()
                if prize:
                    prize.remaining -= 1

            closed = lottery.slots_drawn >= lottery.total_slots
            if closed:
                lottery.is_active = False

            session.commit()

            result_msg = (
                f"🎉 抽中 {slot.emoji} **{slot.tier_label} — {slot.prize_name}**！"
                if slot.prize_id else
                f"{slot.emoji} 谢谢参与，再接再厉！"
            )

            return {
                "success": True,
                "prize_id": slot.prize_id,
                "tier_label": slot.tier_label,
                "prize_name": slot.prize_name,
                "emoji": slot.emoji,
                "message": result_msg,
                "closed": closed,
                "slots_left": lottery.total_slots - lottery.slots_drawn,
                "slots_total": lottery.total_slots,
                "my_count": my_count,
                "max_draws": lottery.max_draws_per_user,
                "blocked": False,
            }
        except Exception as e:
            session.rollback()
            return {"success": False, "message": f"抽取失败: {e}", "closed": False}
        finally:
            session.close()


def get_lottery_status(lottery_id: int) -> dict | None:
    """获取即开型抽奖当前状态（奖池已抽槽位 + 奖品信息 + 最近中奖者）"""
    session = SessionLocal()
    try:
        lot = session.query(InstantLottery).filter_by(id=lottery_id).first()
        if not lot:
            return None

        prizes_raw = session.query(LotteryPrize).filter_by(
            lottery_id=lottery_id
        ).order_by(LotteryPrize.sort_order).all()

        # 统计每种奖品的已抽/总数（从槽位表）
        drawn_slots = session.query(LotteryPoolSlot).filter(
            LotteryPoolSlot.lottery_id == lottery_id,
            LotteryPoolSlot.is_drawn == True,
        ).order_by(LotteryPoolSlot.drawn_at.desc()).all()

        now = now_utc().replace(tzinfo=None)
        is_expired = lot.end_time is not None and now > lot.end_time

        # 最近 10 条抽取记录
        recent = []
        for s in drawn_slots[:10]:
            recent.append({
                "user_name": s.drawn_by_user_name or "?",
                "tier_label": s.tier_label,
                "prize_name": s.prize_name,
                "emoji": s.emoji,
                "is_hit": s.prize_id is not None,
            })

        # 奖池统计
        all_slots = session.query(LotteryPoolSlot).filter_by(lottery_id=lottery_id).count()
        drawn_count = len(drawn_slots)
        hit_count = session.query(LotteryPoolSlot).filter(
            LotteryPoolSlot.lottery_id == lottery_id,
            LotteryPoolSlot.is_drawn == True,
            LotteryPoolSlot.prize_id.isnot(None),
        ).count()

        return {
            "id": lot.id, "bot_id": lot.bot_id, "guild_id": lot.guild_id,
            "channel_id": lot.channel_id, "message_id": lot.message_id,
            "title": lot.title, "description": lot.description or "",
            "start_time": _fmt_bj(lot.start_time, "%Y-%m-%d %H:%M"),
            "end_time": _fmt_bj(lot.end_time, "%Y-%m-%d %H:%M"),
            "total_slots": lot.total_slots, "slots_drawn": lot.slots_drawn,
            "slots_left": lot.total_slots - lot.slots_drawn,
            "max_draws_per_user": lot.max_draws_per_user,
            "is_active": lot.is_active and not is_expired,
            "created_at": _fmt_bj(lot.created_at),
            "all_slots": all_slots,
            "drawn_count": drawn_count,
            "hit_count": hit_count,
            "prizes": [
                {
                    "id": p.id, "tier_label": p.tier_label,
                    "prize_name": p.prize_name, "prize_desc": p.prize_desc or "",
                    "emoji": p.emoji or "🎁",
                    "total_count": p.total_count, "remaining": p.remaining,
                    "sort_order": p.sort_order,
                }
                for p in prizes_raw
            ],
            "recent_draws": recent,
        }
    finally:
        session.close()


def get_lottery_manage_list(bot_id: str, guild_id: str | None = None) -> list[dict]:
    """管理员用：获取所有即开型抽奖。guild_id=None 时不过滤服务器"""
    session = SessionLocal()
    try:
        query = session.query(InstantLottery).filter(InstantLottery.bot_id == bot_id)
        if guild_id is not None:
            query = query.filter(InstantLottery.guild_id == guild_id)
        lotteries = query.order_by(InstantLottery.created_at.desc()).all()
        result = []
        for l in lotteries:
            result.append({
                "id": l.id, "title": l.title, "description": l.description or "",
                "channel_id": l.channel_id, "message_id": l.message_id,
                "start_time": _fmt_bj(l.start_time, "%Y-%m-%d %H:%M"),
                "end_time": _fmt_bj(l.end_time, "%Y-%m-%d %H:%M"),
                "is_active": l.is_active,
                "total_slots": l.total_slots,
                "slots_drawn": l.slots_drawn,
                "slots_left": l.total_slots - l.slots_drawn,
                "max_draws_per_user": l.max_draws_per_user,
                "created_at": _fmt_bj(l.created_at),
            })
        return result
    finally:
        session.close()


def get_lottery_draw_records(lottery_id: int, limit: int = 100) -> list[dict]:
    """获取即开型抽奖的抽取记录"""
    session = SessionLocal()
    try:
        records = session.query(LotteryDrawRecord).filter_by(
            lottery_id=lottery_id
        ).order_by(LotteryDrawRecord.drawn_at.desc()).limit(limit).all()

        prize_map = {}
        prize_ids = {r.prize_id for r in records}
        if prize_ids:
            prizes = session.query(LotteryPrize).filter(
                LotteryPrize.id.in_(prize_ids)
            ).all()
            prize_map = {p.id: p for p in prizes}
        return [
            {
                "id": r.id, "user_id": r.user_id, "user_name": r.user_name,
                "prize_id": r.prize_id,
                "tier_label": prize_map[r.prize_id].tier_label if r.prize_id in prize_map else "",
                "prize_name": prize_map[r.prize_id].prize_name if r.prize_id in prize_map else "",
                "emoji": prize_map[r.prize_id].emoji if r.prize_id in prize_map else "🎁",
                "drawn_at": _fmt_bj(r.drawn_at),
            }
            for r in records
        ]
    finally:
        session.close()


def close_lottery(lottery_id: int) -> bool:
    """手动关闭即开型抽奖"""
    session = SessionLocal()
    try:
        lottery = session.query(InstantLottery).filter_by(id=lottery_id).first()
        if not lottery:
            return False
        lottery.is_active = False
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[DB] close_lottery 失败: {e}")
        return False
    finally:
        session.close()


def force_close_lottery(lottery_id: int) -> dict | None:
    """
    强制清空抽奖池（24h 超时）。
    返回未抽槽位信息 + 强制关闭结果。
    """
    with _lottery_lock:
        session = SessionLocal()
        try:
            lottery = session.query(InstantLottery).filter_by(id=lottery_id).first()
            if not lottery or not lottery.is_active:
                return None

            # 取出所有未抽槽位
            left_slots = session.query(LotteryPoolSlot).filter(
                LotteryPoolSlot.lottery_id == lottery_id,
                LotteryPoolSlot.is_drawn == False,
            ).order_by(LotteryPoolSlot.id).all()

            # 标记所有剩余为空（被强制关闭吞掉）
            for s in left_slots:
                s.is_drawn = True
            lottery.slots_drawn = lottery.total_slots
            lottery.is_active = False
            session.commit()

            return {
                "lottery_id": lottery_id,
                "title": lottery.title,
                "channel_id": lottery.channel_id,
                "message_id": lottery.message_id,
                "total_slots": lottery.total_slots,
                "left_count": len(left_slots),
                "left_slots": [
                    {"tier_label": s.tier_label, "prize_name": s.prize_name, "emoji": s.emoji}
                    for s in left_slots if s.prize_id is not None
                ],
            }
        except Exception as e:
            session.rollback()
            print(f"[DB] force_close_lottery 失败: {e}")
            return None
        finally:
            session.close()


def get_expired_lotteries(hours: float = 24.0) -> list[dict]:
    """
    获取创建超过 hours 小时仍未抽完的活跃抽奖。
    """
    session = SessionLocal()
    try:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        lotteries = session.query(InstantLottery).filter(
            InstantLottery.is_active == True,
            InstantLottery.slots_drawn < InstantLottery.total_slots,
            InstantLottery.created_at <= cutoff,
        ).all()
        return [
            {"id": l.id, "title": l.title, "channel_id": l.channel_id,
             "message_id": l.message_id, "total_slots": l.total_slots,
             "slots_drawn": l.slots_drawn,
             "slots_left": l.total_slots - l.slots_drawn,
             "created_at": l.created_at}
            for l in lotteries
        ]
    finally:
        session.close()


def get_all_active_lottery_messages() -> list[dict]:
    """Bot 启动恢复：获取所有活跃即开抽奖的 message_id"""
    session = SessionLocal()
    try:
        lotteries = session.query(InstantLottery).filter(
            InstantLottery.is_active == True,
            InstantLottery.message_id.isnot(None),
        ).all()
        return [
            {"id": l.id, "message_id": l.message_id, "bot_id": l.bot_id}
            for l in lotteries
        ]
    finally:
        session.close()


def get_unpublished_raffles(bot_id: str = None) -> list[dict]:
    """Bot 轮询：获取已创建但未发布公告的抽奖（message_id 为空）"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        raffles = session.query(Raffle).filter(
            Raffle.bot_id == bot_id,
            Raffle.is_active == True,
            Raffle.message_id.is_(None),
        ).all()
        return [
            {"id": r.id, "channel_id": r.channel_id, "title": r.title}
            for r in raffles
        ]
    finally:
        session.close()


def get_unpublished_lotteries(bot_id: str = None) -> list[dict]:
    """Bot 轮询：获取已创建但未发布公告的即开型抽奖"""
    bot_id = bot_id or DEFAULT_BOT_ID
    session = SessionLocal()
    try:
        lotteries = session.query(InstantLottery).filter(
            InstantLottery.bot_id == bot_id,
            InstantLottery.is_active == True,
            InstantLottery.message_id.is_(None),
        ).all()
        return [
            {"id": l.id, "channel_id": l.channel_id, "title": l.title}
            for l in lotteries
        ]
    finally:
        session.close()