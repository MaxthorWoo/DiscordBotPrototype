import reflex as rx
from ..state import GiftCodeState, BotState
from ..components.sidebar import page_shell, with_sidebar


# ========== 辅助：渲染状态徽章 ==========
def status_badge(is_active: bool) -> rx.Component:
    return rx.cond(
        is_active,
        rx.badge("启用", color_scheme="green"),
        rx.badge("停用", color_scheme="gray"),
    )


# ========== 创建批次卡片 ==========
def create_batch_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("创建新批次", size="4"),
            rx.input(
                placeholder="批次名称（如：万圣节活动）",
                value=GiftCodeState.new_batch_name,
                on_change=GiftCodeState.set_new_batch_name,
                width="100%",
            ),
            rx.input(
                placeholder="口令（如：halloween，用户输入 /code halloween 领取）",
                value=GiftCodeState.new_command_text,
                on_change=GiftCodeState.set_new_command_text,
                width="100%",
            ),
            rx.text(
                "填写批次名称和口令后，选择 xlsx 文件自动上传",
                font_size="xs",
                color="gray",
            ),
            # 没有显示列选择器时，显示上传按钮
            rx.cond(
                ~GiftCodeState.show_column_selector,
                rx.upload(
                    rx.button(
                        rx.cond(
                            GiftCodeState.is_uploading,
                            "上传中...",
                            "选择 xlsx 文件并上传",
                        ),
                        color_scheme="blue",
                        cursor="pointer",
                        disabled=GiftCodeState.is_uploading,
                    ),
                    accept={
                        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    },
                    max_files=1,
                    multiple=False,
                    on_drop=GiftCodeState.handle_upload,
                ),
            ),
            # 显示列选择器
            rx.cond(
                GiftCodeState.show_column_selector,
                rx.vstack(
                    rx.text(
                        "请选择包含礼包码的那一列：",
                        font_weight="bold",
                        font_size="sm",
                    ),
                    # 列选择按钮组
                    rx.text(
                        "点击列名选择：",
                        font_size="xs",
                        color="gray",
                    ),
                    rx.hstack(
                        rx.foreach(
                            GiftCodeState.upload_col_labels,
                            lambda label, idx: rx.button(
                                label,
                                size="1",
                                font_size="xs",
                                color_scheme=rx.cond(
                                    GiftCodeState.selected_col_index == idx + 1,
                                    "green",
                                    "gray",
                                ),
                                variant=rx.cond(
                                    GiftCodeState.selected_col_index == idx + 1,
                                    "solid",
                                    "outline",
                                ),
                                cursor="pointer",
                                on_click=GiftCodeState.select_column(idx + 1),
                            ),
                        ),
                        spacing="1",
                        flex_wrap="wrap",
                    ),
                    rx.hstack(
                        rx.button(
                            "确认创建批次",
                            color_scheme="green",
                            cursor="pointer",
                            disabled=GiftCodeState.is_uploading,
                            on_click=GiftCodeState.confirm_create_batch,
                        ),
                        rx.button(
                            "取消",
                            color_scheme="gray",
                            variant="soft",
                            cursor="pointer",
                            on_click=GiftCodeState.cancel_column_selector,
                        ),
                        spacing="2",
                    ),
                    spacing="2",
                    width="100%",
                    padding="0.5em",
                    border="1px solid var(--accent-8)",
                    border_radius="md",
                ),
            ),
            rx.cond(
                GiftCodeState.upload_status != "",
                rx.text(
                    GiftCodeState.upload_status,
                    color=rx.cond(
                        GiftCodeState.upload_status.contains("成功"),
                        "green",
                        "orange",
                    ),
                    font_size="sm",
                ),
            ),
            rx.text(
                "文件要求：xlsx 格式，第一行必须包含列名",
                font_size="xs",
                color="gray",
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
    )


# ========== 批次列表卡片 ==========
def batch_list_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("礼包码批次", size="4"),
            rx.cond(
                GiftCodeState.batches,
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("批次名称"),
                            rx.table.column_header_cell("口令"),
                            rx.table.column_header_cell("进度"),
                            rx.table.column_header_cell("状态"),
                            rx.table.column_header_cell("创建时间"),
                            rx.table.column_header_cell("操作"),
                        )
                    ),
                    rx.table.body(
                        rx.foreach(
                            GiftCodeState.batches,
                            lambda b: rx.table.row(
                                rx.table.cell(
                                    rx.text(b.batch_name, font_weight="bold"),
                                ),
                                rx.table.cell(
                                    rx.code(f"/code {b.command_text}"),
                                ),
                                rx.table.cell(
                                    f"{b.claimed_count} / {b.total_count}"
                                ),
                                rx.table.cell(status_badge(b.is_active)),
                                rx.table.cell(b.created_at),
                                rx.table.cell(
                                    rx.hstack(
                                        rx.button(
                                            "查看",
                                            size="1",
                                            color_scheme="blue",
                                            cursor="pointer",
                                            on_click=GiftCodeState.view_batch_detail(b.id),
                                        ),
                                        rx.button(
                                            rx.cond(b.is_active, "停用", "启用"),
                                            size="1",
                                            color_scheme=rx.cond(b.is_active, "yellow", "green"),
                                            cursor="pointer",
                                            on_click=GiftCodeState.toggle_batch(b.id, ~b.is_active),
                                        ),
                                        rx.button(
                                            "删除",
                                            size="1",
                                            color_scheme="red",
                                            cursor="pointer",
                                            on_click=GiftCodeState.delete_batch(b.id),
                                        ),
                                        spacing="1",
                                    ),
                                ),
                            ),
                        ),
                    ),
                    width="100%",
                ),
                rx.text("暂无批次，请在下方创建一个", color="gray"),
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
    )


# ========== 批次详情弹窗 ==========
def batch_detail_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.hstack(
                    rx.text(f"批次详情 — {GiftCodeState.batch_detail.batch_name}"),
                    status_badge(GiftCodeState.batch_detail.is_active),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.icon_button("x", variant="ghost", color_scheme="gray", cursor="pointer"),
                    ),
                    align="center",
                ),
            ),
            rx.dialog.description(
                rx.vstack(
                    # 统计信息
                    rx.hstack(
                        rx.text(f"口令: ", font_weight="bold"),
                        rx.code(GiftCodeState.batch_detail.command_text),
                        rx.text(f"  |  进度: {GiftCodeState.batch_detail.claimed_count}/{GiftCodeState.batch_detail.total_count}"),
                        spacing="2",
                        align="center",
                        font_size="1",
                    ),
                    rx.divider(),
                    # 礼包码明细
                    rx.heading("礼包码明细", size="3"),
                    rx.cond(
                        GiftCodeState.batch_detail.codes,
                        rx.box(
                            rx.table.root(
                                rx.table.header(
                                    rx.table.row(
                                        rx.table.column_header_cell("#", width="5%"),
                                        rx.table.column_header_cell("礼包码", width="30%"),
                                        rx.table.column_header_cell("状态", width="12%"),
                                        rx.table.column_header_cell("领取人", width="25%"),
                                        rx.table.column_header_cell("领取时间", width="28%"),
                                    )
                                ),
                                rx.table.body(
                                    rx.foreach(
                                        GiftCodeState.batch_detail.codes,
                                        lambda c, idx: rx.table.row(
                                            rx.table.cell(idx + 1),
                                            rx.table.cell(rx.code(c.code)),
                                            rx.table.cell(
                                                rx.cond(
                                                    c.is_claimed,
                                                    rx.badge("已领取", color_scheme="green"),
                                                    rx.badge("未领取", color_scheme="gray"),
                                                ),
                                            ),
                                            rx.table.cell(c.claimed_by_user_name),
                                            rx.table.cell(c.claimed_at),
                                        ),
                                    ),
                                ),
                                width="100%",
                                style={"tableLayout": "fixed"},
                            ),
                            width="100%",
                            max_height="260px",
                            overflow_y="auto",
                        ),
                        rx.text("无礼包码数据"),
                    ),
                    rx.divider(),
                    # 领取日志
                    rx.heading("领取日志", size="3"),
                    rx.cond(
                        GiftCodeState.claim_logs,
                        rx.box(
                            rx.table.root(
                                rx.table.header(
                                    rx.table.row(
                                        rx.table.column_header_cell("用户", width="25%"),
                                        rx.table.column_header_cell("礼包码", width="30%"),
                                        rx.table.column_header_cell("频道", width="25%"),
                                        rx.table.column_header_cell("时间", width="20%"),
                                    )
                                ),
                                rx.table.body(
                                    rx.foreach(
                                        GiftCodeState.claim_logs,
                                        lambda log: rx.table.row(
                                            rx.table.cell(log["user_name"]),
                                            rx.table.cell(rx.code(log["code"])),
                                            rx.table.cell(log["channel_name"]),
                                            rx.table.cell(log["claimed_at"]),
                                        ),
                                    ),
                                ),
                                width="100%",
                                style={"tableLayout": "fixed"},
                            ),
                            width="100%",
                            max_height="260px",
                            overflow_y="auto",
                        ),
                        rx.text("暂无领取记录", color="gray"),
                    ),
                    spacing="3",
                    width="100%",
                ),
                width="100%",
            ),
            max_width="700px",
        ),
        open=GiftCodeState.detail_modal_open,
        on_open_change=GiftCodeState.on_detail_dialog_change,
    )


# ========== 主页面 ==========
@rx.page(route="/giftcodes", on_load=GiftCodeState.load_data)
def giftcode_page() -> rx.Component:
    return with_sidebar(
        page_shell(
            "礼包码管理",
            f"当前操作机器人: {BotState.current_bot_id}",

            # 创建批次
            create_batch_card(),

            # 批次列表
            batch_list_card(),

            # 批次详情弹窗
            batch_detail_dialog(),
        )
    )
