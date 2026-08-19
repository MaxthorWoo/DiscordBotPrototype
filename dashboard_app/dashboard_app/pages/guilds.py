import reflex as rx
from ..state import GuildState
from ..components.sidebar import page_shell, with_sidebar


# ===== 机器人状态卡片 =====
def _status_dot(online: bool) -> rx.Component:
    """在线/离线状态圆点"""
    return rx.box(
        width="10px",
        height="10px",
        border_radius="full",
        background=rx.cond(online, "var(--green-9)", "var(--red-9)"),
    )


def _status_row(label: str, value_component) -> rx.Component:
    return rx.hstack(
        rx.text(label, color="gray", font_size="sm", width="110px"),
        value_component,
        width="100%",
    )


def bot_status_card() -> rx.Component:
    """机器人运行状态卡片（可点击 → 服务器列表明细）"""
    return rx.card(
        rx.vstack(
            rx.hstack(
                _status_dot(GuildState.bot_status.online),
                rx.heading(
                    rx.cond(
                        GuildState.bot_status.online,
                        "🟢 机器人在线",
                        "🔴 机器人离线",
                    ),
                    size="4",
                ),
                rx.spacer(),
                rx.icon("chevron-right", size=16, color="gray"),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.divider(),
            rx.vstack(
                _status_row("机器人名称", GuildState.bot_status.bot_name),
                _status_row("Token 配置", rx.cond(GuildState.bot_status.configured, "✅ 已配置", "❌ 未配置")),
                _status_row("延迟", rx.cond(
                    GuildState.bot_status.latency_ms != None,
                    rx.text(GuildState.bot_status.latency_ms.to(str) + " ms"),
                    rx.text("—"),
                )),
                _status_row("上线时长", GuildState.bot_status.uptime_hours.to(str) + " 小时"),
                _status_row("最近心跳", rx.cond(
                    GuildState.bot_status.last_seen != "",
                    GuildState.bot_status.last_seen,
                    rx.text("从未上报"),
                )),
                _status_row("已加入服务器", GuildState.bot_status.guild_count.to(str) + " 个"),
                spacing="2",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
        cursor="pointer",
        on_click=GuildState.open_detail("guilds"),
    )


# ===== 业务汇总卡片 =====
def _stat_card(icon: str, label: str, value, on_click, color: str = "var(--accent-9)") -> rx.Component:
    """可点击的统计卡片，带「查看」角标"""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.icon(icon, size=24, color=color),
                rx.vstack(
                    rx.heading(value, size="5"),
                    rx.text(label, font_size="xs", color="gray"),
                    spacing="0",
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            rx.hstack(
                rx.spacer(),
                rx.badge("查看", variant="soft", size="1", color_scheme="gray"),
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
        cursor="pointer",
        on_click=on_click,
    )


def summary_grid() -> rx.Component:
    """顶部业务统计卡片网格（每个可点击打开对应明细弹窗）"""
    return rx.grid(
        _stat_card("server", "服务器", GuildState.summary.guilds,
                   GuildState.open_detail("guilds")),
        _stat_card("messages-square", "频道", GuildState.summary.channels,
                   GuildState.open_detail("channels")),
        _stat_card("users", "成员", GuildState.summary.members,
                   GuildState.open_detail("members")),
        _stat_card("shield-x", "踢人总数", GuildState.summary.total_kicks,
                   GuildState.open_detail("kicks"), "var(--red-9)"),
        _stat_card("clock", "待发任务", GuildState.summary.pending_tasks,
                   GuildState.open_detail("pending"), "var(--orange-9)"),
        _stat_card("send", "已发送任务", GuildState.summary.sent_tasks,
                   GuildState.open_detail("sent"), "var(--green-9)"),
        _stat_card("circle-x", "失败任务", GuildState.summary.failed_tasks,
                   GuildState.open_detail("failed"), "var(--red-9)"),
        columns="4",
        spacing="4",
        width="100%",
    )


# ===== 服务器总览表格 =====
def guilds_table() -> rx.Component:
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("服务器名称"),
                rx.table.column_header_cell("成员数"),
                rx.table.column_header_cell("频道数"),
                rx.table.column_header_cell("踢人记录"),
                rx.table.column_header_cell("配置项"),
                rx.table.column_header_cell("加入时间"),
            )
        ),
        rx.table.body(
            rx.cond(
                GuildState.guilds.length() > 0,
                rx.foreach(
                    GuildState.guilds,
                    lambda g: rx.table.row(
                        rx.table.cell(
                            rx.hstack(
                                rx.link(
                                    g.guild_name,
                                    href=g.guild_url,
                                    underline="none",
                                    target="_blank",
                                    rel="noopener noreferrer",
                                ),
                                rx.link(
                                    rx.icon("external-link", size=14, color="gray"),
                                    href=g.guild_url,
                                    target="_blank",
                                    rel="noopener noreferrer",
                                ),
                                spacing="1",
                                align="center",
                            )
                        ),
                        rx.table.cell(g.member_count),
                        rx.table.cell(g.channel_count),
                        rx.table.cell(g.kick_count),
                        rx.table.cell(g.config_count),
                        rx.table.cell(g.joined_at),
                        cursor="pointer",
                    ),
                ),
                rx.table.row(
                    rx.table.cell("暂无服务器数据（机器人需先加入服务器并运行）",
                                  col_span=6, text_align="center"),
                ),
            )
        ),
        width="100%",
    )


# ===== 明细弹窗 =====
def _empty_row(text: str) -> rx.Component:
    return rx.text(text, color="gray", font_size="sm", padding="1em")


def _dialog_content(title: str, body: rx.Component) -> rx.Component:
    return rx.dialog.content(
        rx.dialog.title(title),
        body,
        max_width="760px",
        width="100%",
        max_height="80vh",
        overflow="auto",
    )


def guilds_modal() -> rx.Component:
    """服务器列表明细"""
    body = rx.cond(
        GuildState.guilds.length() > 0,
        rx.vstack(
            rx.foreach(
                GuildState.guilds,
                lambda g: rx.card(
                    rx.hstack(
                        rx.vstack(
                            rx.text(g.guild_name, font_weight="bold"),
                            rx.text(f"ID: {g.guild_id}", font_size="xs", color="gray"),
                            spacing="0",
                        ),
                        rx.spacer(),
                        rx.badge(f"{g.member_count} 成员", size="1"),
                        rx.badge(f"{g.channel_count} 频道", size="1"),
                        rx.badge(f"{g.kick_count} 踢人", size="1", color_scheme="red"),
                        spacing="2",
                        align="center",
                        width="100%",
                    ),
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        _empty_row("暂无服务器"),
    )
    return rx.dialog.root(
        _dialog_content("服务器列表", body),
        open=GuildState.active_modal == "guilds",
        on_open_change=GuildState.on_modal_change,
    )


def channels_modal() -> rx.Component:
    """频道明细（按服务器分组）"""
    body = rx.cond(
        GuildState.detail_channels.length() > 0,
        rx.vstack(
            rx.foreach(
                GuildState.detail_channels,
                lambda g: rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.text(g.guild_name, font_weight="bold"),
                            rx.badge(f"{g.channel_count} 频道", size="1"),
                            spacing="2",
                        ),
                        rx.foreach(
                            g.channels,
                            lambda c: rx.hstack(
                                rx.icon(
                                    rx.cond(c.channel_type == "forum", "disc", "hash"),
                                    size=14, color="gray",
                                ),
                                rx.text(c.channel_name, font_size="sm"),
                                spacing="2",
                                align="center",
                            ),
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        _empty_row("暂无频道数据"),
    )
    return rx.dialog.root(
        _dialog_content("频道明细", body),
        open=GuildState.active_modal == "channels",
        on_open_change=GuildState.on_modal_change,
    )


def members_modal() -> rx.Component:
    """成员明细（按服务器分组）"""
    body = rx.cond(
        GuildState.detail_members.length() > 0,
        rx.vstack(
            rx.foreach(
                GuildState.detail_members,
                lambda g: rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.text(g.guild_name, font_weight="bold"),
                            rx.badge(f"{g.member_count} 成员", size="1"),
                            spacing="2",
                        ),
                        rx.scroll_area(
                            rx.vstack(
                                rx.foreach(
                                    g.members,
                                    lambda m: rx.hstack(
                                        rx.icon("user", size=14, color="gray"),
                                        rx.text(m.display_name, font_size="sm"),
                                        spacing="2",
                                        align="center",
                                    ),
                                ),
                                spacing="1",
                                width="100%",
                            ),
                            height="300px",
                            width="100%",
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        _empty_row("暂无成员数据（Bot 重启后自动同步）"),
    )
    return rx.dialog.root(
        _dialog_content("成员明细", body),
        open=GuildState.active_modal == "members",
        on_open_change=GuildState.on_modal_change,
    )


def kicks_modal() -> rx.Component:
    """踢人明细"""
    body = rx.cond(
        GuildState.detail_kicks.length() > 0,
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("用户"),
                    rx.table.column_header_cell("服务器"),
                    rx.table.column_header_cell("频道"),
                    rx.table.column_header_cell("时间"),
                    rx.table.column_header_cell("原因"),
                )
            ),
            rx.table.body(
                rx.foreach(
                    GuildState.detail_kicks,
                    lambda k: rx.table.row(
                        rx.table.cell(k.user_name),
                        rx.table.cell(k.guild_name),
                        rx.table.cell(k.channel_name),
                        rx.table.cell(k.kicked_at),
                        rx.table.cell(k.reason),
                    ),
                ),
            ),
            width="100%",
        ),
        _empty_row("暂无踢人记录"),
    )
    return rx.dialog.root(
        _dialog_content("踢人记录", body),
        open=GuildState.active_modal == "kicks",
        on_open_change=GuildState.on_modal_change,
    )


def tasks_modal() -> rx.Component:
    """任务明细（待发/已发/失败，根据 active_modal 显示）"""
    modal_type = GuildState.active_modal
    body = rx.cond(
        GuildState.detail_tasks.length() > 0,
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("任务名"),
                    rx.table.column_header_cell("目标服务器"),
                    rx.table.column_header_cell("类型"),
                    rx.table.column_header_cell("状态"),
                    rx.table.column_header_cell("计划时间"),
                )
            ),
            rx.table.body(
                rx.foreach(
                    GuildState.detail_tasks,
                    lambda t: rx.table.row(
                        rx.table.cell(t.task_name),
                        rx.table.cell(t.guild_name),
                        rx.table.cell(t.schedule_type),
                        rx.table.cell(
                            rx.badge(
                                rx.cond(
                                    t.status == "pending",
                                    "待发送",
                                    rx.cond(
                                        t.status == "sent",
                                        "已发送",
                                        "失败",
                                    ),
                                ),
                                size="1",
                                color_scheme=rx.cond(
                                    t.status == "sent", "green",
                                    rx.cond(t.status == "pending", "orange", "red"),
                                ),
                            ),
                        ),
                        rx.table.cell(t.scheduled_at),
                    ),
                ),
            ),
            width="100%",
        ),
        _empty_row("该状态暂无任务"),
    )
    # 弹窗标题根据 active_modal 动态显示
    title = rx.cond(
        modal_type == "pending", "待发送任务",
        rx.cond(modal_type == "sent", "已发送任务", "发送失败任务"),
    )
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(title),
            body,
            max_width="760px",
            width="100%",
            max_height="80vh",
            overflow="auto",
        ),
        open=rx.cond(
            modal_type == "pending",
            True,
            rx.cond(modal_type == "sent", True, modal_type == "failed"),
        ),
        on_open_change=GuildState.on_modal_change,
    )


@rx.page(route="/guilds", title="系统监控", on_load=GuildState.load_guilds)
def guilds_page() -> rx.Component:
    return with_sidebar(
        rx.fragment(
            page_shell(
                "系统监控",
                "机器人运行状态与服务器总览（点击各板块查看明细）",
                bot_status_card(),
                summary_grid(),
                rx.divider(),
                rx.heading("服务器总览", size="4"),
                guilds_table(),
            ),
            # 明细弹窗
            guilds_modal(),
            channels_modal(),
            members_modal(),
            kicks_modal(),
            tasks_modal(),
            # 加载动画
            rx.cond(
                GuildState.loading,
                rx.box(
                    rx.text("加载中...", color="gray", font_size="sm"),
                    position="fixed", top="1em", right="1em", z_index="9999",
                ),
            ),
        )
    )
