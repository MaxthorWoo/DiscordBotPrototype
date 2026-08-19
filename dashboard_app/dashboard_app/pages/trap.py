import reflex as rx
from ..state import TrapState
from ..components.sidebar import page_shell, with_sidebar

@rx.page(route="/trap", on_load=TrapState.load_data)
def trap_page() -> rx.Component:
    return with_sidebar(
        rx.fragment(
            page_shell(
                "机器账号陷阱",

            # ========== 配置卡片 ==========
            rx.card(
                rx.vstack(
                    # 开关（绑定草稿状态）
                    rx.hstack(
                        rx.text("启用陷阱功能", font_weight="bold"),
                        rx.switch(
                            checked=TrapState.draft_enabled,
                            on_change=TrapState.set_draft_enabled,
                            cursor="pointer",
                        ),
                        justify="between",
                        width="100%"
                    ),
                    # 下拉菜单（绑定草稿状态）
                    rx.hstack(
                        rx.text("选择陷阱频道", font_weight="bold"),
                        rx.select.root(
                            rx.select.trigger(placeholder="请选择文字频道"),
                            rx.select.content(
                                rx.select.group(
                                    rx.foreach(
                                        TrapState.available_channels,
                                        lambda channel: rx.select.item(channel.channel_name, value=channel.channel_id)
                                    )
                                )
                            ),
                            value=TrapState.draft_channel_id,
                            on_change=TrapState.set_draft_channel,
                            width="100%",
                            cursor="pointer",
                        ),
                        justify="between",
                        width="100%"
                    ),
                    # ========== 操作按钮 ==========
                    rx.hstack(
                        rx.button(
                            "保存配置",
                            on_click=TrapState.save_config,
                            color_scheme="green",
                            disabled=~TrapState.has_unsaved_changes,
                            cursor="pointer",
                        ),
                        rx.button(
                            "↩取消修改",
                            on_click=TrapState.cancel_edit,
                            color_scheme="gray",
                            disabled=~TrapState.has_unsaved_changes,
                            cursor="pointer",
                        ),
                        spacing="2",
                        justify="end",
                        width="100%"
                    ),
                    # 有未保存修改时提示（仅当存在草稿变更时显示）
                    rx.cond(
                        TrapState.has_unsaved_changes,
                        rx.text("⚠️ 有未保存的修改", color="orange", font_size="sm"),
                    ),
                    spacing="2",
                    width="100%"
                ),
                width="100%"
            ),

            rx.divider(),
            rx.heading("踢人日志", size="5"),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("用户"),
                        rx.table.column_header_cell("频道"),
                        rx.table.column_header_cell("时间"),
                        rx.table.column_header_cell("原因")
                    )
                ),
                rx.table.body(
                    rx.cond(
                        TrapState.kick_logs,
                        rx.foreach(
                            TrapState.kick_logs,
                            lambda log: rx.table.row(
                                rx.table.cell(log["user_name"]),
                                rx.table.cell(log["channel_name"]),
                                rx.table.cell(log["kicked_at"]),
                                rx.table.cell(log["reason"])
                            )
                        ),
                        rx.table.row(
                            rx.table.cell("暂无踢人记录", col_span=4, text_align="center")
                        )
                    )
                ),
                width="100%"
            ),
        ),
        # 保存提示飘字（短暂闪现，2 秒后自动消失）
        rx.cond(
            TrapState.save_toast != "",
            rx.box(
                rx.text(TrapState.save_toast, font_size="sm", color="white"),
                position="fixed",
                top="1em",
                right="1em",
                z_index="9999",
                padding="0.6em 1.2em",
                border_radius="md",
                background="var(--green-9)",
                box_shadow="0 2px 8px rgba(0,0,0,0.2)",
            ),
        ),
        ),
    )