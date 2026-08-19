import asyncio
import reflex as rx
from shared_lib import crud
from pydantic import BaseModel
from .bot_state import BotState

class ChannelInfo(BaseModel):
    channel_id: str
    channel_name: str

class TrapState(rx.State):
    # ========== 正式状态（已保存到数据库的值）==========
    selected_channel_id: str = ""
    is_enabled: bool = False

    # ========== 草稿状态（用户正在编辑但未保存的值）==========
    draft_channel_id: str = ""
    draft_enabled: bool = False

    # ========== 下拉菜单数据 ==========
    available_channels: list[ChannelInfo] = []
    # 格式：[{"label": "频道A", "value": "123"}, {"label": "频道B", "value": "456"}]
    channel_options: list[dict] = []

    # ========== 日志 ==========
    kick_logs: list[dict] = []

    # ========== 保存提示（短暂闪现）==========
    save_toast: str = ""

    # ========== 内部状态 ==========
    _guild_id: str = ""
    _has_loaded: bool = False

    async def load_data(self):
        """页面加载时加载所有数据"""
        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id

        guilds = crud.get_guilds(bot_id)
        if guilds:
            self._guild_id = guilds[0]["guild_id"]
        else:
            self._guild_id = ""
            return

        # 1. 加载频道列表
        channels = crud.get_channels(bot_id, self._guild_id)
        self.available_channels = [
            ChannelInfo(channel_id=c["channel_id"], channel_name=c["channel_name"])
            for c in channels
        ]

        # 2. 加载陷阱配置
        config = crud.get_trap_config(bot_id, self._guild_id)
        if config:
            self.selected_channel_id = config.trap_channel_id or ""
            self.is_enabled = config.is_enabled
        else:
            self.selected_channel_id = ""
            self.is_enabled = False

        # 3. 同步草稿 = 正式值
        self.draft_channel_id = self.selected_channel_id
        self.draft_enabled = self.is_enabled

        # 4. 加载踢人日志
        self.kick_logs = crud.get_trap_logs(bot_id, self._guild_id)
        # 重置保存提示（刷新/重进页面不残留）
        self.save_toast = ""
        self._has_loaded = True

    # ========== 草稿操作方法（只修改草稿，不写数据库）==========

    def set_draft_channel(self, channel_id: str):
        """用户选择频道时调用（仅修改草稿）"""
        self.draft_channel_id = channel_id

    def set_draft_enabled(self, enabled: bool):
        """用户切换开关时调用（仅修改草稿）"""
        self.draft_enabled = enabled

    # ========== 保存/取消操作 ==========

    async def save_config(self):
        """保存草稿到数据库"""
        if not self._guild_id:
            return

        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id

        # 保存到数据库
        success = crud.set_trap_config(
            bot_id=bot_id,
            guild_id=self._guild_id,
            trap_channel_id=self.draft_channel_id if self.draft_channel_id else None,
            is_enabled=self.draft_enabled,
            whitelist_roles="",
            whitelist_users="",
            kick_message="⚠️ 本频道禁止非授权成员发言"
        )

        if success:
            # 更新正式状态 = 草稿
            self.selected_channel_id = self.draft_channel_id
            self.is_enabled = self.draft_enabled
            # 刷新日志
            self.kick_logs = crud.get_trap_logs(bot_id, self._guild_id)
            # 短暂闪现保存成功提示（2 秒后消失）
            self.save_toast = "✅ 所有配置已保存"
            yield
            await asyncio.sleep(2)
            self.save_toast = ""
            return
        else:
            self.save_toast = "❌ 保存失败，请稍后重试"
            yield
            await asyncio.sleep(2)
            self.save_toast = ""

    def cancel_edit(self):
        """撤销草稿修改，恢复到已保存的状态"""
        self.draft_channel_id = self.selected_channel_id
        self.draft_enabled = self.is_enabled
        self.save_toast = ""

    # ========== 辅助属性（供前端判断是否有未保存修改）==========

    @rx.var
    def has_unsaved_changes(self) -> bool:
        """是否有未保存的修改"""
        return (self.draft_channel_id != self.selected_channel_id or
                self.draft_enabled != self.is_enabled)