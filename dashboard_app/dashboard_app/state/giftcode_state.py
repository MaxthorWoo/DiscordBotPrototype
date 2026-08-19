import reflex as rx
from typing import Any
from pydantic import BaseModel
from shared_lib import crud
from .bot_state import BotState


class BatchInfo(BaseModel):
    """批次列表项"""
    id: int = 0
    batch_name: str = ""
    command_text: str = ""
    total_count: int = 0
    claimed_count: int = 0
    is_active: bool = False
    created_at: str = ""


class CodeInfo(BaseModel):
    """单条礼包码"""
    id: int = 0
    code: str = ""
    is_claimed: bool = False
    claimed_by_user_name: str = ""
    claimed_at: str = ""


class BatchDetail(BaseModel):
    """批次详情"""
    id: int = 0
    batch_name: str = ""
    command_text: str = ""
    total_count: int = 0
    claimed_count: int = 0
    is_active: bool = False
    created_at: str = ""
    codes: list[CodeInfo] = []


class GiftCodeState(rx.State):
    # ========== 批次列表 ==========
    batches: list[BatchInfo] = []

    # ========== 选中批次详情（弹窗） ==========
    selected_batch_id: int = 0
    batch_detail: BatchDetail = BatchDetail()
    detail_modal_open: bool = False    # 详情弹窗开关
    claim_logs: list[dict[str, Any]] = []

    # ========== 创建表单 ==========
    new_batch_name: str = ""
    new_command_text: str = ""
    upload_status: str = ""
    is_uploading: bool = False

    # ========== 上传两步流程：预览列 ==========
    upload_columns: list[str] = []          # xlsx 第一行列名
    upload_col_labels: list[str] = []       # 预计算标签 ["A: 礼包id", "B: 激活码", ...]
    selected_col_index: int = 1             # 用户选择的列（1-based）
    show_column_selector: bool = False      # 是否显示列选择器

    # ========== 内部状态 ==========
    _guild_id: str = ""
    _uploaded_file_bytes: bytes = b""       # 暂存上传的文件字节

    # ========== 表单字段 Setter（遵循 trap_state 模式：显式定义） ==========

    def set_new_batch_name(self, value: str):
        self.new_batch_name = value

    def set_new_command_text(self, value: str):
        self.new_command_text = value

    def select_column(self, idx: int):
        """选择一个列（1-based index）"""
        self.selected_col_index = idx

    def cancel_column_selector(self):
        """取消列选择，返回上传步骤"""
        self.show_column_selector = False
        self._uploaded_file_bytes = b""
        self.upload_columns = []
        self.upload_col_labels = []
        self.upload_status = ""

    # ========== 生命周期 ==========

    async def load_data(self):
        """页面加载时获取数据"""
        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id

        guilds = crud.get_guilds(bot_id)
        if guilds:
            self._guild_id = guilds[0]["guild_id"]
        else:
            self._guild_id = ""
            self.batches = []
            return

        # 加载批次列表
        await self._refresh_batches(bot_id)
        # 清除选中状态
        self.selected_batch_id = 0
        self.batch_detail = BatchDetail()
        self.detail_modal_open = False
        self.claim_logs = []

    async def _refresh_batches(self, bot_id: str = None):
        """刷新批次列表"""
        if bot_id is None:
            bot_state = await self.get_state(BotState)
            bot_id = bot_state.current_bot_id
        if not self._guild_id:
            return
        raw = crud.get_gift_code_batches(bot_id, self._guild_id)
        self.batches = [
            BatchInfo(
                id=b["id"],
                batch_name=b["batch_name"],
                command_text=b["command_text"],
                total_count=b["total_count"],
                claimed_count=b["claimed_count"],
                is_active=b["is_active"],
                created_at=b["created_at"],
            )
            for b in raw
        ]

    # ========== 查看批次详情 ==========

    async def view_batch_detail(self, batch_id: int):
        """点击批次查看详情"""
        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id

        self.selected_batch_id = batch_id

        # 加载批次详情
        detail = crud.get_batch_detail(batch_id)
        if detail:
            self.batch_detail = BatchDetail(
                id=detail["id"],
                batch_name=detail["batch_name"],
                command_text=detail["command_text"],
                total_count=detail["total_count"],
                claimed_count=detail["claimed_count"],
                is_active=detail["is_active"],
                created_at=detail["created_at"],
                codes=[
                    CodeInfo(
                        id=c["id"],
                        code=c["code"],
                        is_claimed=c["is_claimed"],
                        claimed_by_user_name=c["claimed_by_user_name"],
                        claimed_at=c["claimed_at"],
                    )
                    for c in detail["codes"]
                ],
            )
            self.detail_modal_open = True
        else:
            self.batch_detail = BatchDetail()
            self.detail_modal_open = False

        # 加载领取日志
        self.claim_logs = crud.get_claim_logs_for_batch(
            bot_id, self._guild_id, batch_id
        )

    async def on_detail_dialog_change(self, open: bool):
        """弹窗关闭时清除选中批次。open=True 由 view_batch_detail 触发。"""
        self.detail_modal_open = open
        if not open:
            self.selected_batch_id = 0
            self.batch_detail = BatchDetail()
            self.claim_logs = []

    # ========== 上传 xlsx 两步流程 ==========

    async def handle_upload(self, files: list[rx.UploadFile]):
        """步骤1：上传文件，读取列名供用户选择"""
        if not files:
            self.upload_status = "请选择一个 xlsx 文件"
            return

        if not self.new_batch_name.strip():
            self.upload_status = "请输入批次名称"
            return

        if not self.new_command_text.strip():
            self.upload_status = "请输入口令"
            return

        self.is_uploading = True
        self.upload_status = "正在读取文件..."

        try:
            file = files[0]
            file_bytes = await file.read()
            self._uploaded_file_bytes = file_bytes

            # 读取列名
            columns = crud.read_xlsx_headers(file_bytes)
            if not columns:
                self.upload_status = "文件中没有检测到列名，请检查文件格式（第一行应是列名）"
                self.is_uploading = False
                return

            self.upload_columns = columns
            self.upload_col_labels = [
                f"{chr(65 + i)}: {name}" for i, name in enumerate(columns)
            ]
            self.selected_col_index = 1
            self.show_column_selector = True
            self.upload_status = f"检测到 {len(columns)} 列，请选择包含礼包码的列"
            self.is_uploading = False

        except Exception as e:
            self.upload_status = f"读取文件失败: {str(e)}"
            self.is_uploading = False
            self.show_column_selector = False

    async def confirm_create_batch(self):
        """步骤2：用户确认列后，解析并创建批次"""
        if not self._uploaded_file_bytes:
            self.upload_status = "请先上传文件"
            return

        if not self.show_column_selector:
            return

        bot_state = await self.get_state(BotState)
        bot_id = bot_state.current_bot_id

        self.is_uploading = True
        self.upload_status = "正在解析礼包码..."

        try:
            # 用选中的列解析
            codes = crud.parse_codes_from_xlsx(
                self._uploaded_file_bytes, col_index=self.selected_col_index
            )

            if not codes:
                col_name = (
                    self.upload_columns[self.selected_col_index - 1]
                    if self.selected_col_index <= len(self.upload_columns)
                    else f"第{self.selected_col_index}列"
                )
                self.upload_status = f"从「{col_name}」未能解析到礼包码，请确认选择的列是否正确"
                self.is_uploading = False
                return

            # 创建批次
            result = crud.create_gift_code_batch(
                bot_id=bot_id,
                guild_id=self._guild_id,
                batch_name=self.new_batch_name.strip(),
                command_text=self.new_command_text.strip().lower(),
                codes=codes,
            )

            self.upload_status = result["message"]

            if result["success"]:
                # 清空表单和临时状态
                self.new_batch_name = ""
                self.new_command_text = ""
                self._uploaded_file_bytes = b""
                self.upload_columns = []
                self.upload_col_labels = []
                self.show_column_selector = False
                # 刷新列表
                await self._refresh_batches(bot_id)

        except Exception as e:
            self.upload_status = f"创建失败: {str(e)}"
        finally:
            self.is_uploading = False

    # ========== 批次操作 ==========

    async def toggle_batch(self, batch_id: int, enabled: bool):
        """启用/停用批次"""
        crud.toggle_batch_status(batch_id, enabled)
        bot_state = await self.get_state(BotState)
        await self._refresh_batches(bot_state.current_bot_id)
        # 如果在查看该批次的详情，也刷新详情
        if self.selected_batch_id == batch_id:
            await self.view_batch_detail(batch_id)

    async def delete_batch(self, batch_id: int):
        """删除批次"""
        crud.delete_batch(batch_id)
        bot_state = await self.get_state(BotState)
        await self._refresh_batches(bot_state.current_bot_id)
        if self.selected_batch_id == batch_id:
            self.selected_batch_id = 0
            self.batch_detail = BatchDetail()
            self.detail_modal_open = False
            self.claim_logs = []
