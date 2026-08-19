"""当前机器人状态管理"""
import asyncio
import reflex as rx
from shared_lib import crud
import aiohttp


class BotState(rx.State):
    """管理平台当前选择的 Bot"""

    # ---- Bot 基本信息 ----
    current_bot_id: str = crud.DEFAULT_BOT_ID
    bot_name: str = ""
    has_token: bool = False
    is_active: bool = False

    # ---- Bot 设置页表单 ----
    _bot_name_input: str = ""
    _bot_token_input: str = ""
    save_toast: str = ""
    test_result: str = ""   # "" | "success" | "failed" | "testing"
    test_message: str = ""

    # ---- Sidebar 用 ----
    sidebar_bot_name: str = ""

    # ---- 设置弹窗 ----
    show_settings: bool = False

    is_loaded: bool = False

    def open_settings(self):
        """打开设置弹窗并加载 Bot 信息"""
        self.show_settings = True
        return BotState.load_bot

    def close_settings(self):
        """关闭设置弹窗"""
        self.show_settings = False
        self.test_result = ""
        self.test_message = ""

    def handle_settings_change(self, is_open: bool):
        """仅在弹窗被关闭时（点遮罩/Esc/取消）重置状态"""
        if not is_open:
            self.show_settings = False
            self.test_result = ""
            self.test_message = ""

    async def load_bot(self):
        """加载当前 Bot 信息"""
        info = crud.get_bot(self.current_bot_id)
        if info:
            self.bot_name = info["bot_name"]
            self.has_token = info["has_token"]
            self.is_active = info["is_active"]
            self.sidebar_bot_name = info["bot_name"]
            self._bot_name_input = info["bot_name"] if info["bot_name"] != "未配置" else ""
            self._bot_token_input = ""
        self.is_loaded = True

    def set_bot_name(self, val: str):
        self._bot_name_input = val

    def set_bot_token(self, val: str):
        self._bot_token_input = val
        self.test_result = ""
        self.test_message = ""

    async def save_bot(self):
        """保存 Bot 设置到数据库，填写 Token 时需先验证"""
        if not self._bot_name_input.strip():
            self.save_toast = "请输入 Bot 名称"
            yield
            await asyncio.sleep(2)
            self.save_toast = ""
            return

        token = self._bot_token_input.strip()
        if token:
            # 填写了 Token，需验证
            self.test_result = "testing"
            self.test_message = "正在验证 Token..."
            yield
            valid = await self._verify_token(token)
            if not valid:
                self.save_toast = "Token 验证失败，请检查后重试"
                self.test_result = "failed"
                self.test_message = "Token 无效"
                yield
                await asyncio.sleep(2)
                self.save_toast = ""
                return

        ok = crud.update_bot(
            self.current_bot_id,
            self._bot_name_input.strip(),
            token,
        )
        if ok:
            self.save_toast = "保存成功，Bot 已激活" if token else "保存成功"
            self._bot_token_input = ""
            await self.load_bot()
            self.test_result = ""
            self.test_message = ""
            self.show_settings = False  # 保存成功后关闭弹窗
        else:
            self.save_toast = "保存失败"

        yield
        await asyncio.sleep(2)
        self.save_toast = ""

    async def test_connection(self):
        """单独测试 Token 连接"""
        token = self._bot_token_input.strip()
        if not token:
            self.test_result = "failed"
            self.test_message = "请先输入 Token"
            return

        self.test_result = "testing"
        self.test_message = "正在测试连接..."
        yield

        ok = await self._verify_token(token)
        if ok:
            self.test_result = "success"
            self.test_message = "连接成功"
        else:
            self.test_result = "failed"
            self.test_message = "连接失败，请检查 Token"

    async def _verify_token(self, token: str) -> bool:
        """向 Discord API 验证 Token 有效性"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False
