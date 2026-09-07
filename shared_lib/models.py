import os
from pathlib import Path

# 获取项目根目录（假设 shared_lib 位于项目根目录下）
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
DB_PATH = PROJECT_ROOT / "shared_data.db"

from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, UniqueConstraint, Boolean, LargeBinary, Float, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

Base = declarative_base()

# 机器人注册表（预留多租户）
class Bot(Base):
    __tablename__ = 'bots'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), unique=True, nullable=False)  # 唯一标识
    bot_name = Column(String(100))
    owner_id = Column(String(50))  # 预留未来拥有者
    token_encrypted = Column(Text) # V1暂存明文，未来加密
    is_active = Column(Boolean, default=True)  # 是否启用
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen = Column(DateTime, nullable=True)   # 最近一次心跳时间（用于在线监控）
    last_latency_ms = Column(Integer, nullable=True)  # 最近一次上报的延迟(ms)
    last_error = Column(Text, nullable=True)       # 最近一次启动失败的原因（供后台展示）

# 服务器配置表（演示“按服务器隔离”）
class GuildConfig(Base):
    __tablename__ = 'guild_configs'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    config_key = Column(String(50), nullable=False)
    config_value = Column(Text)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

# 系统事件表（验证机器人和Web通信）
class SystemEvent(Base):
    __tablename__ = 'system_events'
    id = Column(Integer, primary_key=True)
    event_source = Column(String(20))  # 'bot' 或 'web'
    event_type = Column(String(50))
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

# --- 初始化数据库引擎（V1 直接用 SQLite）---
# 使用 WAL 模式 + busy_timeout，允许读写并发，避免「database is locked」
# 让后台卡顿；echo=False 关闭逐条 SQL 日志，降低开销。
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, connection_record):
    """连接时开启 WAL 与 busy_timeout，显著降低多进程/多线程并发锁冲突。"""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


# 机器人真实加入的服务器列表（同步自 Discord API）
class Guild(Base):
    __tablename__ = 'guilds'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    guild_name = Column(String(100))
    member_count = Column(Integer)
    icon_url = Column(String(200))
    joined_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    __table_args__ = (UniqueConstraint('bot_id', 'guild_id', name='uq_bot_guild'),)

# 频道缓存表
class ChannelCache(Base):
    __tablename__ = 'channel_cache'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    channel_id = Column(String(50), nullable=False)
    channel_name = Column(String(100))
    channel_type = Column(String(20))   # 'text', 'forum', 'thread'
    parent_channel_id = Column(String(50))  # 论坛帖子的父论坛 ID
    is_available = Column(Boolean, default=True)   # 机器人是否有权限
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    __table_args__ = (UniqueConstraint('bot_id', 'channel_id', name='uq_bot_channel'),)

# 陷阱配置表
class TrapConfig(Base):
    __tablename__ = 'trap_configs'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    trap_channel_id = Column(String(50), nullable=True)   # NULL 表示未设置
    is_enabled = Column(Boolean, default=False)
    whitelist_roles = Column(Text, default='')   # 逗号分隔的角色ID列表
    whitelist_users = Column(Text, default='')   # 逗号分隔的用户ID列表
    kick_message = Column(String(200), default='⚠️ 本频道禁止非授权成员发言')
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    __table_args__ = (UniqueConstraint('bot_id', 'guild_id', name='uq_bot_guild_trap'),)

# 踢人日志表
class TrapLog(Base):
    __tablename__ = 'trap_logs'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    channel_id = Column(String(50))
    user_id = Column(String(50))
    user_name = Column(String(100))
    kicked_at = Column(DateTime, default=datetime.datetime.utcnow)
    reason = Column(String(200))

# ========== 礼包码系统 ==========

# 礼包码批次表
class GiftCodeBatch(Base):
    __tablename__ = 'gift_code_batches'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    batch_name = Column(String(100), nullable=False)       # 批次名称（如"万圣节活动"）
    command_text = Column(String(100), nullable=False)     # 口令（如 halloween）
    total_count = Column(Integer, default=0)               # 总礼包码数量
    claimed_count = Column(Integer, default=0)             # 已领取数量
    is_active = Column(Boolean, default=True)              # 是否启用
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    __table_args__ = (
        UniqueConstraint('bot_id', 'guild_id', 'command_text', name='uq_bot_guild_command'),
    )

# 礼包码表（每个礼包码一条记录）
class GiftCode(Base):
    __tablename__ = 'gift_codes'
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, nullable=False, index=True)
    code = Column(Text, nullable=False)
    is_claimed = Column(Boolean, default=False, index=True)
    claimed_by_user_id = Column(String(50))
    claimed_by_user_name = Column(String(100))
    claimed_at = Column(DateTime)

# 礼包码领取日志表
class GiftClaimLog(Base):
    __tablename__ = 'gift_claim_logs'
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, nullable=False)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    channel_id = Column(String(50))
    code = Column(Text)
    user_id = Column(String(50))
    user_name = Column(String(100))
    claimed_at = Column(DateTime, default=datetime.datetime.utcnow)

# ========== 机器人回复消息配置表 ==========

class BotMessage(Base):
    """存储机器人各场景的可自定义回复消息（支持 {变量} 模板）"""
    __tablename__ = 'bot_messages'

    id = Column(Integer, primary_key=True)
    message_key = Column(String(100), nullable=False)          # 唯一标识（如 claim_success）
    bot_id = Column(String(50), nullable=False, default='default')
    message_text = Column(Text, nullable=False)                # 可带 {变量} 的消息模板
    description = Column(String(200))                          # 在后台显示的说明文字
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('message_key', 'bot_id', name='uq_bot_message'),
    )

# ========== 消息广播系统 ==========

# 目标类型常量
TARGET_CHANNEL = "channel"
TARGET_FORUM_NEW = "forum_new"
TARGET_FORUM_REPLY = "forum_reply"

# 调度类型常量
SCHEDULE_IMMEDIATE = "immediate"
SCHEDULE_TIMED = "scheduled"

# 任务状态常量
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_DRAFT = "draft"


class MemberCache(Base):
    """公会成员/角色缓存表（供 @提及 使用）"""
    __tablename__ = 'member_cache'

    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    user_id = Column(String(50), nullable=False)
    username = Column(String(100))
    nickname = Column(String(100))
    display_name = Column(String(100))                         # nickname or username
    avatar_url = Column(String(200))
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (UniqueConstraint('bot_id', 'guild_id', 'user_id', name='uq_member_cache'),)


# ========== UID 自动采集系统 ==========

# UID 采集进程状态
UID_CAMPAIGN_RUNNING = "running"   # 运行中
UID_CAMPAIGN_PAUSED = "paused"     # 暂停
UID_CAMPAIGN_ENDED = "ended"       # 结束（到时间自动结案）

# UID 记录状态
UID_STATUS_VALID = "valid"            # 有效，已确认
UID_STATUS_DUPLICATE = "duplicate"    # 与其它 UID 重叠 / 同一人重复（作废）
UID_STATUS_INVALID = "invalid"        # 位数不符 / 同一人多发不同 UID（作废）

# UID 无效原因
UID_REASON_OVERLAP = "overlap"        # 与其它用户提交的 UID 重叠
UID_REASON_MULTIPLE = "multiple"      # 同一用户提交了多个不同 UID
UID_REASON_LENGTH = "length"          # 数字位数不符（非配置位数）


class UIDCampaign(Base):
    """UID 采集进程（一次活动的完整配置 + 时间范围）"""
    __tablename__ = 'uid_campaigns'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, default="未命名采集")  # 进程名称
    status = Column(String(20), nullable=False, default=UID_CAMPAIGN_RUNNING)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    channel_id = Column(String(50), nullable=False)     # 单频道/进程
    uid_length = Column(Integer, default=8)             # UID 位数
    valid_reaction = Column(String(20), default="✅")
    duplicate_reaction = Column(String(20), default="❌")
    msg_overlap = Column(Text)                          # 质询模板
    msg_multiple = Column(Text)
    msg_length = Column(Text)
    started_at = Column(DateTime)                       # 开始时间（生效起点，空=不限）
    end_at = Column(DateTime)                           # 结束时间（到点自动结案）
    last_scan_message_id = Column(String(50), default="")  # 增量扫描游标
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)

    __table_args__ = (UniqueConstraint('bot_id', 'channel_id', name='uq_uid_campaign_channel'),)


class UIDRecord(Base):
    """UID 自动采集记录"""
    __tablename__ = 'uid_records'

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, nullable=True)        # 关联采集进程（可空=旧数据）
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    channel_id = Column(String(50), nullable=False)
    message_id = Column(String(50), nullable=False)     # 消息 ID（同一进程内唯一，防重复）
    user_id = Column(String(50), nullable=False)
    user_name = Column(String(100))
    uid = Column(String(50), nullable=False)            # 采集到的 UID（8 位数字）
    answer = Column(String(50))                         # 宽松提取的答案（可空）
    status = Column(String(20), nullable=False, default=UID_STATUS_VALID)
    invalid_reason = Column(String(20))
    raw_content = Column(Text, default='')              # 消息原文
    mentioned_users = Column(Text, default='[]')        # 消息内被 @ 的用户 JSON 数组
    scanned = Column(Boolean, default=False)            # True=历史扫描采得，False=实时采集
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('bot_id', 'campaign_id', 'message_id', name='uq_uid_message'),
    )


# 手动扫描任务状态
UID_SCAN_TASK_PENDING = "pending"    # 等待 bot 执行
UID_SCAN_TASK_PROCESSING = "processing"
UID_SCAN_TASK_DONE = "done"
UID_SCAN_TASK_FAILED = "failed"


class UIDScanTask(Base):
    """UID 手动扫描任务（查漏补缺）。

    后台「手动扫描」写入一条 pending 任务，bot 扫描循环轮询领取后，
    对该进程频道做全量历史扫描（基于进程时间范围过滤），并把结果写回。
    主要用于 bot 掉线后补采遗漏的消息。
    """
    __tablename__ = 'uid_scan_tasks'

    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    campaign_id = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default=UID_SCAN_TASK_PENDING)
    # 扫描结果统计（JSON 字符串）
    result = Column(Text, default='')
    error = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    processed_at = Column(DateTime)



class MessageTask(Base):
    """消息发送任务"""
    __tablename__ = 'message_tasks'

    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    task_name = Column(String(100))
    guild_id = Column(String(50), nullable=False)
    channel_id = Column(String(50), nullable=False)
    thread_id = Column(String(50))                             # 回复帖子时的帖子 ID
    thread_name = Column(String(200))                          # 论坛发帖时的标题
    target_type = Column(String(20), nullable=False, default=TARGET_CHANNEL)
    content = Column(Text)
    embed_json = Column(Text)                                  # 预留 Embed JSON
    schedule_type = Column(String(20), nullable=False, default=SCHEDULE_IMMEDIATE)
    scheduled_at = Column(DateTime)
    status = Column(String(20), nullable=False, default=STATUS_PENDING)
    result_msg = Column(Text)
    sent_at = Column(DateTime)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class MessageAttachment(Base):
    """消息附件（图片等）"""
    __tablename__ = 'message_attachments'

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, nullable=False, index=True)
    filename = Column(String(200))
    file_data = Column(LargeBinary)                            # 文件二进制数据
    content_type = Column(String(100))
    file_size = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ========== 传统抽奖系统 ==========

class Raffle(Base):
    """传统抽奖 — 定时开奖 / 手动开奖"""
    __tablename__ = 'raffles'

    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    channel_id = Column(String(50))              # 公告消息所在频道
    message_id = Column(String(50))              # 公告消息 ID（用于编辑）
    announce_channel_id = Column(String(50))     # 可选的开奖结果频道
    creator_id = Column(String(50))
    title = Column(String(100), nullable=False)
    description = Column(Text, default='')
    winner_count = Column(Integer, default=1)
    draw_time = Column(DateTime)                 # 定时开奖时间，NULL=仅手动开
    is_active = Column(Boolean, default=True)
    is_drawn = Column(Boolean, default=False)
    drawn_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class RaffleParticipant(Base):
    """传统抽奖参与者"""
    __tablename__ = 'raffle_participants'

    id = Column(Integer, primary_key=True)
    raffle_id = Column(Integer, nullable=False, index=True)
    user_id = Column(String(50), nullable=False)
    user_name = Column(String(100))
    joined_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_winner = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint('raffle_id', 'user_id', name='uq_raffle_user'),
    )


# ========== 即开型抽奖（一番赏风格）==========

class InstantLottery(Base):
    """即开型抽奖 — 固定奖池+打乱+按序抽取"""
    __tablename__ = 'instant_lotteries'

    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), nullable=False)
    guild_id = Column(String(50), nullable=False)
    channel_id = Column(String(50))              # 公告消息所在频道
    message_id = Column(String(50))              # 公告消息 ID
    creator_id = Column(String(50))
    title = Column(String(100), nullable=False)
    description = Column(Text, default='')
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    total_slots = Column(Integer, default=100)   # 总抽数（可配置）
    slots_drawn = Column(Integer, default=0)     # 已抽数
    max_draws_per_user = Column(Integer, default=3)  # 每人限制
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class LotteryPrize(Base):
    """即开型抽奖奖品配置"""
    __tablename__ = 'lottery_prizes'

    id = Column(Integer, primary_key=True)
    lottery_id = Column(Integer, nullable=False, index=True)
    tier_label = Column(String(20))              # S / A / B / LAST 等
    prize_name = Column(String(100))
    prize_desc = Column(Text, default='')
    emoji = Column(String(50), default='🎁')
    total_count = Column(Integer, nullable=False)
    remaining = Column(Integer, nullable=False)
    sort_order = Column(Integer, default=0)


class LotteryDrawRecord(Base):
    """即开型抽奖抽取记录"""
    __tablename__ = 'lottery_draw_records'

    id = Column(Integer, primary_key=True)
    lottery_id = Column(Integer, nullable=False, index=True)
    prize_id = Column(Integer, nullable=False)
    user_id = Column(String(50), nullable=False)
    user_name = Column(String(100))
    drawn_at = Column(DateTime, default=datetime.datetime.utcnow)


class LotteryPoolSlot(Base):
    """固定奖池槽位 — 预生成打乱后的抽奖序列"""
    __tablename__ = 'lottery_pool_slots'

    id = Column(Integer, primary_key=True)       # 自增即 shuffle 后的位置
    lottery_id = Column(Integer, nullable=False, index=True)
    prize_id = Column(Integer, nullable=True)    # NULL = 谢谢参与
    tier_label = Column(String(20))              # 冗余缓存
    prize_name = Column(String(100))
    emoji = Column(String(50))
    is_drawn = Column(Boolean, default=False)
    drawn_by_user_id = Column(String(50))
    drawn_by_user_name = Column(String(100))
    drawn_at = Column(DateTime)


# 默认消息模板定义
DEFAULT_BOT_MESSAGES = {
    "claim_not_in_guild": {
        "text": "❌ 礼包码领取只能在服务器频道中进行",
        "description": "用户在私聊中使用 /code 时",
        "variables": "",
    },
    "claim_not_found": {
        "text": "❌ 未找到口令 '{command_text}' 对应的礼包码活动，或活动已结束",
        "description": "口令不存在或已停用时",
        "variables": "command_text",
    },
    "claim_already_claimed": {
        "text": "ℹ️ 你已经领取过「{batch_name}」的礼包码了，你的礼包码：{code_value}",
        "description": "用户重复领取同一批次时",
        "variables": "batch_name, code_value",
    },
    "claim_sold_out": {
        "text": "😢 「{batch_name}」的礼包码已经全部发放完毕了",
        "description": "批次礼包码已领完时",
        "variables": "batch_name",
    },
    "claim_success": {
        "text": "🎁 你的「{batch_name}」礼包码是：**{code_value}**",
        "description": "领取成功时",
        "variables": "batch_name, code_value",
    },
    "claim_failed": {
        "text": "❌ 领取失败，请稍后重试",
        "description": "系统异常时",
        "variables": "",
    },
    "ping_response": {
        "text": "🏓 Pong! 数据库连接正常。",
        "description": "!ping 命令回复",
        "variables": "",
    },
    # ========== 传统抽奖消息模板 ==========
    "raffle_embed_desc": {
        "text": (
            "{description}\n"
            "🏆 **中奖人数**：{winner_count}\n"
            "⏰ **开奖时间**：{draw_time}\n"
            "📊 **参与人数**：{participant_count}\n"
            "{status_icon} **状态**：{status_text}"
        ),
        "description": "传统抽奖公告 Embed 描述（变量: title, description, winner_count, draw_time, participant_count, status_icon, status_text, raffle_id）",
        "variables": "title, description, winner_count, draw_time, participant_count, status_icon, status_text, raffle_id",
    },
    "raffle_result_desc": {
        "text": (
            "{description}\n"
            "📊 **参与人数**：{participant_count}\n"
            "🏆 **中奖人数**：{winner_count}\n"
            "⏰ **开奖时间**：{draw_time}"
        ),
        "description": "传统抽奖开奖结果 Embed 描述（变量: title, description, participant_count, winner_count, draw_time, raffle_id）",
        "variables": "title, description, participant_count, winner_count, draw_time, raffle_id",
    },
    "raffle_join_success": {
        "text": "✅ 报名成功！当前共 {count} 人参与。",
        "description": "传统抽奖报名成功提示",
        "variables": "count",
    },
    "raffle_already_joined": {
        "text": "⚠️ 你已经参与过了！",
        "description": "传统抽奖重复报名提示",
        "variables": "",
    },
    "raffle_announce_draw": {
        "text": (
            "🎉 **{title}** 开奖啦！（{operator}触发）\n"
            "恭喜 {mentions} 中奖！\n"
            "共 {winner_count} 人获奖，{participant_count} 人参与。"
        ),
        "description": "传统抽奖中奖公告 @ 消息",
        "variables": "title, operator, mentions, winner_count, participant_count",
    },
    # ========== 即开番赏消息模板 ==========
    "lottery_embed_desc": {
        "text": "{description}",
        "description": "即开番赏公告 Embed 描述（变量: title, description, total_slots, max_draws_per_user）",
        "variables": "title, description, total_slots, max_draws_per_user",
    },
    "lottery_draw_ephemeral": {
        "text": "{result_emoji} **{result_text}**\n\n已抽 {my_count}/{max_draws} 次 · 奖池剩余 {slots_left} 抽",
        "description": "即开番赏抽奖结果（临时消息，变量: result_emoji, result_text, my_count, max_draws, slots_left）",
        "variables": "result_emoji, result_text, my_count, max_draws, slots_left",
    },
    "lottery_draw_blocked": {
        "text": "⚠️ 你已达到抽奖上限（{my_count}/{max_draws}），无法继续抽取。",
        "description": "即开番赏抽取被拒绝提示",
        "variables": "my_count, max_draws",
    },
    "lottery_force_close_announce": {
        "text": (
            "⏰ **{title}** 已超过 {duration} 小时，奖池强制清空！\n"
            "剩余 {left} 个奖品已随机分配给频道在线成员。\n"
            "中奖名单：{mentions}"
        ),
        "description": "即开番赏强制清空公告",
        "variables": "title, duration, left, mentions",
    },
    "lottery_modal_title": {
        "text": "确认抽奖",
        "description": "确认抽奖弹窗标题",
        "variables": "",
    },
    "lottery_modal_content": {
        "text": "消耗 1 次机会（你已抽 {my_count}/{max_draws} 次）\n奖池剩余 {slots_left} 抽",
        "description": "确认抽奖弹窗说明文字",
        "variables": "my_count, max_draws, slots_left",
    },
    # ===== 即开番赏公告 Embed 结构 =====
    "lottery_embed_title": {
        "text": "🎰 {title}",
        "description": "即开番赏公告标题（变量: title, lottery_id）",
        "variables": "title, lottery_id",
    },
    "lottery_embed_status_name": {
        "text": "状态",
        "description": "公告「状态」字段名",
        "variables": "",
    },
    "lottery_embed_status_active": {
        "text": "🟢 进行中",
        "description": "进行中的状态文本",
        "variables": "",
    },
    "lottery_embed_status_ended": {
        "text": "⚫ 已结束",
        "description": "已结束的状态文本",
        "variables": "",
    },
    "lottery_embed_progress_name": {
        "text": "📊 进度 {drawn}/{total}",
        "description": "公告「进度」字段名（变量: drawn, total）",
        "variables": "drawn, total",
    },
    "lottery_embed_progress_value": {
        "text": "`{bar}` 剩余 {left} 抽",
        "description": "公告「进度」字段值（变量: bar, left, total）",
        "variables": "bar, left, total",
    },
    "lottery_embed_prizes_name": {
        "text": "🏆 奖池",
        "description": "公告「奖池」字段名",
        "variables": "",
    },
    "lottery_embed_prize_normal": {
        "text": "{emoji} **{tier}** {name} `[{remaining}/{total}]`",
        "description": "奖池中未售罄奖品行（变量: emoji, tier, name, remaining, total）",
        "variables": "emoji, tier, name, remaining, total",
    },
    "lottery_embed_prize_soldout": {
        "text": "{emoji} **{tier}** ~~{name}~~ 已售罄 `[{remaining}/{total}]`",
        "description": "奖池中已售罄奖品行（变量: emoji, tier, name, remaining, total）",
        "variables": "emoji, tier, name, remaining, total",
    },
    "lottery_embed_recent_name": {
        "text": "📜 最近抽取",
        "description": "公告「最近抽取」字段名",
        "variables": "",
    },
    "lottery_embed_recent_hit": {
        "text": "{emoji} **{user}** → {tier} {name}",
        "description": "最近抽取-中奖行（变量: emoji, user, tier, name）",
        "variables": "emoji, user, tier, name",
    },
    "lottery_embed_recent_miss": {
        "text": "😔 **{user}** → 谢谢参与",
        "description": "最近抽取-谢谢参与行（变量: user）",
        "variables": "user",
    },
    "lottery_embed_limit_name": {
        "text": "每人限抽",
        "description": "公告「每人限抽」字段名",
        "variables": "",
    },
    "lottery_embed_limit_value": {
        "text": "{n} 次",
        "description": "公告「每人限抽」字段值（变量: n）",
        "variables": "n",
    },
    "lottery_embed_endtime_name": {
        "text": "结束时间",
        "description": "公告「结束时间」字段名",
        "variables": "",
    },
    "lottery_embed_endtime_value": {
        "text": "{time}",
        "description": "公告「结束时间」字段值（变量: time）",
        "variables": "time",
    },
    "lottery_embed_endtime_na": {
        "text": "未设置",
        "description": "结束时间为空时显示",
        "variables": "",
    },
    "lottery_embed_footer": {
        "text": "抽奖 ID: {id} • 时间均为北京时间",
        "description": "公告页脚（变量: id）",
        "variables": "id",
    },
    # ===== 即开番赏结果公示 =====
    "lottery_result_title": {
        "text": "🏆 {title} — 抽奖结果公示",
        "description": "抽奖结果公示标题（变量: title, lottery_id）",
        "variables": "title, lottery_id",
    },
    "lottery_result_desc": {
        "text": "共 {drawn}/{total} 抽\n中奖 {hit} 人次",
        "description": "结果公示描述（变量: drawn, total, hit, title）",
        "variables": "drawn, total, hit, title",
    },
    "lottery_result_winner_name": {
        "text": "中奖名单",
        "description": "结果公示「中奖名单」字段名",
        "variables": "",
    },
    "lottery_result_no_winner": {
        "text": "无中奖者",
        "description": "结果公示无中奖者时显示",
        "variables": "",
    },
    "lottery_result_line": {
        "text": "{emoji} {tier}-{name}",
        "description": "结果公示中奖行（变量: emoji, tier, name）",
        "variables": "emoji, tier, name",
    },
    "lottery_result_footer": {
        "text": "抽奖 ID: {id} • 时间均为北京时间",
        "description": "结果公示页脚（变量: id）",
        "variables": "id",
    },
    # ===== 即开番赏交互 =====
    "lottery_draw_button": {
        "text": "🎯 抽一发",
        "description": "抽奖按钮文字",
        "variables": "",
    },
    "lottery_draw_error": {
        "text": "❌ {message}",
        "description": "抽奖过程错误提示（变量: message）",
        "variables": "message",
    },
    "lottery_draw_fail": {
        "text": "❌ 出错了，请稍后重试",
        "description": "抽奖未知错误兜底提示",
        "variables": "",
    },
    "lottery_modal_confirm_label": {
        "text": "输入「抽」确认抽取",
        "description": "确认弹窗输入框标签",
        "variables": "",
    },
    "lottery_modal_confirm_placeholder": {
        "text": "输入「抽」确认",
        "description": "确认弹窗输入框占位符",
        "variables": "",
    },
    "lottery_modal_confirm_wrong": {
        "text": "❌ 请输入「抽」来确认",
        "description": "确认内容不正确时提示",
        "variables": "",
    },
    "lottery_force_close_prize_line": {
        "text": "{emoji} {tier} — {name}",
        "description": "强制清空后分配奖品行（变量: emoji, tier, name）",
        "variables": "emoji, tier, name",
    },
    "lottery_force_close_no_prize": {
        "text": "无剩余奖品",
        "description": "强制清空时无剩余奖品",
        "variables": "",
    },
    # ===== 传统抽奖补充结构 =====
    "raffle_embed_title": {
        "text": "🎟️ {title}",
        "description": "传统抽奖公告标题（变量: title, raffle_id）",
        "variables": "title, raffle_id",
    },
    "raffle_embed_footer": {
        "text": "抽奖 ID: {id} • 时间均为北京时间",
        "description": "传统抽奖公告页脚（变量: id）",
        "variables": "id",
    },
    "raffle_embed_default_desc": {
        "text": "🎟️ {draw_type} — 点击下方按钮参与！",
        "description": "传统抽奖无自定义描述时的默认文案（变量: draw_type, title）",
        "variables": "draw_type, title",
    },
    "raffle_status_active": {
        "text": "🟢 进行中",
        "description": "传统抽奖进行中状态文本",
        "variables": "",
    },
    "raffle_status_drawn": {
        "text": "🔴 已开奖",
        "description": "传统抽奖已开奖状态文本",
        "variables": "",
    },
    "raffle_status_ended": {
        "text": "⚫ 已结束",
        "description": "传统抽奖已结束状态文本",
        "variables": "",
    },
    "raffle_result_title": {
        "text": "🎟️ {title} [已开奖]",
        "description": "传统抽奖开奖结果标题（变量: title, raffle_id）",
        "variables": "title, raffle_id",
    },
    "raffle_result_winner_name": {
        "text": "中奖者",
        "description": "传统抽奖「中奖者」字段名",
        "variables": "",
    },
    "raffle_result_winner_line": {
        "text": "🏆 {user}",
        "description": "传统抽奖中奖者行（变量: user）",
        "variables": "user",
    },
    "raffle_result_no_winner": {
        "text": "无人中奖",
        "description": "传统抽奖无中奖者时显示",
        "variables": "",
    },
    "raffle_result_footer": {
        "text": "抽奖 ID: {id} • 时间均为北京时间",
        "description": "传统抽奖结果页脚（变量: id）",
        "variables": "id",
    },
    "raffle_draw_failed": {
        "text": "🎟️ **{title}** 开奖失败：{message}",
        "description": "传统抽奖开奖失败公告（变量: title, message）",
        "variables": "title, message",
    },
    "raffle_draw_error": {
        "text": "❌ {message}",
        "description": "传统抽奖错误提示（变量: message）",
        "variables": "message",
    },
    "raffle_join_button": {
        "text": "🎫 参与抽奖",
        "description": "传统抽奖参与按钮文字",
        "variables": "",
    },
    "raffle_manual_button": {
        "text": "✋ 手动开奖",
        "description": "传统抽奖手动开奖按钮文字",
        "variables": "",
    },
    "raffle_manual_permission_denied": {
        "text": "❌ 只有管理员可以手动开奖。",
        "description": "手动开奖权限不足提示",
        "variables": "",
    },
    "raffle_manual_done": {
        "text": "✅ 已执行开奖。",
        "description": "手动开奖成功提示",
        "variables": "",
    },
}


# ===== 消息模板前端展示元数据（key → 中文名 + 变量含义解释） =====
# display_name：左侧列表/编辑器标题展示的中文名
# variable_descriptions：{变量名: 含义}，右侧编辑框上方展示
BOT_MESSAGE_META = {
    # ---- 礼包码 ----
    "claim_not_in_guild": {
        "display_name": "礼包码-私聊限制",
        "variable_descriptions": {},
    },
    "claim_not_found": {
        "display_name": "礼包码-口令不存在",
        "variable_descriptions": {
            "command_text": "用户输入的口令",
        },
    },
    "claim_already_claimed": {
        "display_name": "礼包码-重复领取",
        "variable_descriptions": {
            "batch_name": "礼包码批次名称",
            "code_value": "已发放的礼包码内容",
        },
    },
    "claim_sold_out": {
        "display_name": "礼包码-已领完",
        "variable_descriptions": {
            "batch_name": "礼包码批次名称",
        },
    },
    "claim_success": {
        "display_name": "礼包码-领取成功",
        "variable_descriptions": {
            "batch_name": "礼包码批次名称",
            "code_value": "发放的礼包码内容",
        },
    },
    "claim_failed": {
        "display_name": "礼包码-领取失败",
        "variable_descriptions": {},
    },
    "ping_response": {
        "display_name": "系统-Ping回复",
        "variable_descriptions": {},
    },
    # ---- 传统抽奖 ----
    "raffle_embed_desc": {
        "display_name": "传统抽奖-公告正文",
        "variable_descriptions": {
            "title": "抽奖标题",
            "description": "抽奖描述（创建时填写）",
            "winner_count": "中奖人数",
            "draw_time": "开奖时间",
            "participant_count": "当前参与人数",
            "status_icon": "状态图标（🟢/🔴/⚫）",
            "status_text": "状态文字（进行中/已开奖/已结束）",
            "raffle_id": "抽奖 ID",
        },
    },
    "raffle_result_desc": {
        "display_name": "传统抽奖-结果正文",
        "variable_descriptions": {
            "title": "抽奖标题",
            "description": "抽奖描述",
            "participant_count": "参与人数",
            "winner_count": "中奖人数",
            "draw_time": "开奖时间",
            "raffle_id": "抽奖 ID",
        },
    },
    "raffle_join_success": {
        "display_name": "传统抽奖-报名成功",
        "variable_descriptions": {
            "count": "当前参与人数",
        },
    },
    "raffle_already_joined": {
        "display_name": "传统抽奖-重复报名",
        "variable_descriptions": {},
    },
    "raffle_announce_draw": {
        "display_name": "传统抽奖-中奖公告@",
        "variable_descriptions": {
            "title": "抽奖标题",
            "operator": "开奖操作人",
            "mentions": "@中奖者列表",
            "winner_count": "中奖人数",
            "participant_count": "参与人数",
        },
    },
    "raffle_embed_title": {
        "display_name": "传统抽奖-公告标题",
        "variable_descriptions": {
            "title": "抽奖标题",
            "raffle_id": "抽奖 ID",
        },
    },
    "raffle_embed_footer": {
        "display_name": "传统抽奖-公告页脚",
        "variable_descriptions": {
            "id": "抽奖 ID",
        },
    },
    "raffle_embed_default_desc": {
        "display_name": "传统抽奖-默认正文",
        "variable_descriptions": {
            "draw_type": "开奖方式（手动/定时）",
            "title": "抽奖标题",
        },
    },
    "raffle_status_active": {
        "display_name": "传统抽奖-状态·进行中",
        "variable_descriptions": {},
    },
    "raffle_status_drawn": {
        "display_name": "传统抽奖-状态·已开奖",
        "variable_descriptions": {},
    },
    "raffle_status_ended": {
        "display_name": "传统抽奖-状态·已结束",
        "variable_descriptions": {},
    },
    "raffle_result_title": {
        "display_name": "传统抽奖-结果标题",
        "variable_descriptions": {
            "title": "抽奖标题",
            "raffle_id": "抽奖 ID",
        },
    },
    "raffle_result_winner_name": {
        "display_name": "传统抽奖-中奖者字段名",
        "variable_descriptions": {},
    },
    "raffle_result_winner_line": {
        "display_name": "传统抽奖-中奖者行",
        "variable_descriptions": {
            "user": "中奖者名称",
        },
    },
    "raffle_result_no_winner": {
        "display_name": "传统抽奖-无中奖者",
        "variable_descriptions": {},
    },
    "raffle_result_footer": {
        "display_name": "传统抽奖-结果页脚",
        "variable_descriptions": {
            "id": "抽奖 ID",
        },
    },
    "raffle_draw_failed": {
        "display_name": "传统抽奖-开奖失败",
        "variable_descriptions": {
            "title": "抽奖标题",
            "message": "失败原因",
        },
    },
    "raffle_draw_error": {
        "display_name": "传统抽奖-错误提示",
        "variable_descriptions": {
            "message": "错误信息",
        },
    },
    "raffle_join_button": {
        "display_name": "传统抽奖-参与按钮",
        "variable_descriptions": {},
    },
    "raffle_manual_button": {
        "display_name": "传统抽奖-手动开奖按钮",
        "variable_descriptions": {},
    },
    "raffle_manual_permission_denied": {
        "display_name": "传统抽奖-权限不足",
        "variable_descriptions": {},
    },
    "raffle_manual_done": {
        "display_name": "传统抽奖-开奖完成",
        "variable_descriptions": {},
    },
    # ---- 即开番赏 ----
    "lottery_embed_desc": {
        "display_name": "番赏-公告正文",
        "variable_descriptions": {
            "title": "番赏标题",
            "description": "番赏描述（创建时填写）",
            "total_slots": "奖池总槽位数",
            "max_draws_per_user": "每人限抽次数",
        },
    },
    "lottery_draw_ephemeral": {
        "display_name": "番赏-抽取结果(临时)",
        "variable_descriptions": {
            "result_emoji": "抽中奖品的 emoji",
            "result_text": "抽中奖品的描述",
            "my_count": "你已抽取次数",
            "max_draws": "每人限抽次数",
            "slots_left": "奖池剩余抽数",
        },
    },
    "lottery_draw_blocked": {
        "display_name": "番赏-次数用尽",
        "variable_descriptions": {
            "my_count": "你已抽取次数",
            "max_draws": "每人限抽次数",
        },
    },
    "lottery_force_close_announce": {
        "display_name": "番赏-强制清空公告",
        "variable_descriptions": {
            "title": "番赏标题",
            "duration": "超时小时数（24）",
            "left": "剩余未抽取槽位数",
            "mentions": "分配奖品的 @用户列表",
        },
    },
    "lottery_modal_title": {
        "display_name": "番赏-确认弹窗标题",
        "variable_descriptions": {},
    },
    "lottery_modal_content": {
        "display_name": "番赏-确认弹窗说明",
        "variable_descriptions": {
            "my_count": "你已抽取次数",
            "max_draws": "每人限抽次数",
            "slots_left": "奖池剩余抽数",
        },
    },
    "lottery_embed_title": {
        "display_name": "番赏-公告标题",
        "variable_descriptions": {
            "title": "番赏标题",
            "lottery_id": "番赏 ID",
        },
    },
    "lottery_embed_status_name": {
        "display_name": "番赏-状态字段名",
        "variable_descriptions": {},
    },
    "lottery_embed_status_active": {
        "display_name": "番赏-状态·进行中",
        "variable_descriptions": {},
    },
    "lottery_embed_status_ended": {
        "display_name": "番赏-状态·已结束",
        "variable_descriptions": {},
    },
    "lottery_embed_progress_name": {
        "display_name": "番赏-进度字段名",
        "variable_descriptions": {
            "drawn": "已抽取数",
            "total": "总槽位数",
        },
    },
    "lottery_embed_progress_value": {
        "display_name": "番赏-进度条内容",
        "variable_descriptions": {
            "bar": "进度条图形",
            "left": "剩余抽数",
            "total": "总槽位数",
        },
    },
    "lottery_embed_prizes_name": {
        "display_name": "番赏-奖池字段名",
        "variable_descriptions": {},
    },
    "lottery_embed_prize_normal": {
        "display_name": "番赏-奖品行(未售罄)",
        "variable_descriptions": {
            "emoji": "奖品 emoji",
            "tier": "奖品等级",
            "name": "奖品名称",
            "remaining": "剩余数量",
            "total": "总数量",
        },
    },
    "lottery_embed_prize_soldout": {
        "display_name": "番赏-奖品行(已售罄)",
        "variable_descriptions": {
            "emoji": "奖品 emoji",
            "tier": "奖品等级",
            "name": "奖品名称",
            "remaining": "剩余数量",
            "total": "总数量",
        },
    },
    "lottery_embed_recent_name": {
        "display_name": "番赏-最近抽取字段名",
        "variable_descriptions": {},
    },
    "lottery_embed_recent_hit": {
        "display_name": "番赏-最近中奖行",
        "variable_descriptions": {
            "emoji": "奖品 emoji",
            "user": "抽取者",
            "tier": "奖品等级",
            "name": "奖品名称",
        },
    },
    "lottery_embed_recent_miss": {
        "display_name": "番赏-最近谢谢参与",
        "variable_descriptions": {
            "user": "抽取者",
        },
    },
    "lottery_embed_limit_name": {
        "display_name": "番赏-限抽字段名",
        "variable_descriptions": {},
    },
    "lottery_embed_limit_value": {
        "display_name": "番赏-限抽字段值",
        "variable_descriptions": {
            "n": "每人限抽次数",
        },
    },
    "lottery_embed_endtime_name": {
        "display_name": "番赏-结束时间字段名",
        "variable_descriptions": {},
    },
    "lottery_embed_endtime_value": {
        "display_name": "番赏-结束时间字段值",
        "variable_descriptions": {
            "time": "结束时间",
        },
    },
    "lottery_embed_endtime_na": {
        "display_name": "番赏-结束时间(未设置)",
        "variable_descriptions": {},
    },
    "lottery_embed_footer": {
        "display_name": "番赏-公告页脚",
        "variable_descriptions": {
            "id": "番赏 ID",
        },
    },
    "lottery_result_title": {
        "display_name": "番赏-结果标题",
        "variable_descriptions": {
            "title": "番赏标题",
            "lottery_id": "番赏 ID",
        },
    },
    "lottery_result_desc": {
        "display_name": "番赏-结果正文",
        "variable_descriptions": {
            "drawn": "总抽取次数",
            "total": "总槽位数",
            "hit": "中奖人次",
            "title": "番赏标题",
        },
    },
    "lottery_result_winner_name": {
        "display_name": "番赏-中奖名单字段名",
        "variable_descriptions": {},
    },
    "lottery_result_no_winner": {
        "display_name": "番赏-无中奖者",
        "variable_descriptions": {},
    },
    "lottery_result_line": {
        "display_name": "番赏-中奖行",
        "variable_descriptions": {
            "emoji": "奖品 emoji",
            "tier": "奖品等级",
            "name": "奖品名称",
        },
    },
    "lottery_result_footer": {
        "display_name": "番赏-结果页脚",
        "variable_descriptions": {
            "id": "番赏 ID",
        },
    },
    "lottery_draw_button": {
        "display_name": "番赏-抽奖按钮",
        "variable_descriptions": {},
    },
    "lottery_draw_error": {
        "display_name": "番赏-错误提示",
        "variable_descriptions": {
            "message": "错误信息",
        },
    },
    "lottery_draw_fail": {
        "display_name": "番赏-未知错误",
        "variable_descriptions": {},
    },
    "lottery_modal_confirm_label": {
        "display_name": "番赏-确认输入框标签",
        "variable_descriptions": {},
    },
    "lottery_modal_confirm_placeholder": {
        "display_name": "番赏-确认输入框占位",
        "variable_descriptions": {},
    },
    "lottery_modal_confirm_wrong": {
        "display_name": "番赏-确认不正确提示",
        "variable_descriptions": {},
    },
    "lottery_force_close_prize_line": {
        "display_name": "番赏-强制清空奖品行",
        "variable_descriptions": {
            "emoji": "奖品 emoji",
            "tier": "奖品等级",
            "name": "奖品名称",
        },
    },
    "lottery_force_close_no_prize": {
        "display_name": "番赏-清空无剩余奖品",
        "variable_descriptions": {},
    },
}


# ---- 初始化数据库引擎与建表 ----
# 注意：create_all 必须放在所有模型定义之后，否则新表（如 uid_records）不会被创建。
Base.metadata.create_all(engine)  # 自动创建缺失的表
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _migrate_uid_campaign_schema():
    """轻量迁移：为已存在的 uid_records 表添加 campaign_id 列（幂等）。

    因为 create_all 不会给已存在的表加列，而 dashboard 与 bot 都会查询
    uid_records，所以在这里统一处理，保证两端导入 models 后列都存在。
    """
    from sqlalchemy import text, inspect
    try:
        inspector = inspect(engine)
        if "uid_records" not in inspector.get_table_names():
            return
        cols = [c["name"] for c in inspector.get_columns("uid_records")]
        if "campaign_id" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE uid_records ADD COLUMN campaign_id INTEGER"))
                conn.commit()
            print("[DB] uid_records.campaign_id 列迁移完成")
    except Exception as e:
        print(f"[DB] uid_campaign 迁移失败(忽略): {e}")


_migrate_uid_campaign_schema()