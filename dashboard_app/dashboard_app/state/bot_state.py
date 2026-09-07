"""当前机器人状态管理"""
import asyncio
import reflex as rx
from shared_lib import crud
import aiohttp


class BotState(rx.State):
    """管理平台当前选择的 Bot（全局单一事实源）"""

    # ---- Bot 基本信息 ----
    current_bot_id: str = crud.DEFAULT_BOT_ID
    bot_name: str = ""
    has_token: bool = False
    is_active: bool = False

    # ---- Bot 列表（所有机器人，含状态，供切换与启停）----
    bots_list: list[dict] = []   # 每项含 bot_id / bot_name / status / has_token

    # ---- Token 掩码（已配置时显示，避免明文泄露）----
    token_mask: str = ""         # 非空表示“已配置 Token”

    # ---- Bot 设置页表单（公开字段，需同步到前端）----
    bot_name_input: str = ""
    bot_token_input: str = ""
    # 逐字段行内编辑：名称行 / Token 行各自独立切换
    editing_name: bool = False
    editing_token: bool = False
    save_toast: str = ""
    test_result: str = ""   # "" | "success" | "failed" | "testing"
    test_message: str = ""

    # ---- Sidebar 用 ----
    sidebar_bot_name: str = ""

    # ---- 统一机器人管理弹窗 ----
    show_manager: bool = False

    # ---- 新增 Bot（二级弹窗）----
    show_add_dialog: bool = False
    add_name_input: str = ""
    add_token_input: str = ""
    add_toast: str = ""

    is_loaded: bool = False

    def open_settings(self):
        """设置图标：打开统一机器人管理弹窗"""
        self.show_manager = True
        return BotState.load_bots

    async def load_bots(self):
        """加载所有机器人列表（含状态与错误）到 bots_list，并确保 current_bot_id 有效"""
        bots = crud.get_all_bots()  # [(bot_id, bot_name), ...] 含未激活
        items = []
        for bot_id, bot_name in (bots or []):
            st = crud.get_bot_status(bot_id)
            status = self._status_of(st)
            items.append({
                "bot_id": bot_id,
                "bot_name": bot_name,
                "status": status,
                "error": st.get("last_error") or "",
            })
        self.bots_list = items
        if self.bots_list and self.current_bot_id not in [b["bot_id"] for b in self.bots_list]:
            self.current_bot_id = self.bots_list[0]["bot_id"]
            await self.load_bot()

    def _status_of(self, st: dict) -> str:
        """返回单个机器人的状态：unconfigured / stopped / online / offline / error"""
        if st.get("last_error"):
            return "error"
        if not st.get("configured"):
            return "unconfigured"
        if not st.get("active"):
            return "stopped"
        return "online" if st.get("online") else "offline"

    async def select_bot(self, bot_id: str):
        """切换当前管理的机器人（全局生效）：用于管理弹窗点击列表项"""
        self.current_bot_id = bot_id
        await self.load_bot()
        # 若目标机器人已配置 Token，切换即视为“启动”（确保它能上线）
        if self.has_token and not self.is_active:
            crud.set_bot_active(bot_id, True)
            self.is_active = True

    async def start_bot(self, bot_id: str):
        """启动一个机器人（标记 active，run.py 热加载会自动拉起进程）"""
        ok = crud.set_bot_active(bot_id, True)
        if ok:
            await self.load_bots()
            if bot_id == self.current_bot_id:
                self.is_active = True
        else:
            self.add_toast = "无法启动：请先配置 Token"
            await asyncio.sleep(2)
            self.add_toast = ""

    async def stop_bot(self, bot_id: str):
        """停止一个机器人（标记 inactive，run.py 会终止对应进程）"""
        ok = crud.set_bot_active(bot_id, False)
        if ok:
            await self.load_bots()
            if bot_id == self.current_bot_id:
                self.is_active = False

    def open_manager(self):
        """打开统一机器人管理弹窗并刷新列表与编辑区"""
        self.show_manager = True
        return BotState.load_bots

    def close_manager(self):
        self.show_manager = False
        self.test_result = ""
        self.test_message = ""

    def handle_manager_change(self, is_open: bool):
        if not is_open:
            self.show_manager = False
            self.test_result = ""
            self.test_message = ""

    # ── 新增 Bot（二级弹窗）──
    def open_add_dialog(self):
        """打开新增机器人二级弹窗，并清空表单"""
        self.add_name_input = ""
        self.add_token_input = ""
        self.add_toast = ""
        self.show_add_dialog = True

    def set_add_name(self, val: str):
        self.add_name_input = val

    def set_add_token(self, val: str):
        self.add_token_input = val

    def add_dialog_open_change(self, is_open: bool):
        """二级弹窗开关变化：关闭时重置表单"""
        if not is_open:
            self.cancel_add()

    def cancel_add(self):
        self.show_add_dialog = False
        self.add_name_input = ""
        self.add_token_input = ""
        self.add_toast = ""

    async def confirm_add(self):
        """二级弹窗确认：创建机器人，关闭二级弹窗并刷新一级列表"""
        name = self.add_name_input.strip()
        if not name:
            self.add_toast = "请输入机器人名称"
            yield
            await asyncio.sleep(2)
            self.add_toast = ""
            return

        bot_id = crud.create_bot(name)
        if not bot_id:
            self.add_toast = "创建失败，请稍后重试"
            yield
            await asyncio.sleep(2)
            self.add_toast = ""
            return

        # 若填写了 Token，先验证再写入
        token = self.add_token_input.strip()
        if token:
            self.add_toast = "正在验证 Token..."
            yield
            valid = await self._verify_token(token)
            if not valid:
                self.add_toast = "Token 验证失败，请检查后重试"
                await asyncio.sleep(2)
                return

        if token:
            crud.update_bot(bot_id, name, token)

        await self.load_bots()           # 刷新一级弹窗的机器人列表
        self.show_add_dialog = False
        self.add_name_input = ""
        self.add_token_input = ""
        self.add_toast = ""
        yield

    async def load_bot(self):
        """加载当前 Bot 信息"""
        info = crud.get_bot(self.current_bot_id)
        if info:
            self.bot_name = info["bot_name"]
            self.has_token = info["has_token"]
            self.is_active = info["is_active"]
            self.sidebar_bot_name = info["bot_name"]
            self.bot_name_input = info["bot_name"] if info["bot_name"] != "未配置" else ""
            self.bot_token_input = ""
            self.editing_name = False
            self.editing_token = False
            self.token_mask = "••••••••" if info.get("has_token") else ""
        self.is_loaded = True

    def edit_name(self):
        """进入名称行内编辑：文字 -> 输入框"""
        self.editing_name = True

    def cancel_name(self):
        """取消名称编辑，还原输入框内容"""
        self.editing_name = False
        self.bot_name_input = self.bot_name
        self.save_toast = ""

    async def save_name(self):
        """仅保存名称（无需验证 Token）"""
        name = self.bot_name_input.strip()
        if not name:
            self.save_toast = "请输入 Bot 名称"
            yield
            await asyncio.sleep(2)
            self.save_toast = ""
            return
        ok = crud.update_bot(self.current_bot_id, name, "")
        if ok:
            self.editing_name = False
            await self.load_bot()
            await self.load_bots()   # 刷新列表名称
        else:
            self.save_toast = "保存失败"
        yield
        await asyncio.sleep(2)
        self.save_toast = ""

    def edit_token(self):
        """进入 Token 行内编辑：文字 -> 输入框"""
        self.editing_token = True

    def cancel_token(self):
        """取消 Token 编辑"""
        self.editing_token = False
        self.bot_token_input = ""
        self.test_result = ""
        self.test_message = ""
        self.save_toast = ""

    def set_bot_name(self, val: str):
        self.bot_name_input = val

    def set_bot_token(self, val: str):
        self.bot_token_input = val
        self.test_result = ""
        self.test_message = ""

    async def save_token(self):
        """行内保存 Token：需先验证有效性，成功后刷新并回到展示态"""
        token = self.bot_token_input.strip()
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
            self.bot_name,      # 名称不变，仅更新 Token
            token,
        )
        if ok:
            self.save_toast = "保存成功，Bot 已激活" if token else "保存成功"
            self.bot_token_input = ""
            self.editing_token = False
            await self.load_bot()
            await self.load_bots()      # 刷新列表
            self.test_result = ""
            self.test_message = ""
        else:
            self.save_toast = "保存失败"

        yield
        await asyncio.sleep(2)
        self.save_toast = ""

    async def test_connection(self):
        """单独测试 Token 连接"""
        token = self.bot_token_input.strip()
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
