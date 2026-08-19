"""统一抽奖管理 State（传统抽奖 + 即开番赏 + 消息模板编辑器）"""
import reflex as rx
from typing import Any
from datetime import timedelta
from pydantic import BaseModel
from shared_lib import crud
from shared_lib.utils.time_utils import beijing_input_to_utc_datetime, now_beijing
from .bot_state import BotState
from .message_state import MessageState


class PrizeRow(BaseModel):
    """即开番赏动态奖品行"""
    key: str = ""       # 唯一标识，用于删除/编辑定位
    tier_label: str = ""
    prize_name: str = ""
    prize_desc: str = ""
    emoji: str = "🎁"
    count: int = 1


class DrawState(BotState):
    # ========== 公共 ==========
    draw_type: str = "raffle"          # "raffle" | "lottery"
    channel_options: list[dict] = []
    list_modal_open: bool = False      # 列表弹窗开关（点击标题右上角图标打开）

    # ========== 传统抽奖：创建表单 ==========
    raffle_create_title: str = ""
    raffle_create_description: str = ""
    raffle_create_winner_count: int = 1
    raffle_create_draw_time: str = ""  # datetime-local (北京时间)
    raffle_create_channel_id: str = ""
    raffle_create_status: str = ""

    # ========== 传统抽奖：列表/详情/删除 ==========
    raffles: list[dict] = []
    raffle_detail_modal_open: bool = False
    selected_raffle_id: int = 0
    raffle_detail: dict = {}
    raffle_participants: list[dict] = []
    raffle_delete_confirm_open: bool = False

    # ========== 即开番赏：创建表单 ==========
    lottery_create_title: str = ""
    lottery_create_description: str = ""
    lottery_create_start_time: str = ""  # datetime-local (北京时间)
    lottery_create_end_time: str = ""    # datetime-local (北京时间)
    lottery_create_channel_id: str = ""
    lottery_create_total_slots: int = 100
    lottery_create_max_draws: int = 3
    lottery_create_status: str = ""
    prizes: list[PrizeRow] = [PrizeRow(key="prize_0")]

    # ========== 即开番赏：列表/详情/删除 ==========
    lotteries: list[dict] = []
    lottery_detail_modal_open: bool = False
    selected_lottery_id: int = 0
    lottery_detail_title: str = ""
    lottery_detail_total_slots: int = 100
    lottery_detail_slots_drawn: int = 0
    lottery_detail_slots_left: int = 100
    lottery_detail_hit_count: int = 0
    lottery_detail_prizes: list[dict] = []
    lottery_detail_recent_draws: list[dict] = []
    lottery_draw_records: list[dict] = []
    lottery_delete_confirm_open: bool = False

    # ========== 类型切换 ==========
    async def set_draw_type(self, value: str):
        self.draw_type = value
        if value == "raffle":
            self.load_raffles()
        else:
            self.load_lotteries()
        # 切换类型时，内嵌模板编辑器只加载对应前缀的模板
        msg_state = await self.get_state(MessageState)
        await msg_state.load_data("raffle_" if value == "raffle" else "lottery_")

    # ========== 列表弹窗 ==========
    def open_list_modal(self):
        """打开列表弹窗（标题右上角图标按钮触发）"""
        # 打开前刷新一次，确保看到最新数据
        if self.draw_type == "raffle":
            self.load_raffles()
        else:
            self.load_lotteries()
        self.list_modal_open = True

    def close_list_modal(self):
        self.list_modal_open = False

    def on_list_modal_change(self, open: bool):
        """响应 rx.dialog.root 的 on_open_change 事件"""
        self.list_modal_open = open

    # ========== 公共加载 ==========
    async def load_data(self):
        """页面加载时执行"""
        self.channel_options = crud.get_channels_all_types(
            self.current_bot_id
        ).get("text", [])
        self.load_raffles()
        self.load_lotteries()
        # 加载抽奖相关的消息模板（供页面内嵌模板编辑器使用），按当前类型只加载对应前缀
        msg_state = await self.get_state(MessageState)
        await msg_state.load_data("raffle_" if self.draw_type == "raffle" else "lottery_")

    def load_raffles(self):
        self.raffles = crud.get_raffle_manage_list(self.current_bot_id)

    def load_lotteries(self):
        self.lotteries = crud.get_lottery_manage_list(self.current_bot_id)

    def _get_guild_id_from_channel(self, channel_id: str) -> str:
        """从 channel_options 中查找频道所属的 guild_id"""
        for ch in self.channel_options:
            if ch.get("channel_id") == channel_id:
                return ch.get("guild_id", "")
        return ""

    # ========== 传统抽奖：创建表单处理 ==========
    def set_raffle_create_title(self, value: str):
        self.raffle_create_title = value

    def set_raffle_create_description(self, value: str):
        self.raffle_create_description = value

    def set_raffle_create_draw_time(self, value: str):
        self.raffle_create_draw_time = value

    def set_raffle_create_channel_id(self, value: str):
        self.raffle_create_channel_id = value

    def handle_raffle_winner_count(self, value: str):
        try:
            self.raffle_create_winner_count = max(1, int(value))
        except (ValueError, TypeError):
            self.raffle_create_winner_count = 1

    async def create_raffle(self):
        channel_id = self.raffle_create_channel_id or ""
        guild_id = self._get_guild_id_from_channel(channel_id)

        if not self.raffle_create_title.strip():
            self.raffle_create_status = "请输入抽奖标题"
            yield
            return
        if not channel_id:
            self.raffle_create_status = "请选择发布频道"
            yield
            return

        draw_time = beijing_input_to_utc_datetime(self.raffle_create_draw_time)

        result = crud.create_raffle(
            bot_id=self.current_bot_id,
            guild_id=guild_id,
            channel_id=channel_id,
            title=self.raffle_create_title.strip(),
            description=self.raffle_create_description.strip(),
            winner_count=self.raffle_create_winner_count,
            draw_time=draw_time,
            creator_id="dashboard",
        )
        if result.get("success"):
            self.raffle_create_title = ""
            self.raffle_create_description = ""
            self.raffle_create_winner_count = 1
            self.raffle_create_draw_time = ""
            self.raffle_create_channel_id = ""
            self.raffle_create_status = "创建成功"
            self.load_raffles()
        else:
            self.raffle_create_status = result.get("message", "创建失败")
        yield

    # ========== 传统抽奖：详情弹窗 ==========
    async def view_raffle_detail(self, raffle_id: int):
        self.selected_raffle_id = raffle_id
        self.raffle_detail = crud.get_raffle(raffle_id) or {}
        self.raffle_participants = crud.get_raffle_participants(raffle_id)
        self.raffle_detail_modal_open = True

    def on_raffle_detail_dialog_change(self, open: bool):
        self.raffle_detail_modal_open = open
        if not open:
            self.selected_raffle_id = 0
            self.raffle_detail = {}
            self.raffle_participants = []

    # ========== 传统抽奖：删除 ==========
    def confirm_delete_raffle(self, raffle_id: int):
        """打开删除确认对话框"""
        self.selected_raffle_id = raffle_id
        self.raffle_delete_confirm_open = True

    def on_raffle_delete_dialog_change(self, open: bool):
        self.raffle_delete_confirm_open = open

    async def execute_delete_raffle(self):
        """执行删除"""
        rid = self.selected_raffle_id
        if crud.delete_raffle(rid):
            self.raffle_delete_confirm_open = False
            self.load_raffles()
        yield

    # ========== 即开番赏：创建表单处理 ==========
    def set_lottery_create_title(self, value: str):
        self.lottery_create_title = value

    def set_lottery_create_description(self, value: str):
        self.lottery_create_description = value

    def set_lottery_create_start_time(self, value: str):
        self.lottery_create_start_time = value

    def set_lottery_create_end_time(self, value: str):
        self.lottery_create_end_time = value

    def set_lottery_create_channel_id(self, value: str):
        self.lottery_create_channel_id = value

    def handle_lottery_total_slots(self, value: str):
        try:
            self.lottery_create_total_slots = max(1, int(value))
        except (ValueError, TypeError):
            self.lottery_create_total_slots = 100

    def handle_lottery_max_draws(self, value: str):
        try:
            self.lottery_create_max_draws = max(1, int(value))
        except (ValueError, TypeError):
            self.lottery_create_max_draws = 3

    # --- 奖品行操作 ---
    _prize_counter: int = 0

    def add_prize_row(self):
        key = f"prize_{self._prize_counter}"
        self._prize_counter += 1
        self.prizes = self.prizes + [PrizeRow(key=key)]

    def remove_prize_row(self, key: str):
        self.prizes = [p for p in self.prizes if p.key != key]
        if not self.prizes:
            self.prizes = [PrizeRow(key=f"prize_{self._prize_counter}")]
            self._prize_counter += 1

    def set_prize_field(self, key: str, field: str, value: str):
        new_list = []
        for row in self.prizes:
            if row.key == key:
                updates = {}
                if field == "count":
                    try:
                        updates["count"] = max(1, int(value))
                    except (ValueError, TypeError):
                        updates["count"] = row.count
                else:
                    updates[field] = value
                new_list.append(row.model_copy(update=updates))
            else:
                new_list.append(row)
        self.prizes = new_list

    # --- 基于索引的奖品操作（配合显式索引渲染，绕过 rx.foreach 闭包问题） ---

    def set_prize_field_by_idx(self, idx: int, field: str, value: str):
        """Set a prize field by index — used with explicit-index rendering"""
        if idx < 0 or idx >= len(self.prizes):
            return
        new_list = list(self.prizes)
        row = new_list[idx]
        updates = {}
        if field == "count":
            try:
                updates["count"] = max(1, int(value))
            except (ValueError, TypeError):
                updates["count"] = row.count
        else:
            updates[field] = value
        new_list[idx] = row.model_copy(update=updates)
        self.prizes = new_list

    def remove_prize_row_by_idx(self, idx: int):
        """Remove a prize row by index — used with explicit-index rendering"""
        if idx < 0 or idx >= len(self.prizes):
            return
        new_list = [p for i, p in enumerate(self.prizes) if i != idx]
        if not new_list:
            new_list = [PrizeRow(key=f"prize_{self._prize_counter}")]
            self._prize_counter += 1
        self.prizes = new_list

    async def create_lottery(self):
        channel_id = self.lottery_create_channel_id or ""
        guild_id = self._get_guild_id_from_channel(channel_id)

        if not self.lottery_create_title.strip():
            self.lottery_create_status = "请输入抽奖标题"
            yield
            return
        if not channel_id:
            self.lottery_create_status = "请选择发布频道"
            yield
            return
        if not self.prizes:
            self.lottery_create_status = "请至少添加一个奖品"
            yield
            return

        start_time = beijing_input_to_utc_datetime(self.lottery_create_start_time)
        end_time = beijing_input_to_utc_datetime(self.lottery_create_end_time)

        prize_payload = [
            {
                "tier_label": p.tier_label,
                "prize_name": p.prize_name,
                "prize_desc": p.prize_desc,
                "emoji": p.emoji,
                "count": p.count,
            }
            for p in self.prizes
        ]

        result = crud.create_instant_lottery(
            bot_id=self.current_bot_id,
            guild_id=guild_id,
            channel_id=channel_id,
            title=self.lottery_create_title.strip(),
            description=self.lottery_create_description.strip(),
            start_time=start_time,
            end_time=end_time,
            creator_id="dashboard",
            prizes=prize_payload,
            total_slots=self.lottery_create_total_slots,
            max_draws_per_user=self.lottery_create_max_draws,
        )
        if result.get("success"):
            self.lottery_create_title = ""
            self.lottery_create_description = ""
            self.lottery_create_start_time = ""
            self.lottery_create_end_time = ""
            self.lottery_create_channel_id = ""
            self.lottery_create_total_slots = 100
            self.lottery_create_max_draws = 3
            self.prizes = [PrizeRow(key="prize_0")]
            self._prize_counter = 1
            self.lottery_create_status = "创建成功"
            self.load_lotteries()
        else:
            self.lottery_create_status = result.get("message", "创建失败")
        yield

    # ========== 即开番赏：详情弹窗 ==========
    async def view_lottery_detail(self, lottery_id: int):
        self.selected_lottery_id = lottery_id
        detail = crud.get_lottery_status(lottery_id) or {}
        self.lottery_detail_title = detail.get("title", "")
        self.lottery_detail_total_slots = detail.get("total_slots", 100)
        self.lottery_detail_slots_drawn = detail.get("slots_drawn", 0)
        self.lottery_detail_slots_left = detail.get("slots_left", 100)
        self.lottery_detail_hit_count = detail.get("hit_count", 0)
        self.lottery_detail_prizes = detail.get("prizes", [])
        self.lottery_detail_recent_draws = detail.get("recent_draws", [])
        self.lottery_draw_records = crud.get_lottery_draw_records(lottery_id)
        self.lottery_detail_modal_open = True

    def on_lottery_detail_dialog_change(self, open: bool):
        self.lottery_detail_modal_open = open
        if not open:
            self.selected_lottery_id = 0
            self.lottery_detail_title = ""
            self.lottery_detail_total_slots = 100
            self.lottery_detail_slots_drawn = 0
            self.lottery_detail_slots_left = 100
            self.lottery_detail_hit_count = 0
            self.lottery_detail_prizes = []
            self.lottery_detail_recent_draws = []
            self.lottery_draw_records = []

    # ========== 即开番赏：删除 ==========
    def confirm_delete_lottery(self, lottery_id: int):
        """打开删除确认对话框"""
        self.selected_lottery_id = lottery_id
        self.lottery_delete_confirm_open = True

    def on_lottery_delete_dialog_change(self, open: bool):
        self.lottery_delete_confirm_open = open

    async def execute_delete_lottery(self):
        """执行删除"""
        lid = self.selected_lottery_id
        if crud.delete_lottery(lid):
            self.lottery_delete_confirm_open = False
            self.load_lotteries()
        yield
