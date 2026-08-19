"""机器人消息模板配置 State"""
import asyncio
import reflex as rx
from shared_lib import crud
from .bot_state import BotState


class MessageState(rx.State):
    """管理机器人所有可自定义的消息模板"""

    messages: list[dict] = []
    editing_key: str = ""       # 当前选中/编辑的消息 key
    edit_value: str = ""        # 编辑框中的文本
    toast_text: str = ""        # 飘字提示文字
    is_loaded: bool = False

    editing_display_name: str = ""  # 当前选中消息的中文名（前端展示）
    selected_var_lines: list[dict[str, str]] = []  # 变量解释行 [{name, desc}]（前端展示）

    async def load_data(self, prefix: str | tuple[str, ...] = ""):
        """加载消息模板；prefix 非空时只加载匹配的模板（单个前缀或前缀元组）"""
        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id
        all_msgs = crud.get_all_bot_messages(bot_id)
        if prefix:
            if isinstance(prefix, tuple):
                prefixes = prefix
                all_msgs = [
                    m for m in all_msgs
                    if any(m["message_key"].startswith(p) for p in prefixes)
                ]
            else:
                all_msgs = [
                    m for m in all_msgs
                    if m["message_key"].startswith(prefix)
                ]
        self.messages = all_msgs
        self.is_loaded = True

    def begin_edit(self, key: str):
        """点击左侧列表项，右侧打开编辑面板"""
        self.toast_text = ""  # 切换时清除旧飘字
        for m in self.messages:
            if m["message_key"] == key:
                self.editing_key = key
                self.edit_value = m["message_text"]
                self.editing_display_name = m.get("display_name", key)
                # 生成变量解释行（保持 variables 字段中的顺序）
                var_desc = m.get("variable_descriptions", {})
                self.selected_var_lines = []
                for var_name in (m.get("variables", "") or "").split(","):
                    var_name = var_name.strip()
                    if var_name:
                        self.selected_var_lines.append({
                            "name": var_name,
                            "desc": var_desc.get(var_name, ""),
                        })
                break

    def cancel_edit(self):
        """取消选择"""
        self.editing_key = ""
        self.edit_value = ""
        self.editing_display_name = ""
        self.selected_var_lines = []

    def set_edit_value(self, value: str):
        self.edit_value = value

    async def save_message(self):
        """保存当前编辑的消息，编辑面板保持不变"""
        if not self.editing_key:
            return

        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id

        if crud.update_bot_message(bot_id, self.editing_key, self.edit_value):
            await self.load_data()
            self.toast_text = f"「{self.editing_key}」保存成功"
        else:
            self.toast_text = "保存失败，请稍后重试"

        # 2 秒后自动消失
        yield
        await asyncio.sleep(2)
        self.toast_text = ""

    async def reset_message(self, key: str):
        """重置某条消息为默认值"""
        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id
        default = crud.reset_bot_message(bot_id, key)
        if default is not None:
            self.edit_value = default
            await self.load_data()
            self.toast_text = f"「{key}」已重置为默认值"
        else:
            self.toast_text = "重置失败"

        yield
        await asyncio.sleep(2)
        self.toast_text = ""
