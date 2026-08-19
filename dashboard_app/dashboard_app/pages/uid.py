"""UID 采集进程管理页

路由：
- /uid                   进程列表
- /uid/new               新建进程
- /uid/campaign/[id]     进程详情（编辑 + 报告 + 明细）
"""
import reflex as rx
from ..state import UIDState
from ..components.sidebar import page_shell, with_sidebar


def _status_badge(status: str) -> rx.Component:
    return rx.badge(
        rx.cond(
            status == "running", "运行中",
            rx.cond(status == "paused", "已暂停", "已结束"),
        ),
        color_scheme=rx.cond(
            status == "running", "green",
            rx.cond(status == "paused", "orange", "gray"),
        ),
        size="1",
    )


def _stat_card(title: str, value, color: str) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(title, color="gray", font_size="sm"),
            rx.heading(value, size="5", color=color),
            spacing="1",
            width="100%",
            align="start",
        ),
        width="100%",
    )


def _flash_box() -> rx.Component:
    return rx.fragment(
        rx.cond(
            UIDState.toast != "",
            rx.box(
                rx.text(UIDState.toast, font_size="sm", color="white"),
                position="fixed", bottom="1em", right="1em", z_index="9999",
                padding="0.6em 1.2em", border_radius="md",
                background="var(--green-9)", box_shadow="0 2px 8px rgba(0,0,0,0.2)",
            ),
        ),
        rx.cond(
            UIDState.error != "",
            rx.box(
                rx.text(UIDState.error, font_size="sm", color="white"),
                position="fixed", bottom="1em", right="1em", z_index="9999",
                padding="0.6em 1.2em", border_radius="md",
                background="var(--red-9)", box_shadow="0 2px 8px rgba(0,0,0,0.2)",
            ),
        ),
    )


# ===================== 进程列表页 /uid =====================
def _campaign_row(c) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.heading(c.name, size="3"),
                    _status_badge(c.status),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    f"{c.channel_name} · {c.guild_name} · {c.uid_length}位",
                    color="gray", font_size="sm",
                ),
                rx.text(
                    rx.cond(
                        (c.started_at != "") & (c.end_at != ""),
                        f"{c.started_at} ~ {c.end_at}",
                        rx.cond(c.started_at != "", f"从 {c.started_at} 起", "不限时间"),
                    ),
                    color="gray", font_size="xs",
                ),
                spacing="2",
                align="start",
            ),
            rx.spacer(),
            # 统计块：垂直居中于卡片
            rx.vstack(
                rx.hstack(
                    rx.text("有效", font_size="xs", color="green"),
                    rx.heading(c.stats["valid"], size="4", color="green"),
                ),
                rx.hstack(
                    rx.text("总数", font_size="xs", color="gray"),
                    rx.heading(c.stats["total"], size="4"),
                ),
                spacing="1",
                align="center",
                justify="center",
            ),
            # 按钮块：垂直居中于卡片
            rx.hstack(
                rx.button("查看", on_click=lambda: rx.redirect(f"/uid/campaign/{c.id}"), size="2", cursor="pointer"),
                # 按钮按状态区分：running 显示暂停/结束，paused 显示继续/结束，ended 仅查看
                rx.cond(
                    c.status == "running",
                    rx.hstack(
                        rx.button("暂停", on_click=UIDState.set_status(c.id, "paused"), size="2", variant="soft", cursor="pointer"),
                        rx.button("结束", on_click=UIDState.set_status(c.id, "ended"), size="2", variant="soft", color_scheme="red", cursor="pointer"),
                        spacing="2",
                    ),
                    rx.cond(
                        c.status == "paused",
                        rx.hstack(
                            rx.button("继续", on_click=UIDState.set_status(c.id, "running"), size="2", variant="soft", cursor="pointer"),
                            rx.button("结束", on_click=UIDState.set_status(c.id, "ended"), size="2", variant="soft", color_scheme="red", cursor="pointer"),
                            spacing="2",
                        ),
                        rx.text("已结束", color="gray", font_size="sm"),
                    ),
                ),
                spacing="2",
                align="center",
            ),
            padding="1em",
            align="center",
        ),
        width="100%",
    )


@rx.page(route="/uid", title="UID 采集", on_load=UIDState.load_campaigns)
def uid_page() -> rx.Component:
    return with_sidebar(
        rx.fragment(
            page_shell(
                "UID 采集", "管理多个采集进程，每个进程绑定一个频道和一套规则",
                rx.vstack(
                    rx.hstack(
                        rx.heading("采集进程", size="3"),
                        rx.spacer(),
                        rx.button(
                            "新建进程",
                            on_click=rx.redirect("/uid/new"),
                            color_scheme="plum",
                            cursor="pointer",
                        ),
                        width="100%",
                    ),
                    rx.cond(
                        UIDState.campaigns.length() > 0,
                        rx.vstack(
                            rx.foreach(UIDState.campaigns, _campaign_row),
                            spacing="3",
                            width="100%",
                        ),
                        rx.card(
                            rx.vstack(
                                rx.text("暂无采集进程", color="gray"),
                                rx.text("点击右上角「新建进程」开始配置", font_size="sm", color="gray"),
                                spacing="2",
                            ),
                            width="100%",
                            align_items="center",
                            padding="2em",
                        ),
                    ),
                    spacing="4",
                    width="100%",
                ),
            ),
            _flash_box(),
        ),
    )


# ===================== 新建/编辑进程表单 =====================
def _dt_input(label: str, date_value, time_value, on_date, on_time) -> rx.Component:
    """开始/结束时间输入 — 使用 HTML5 原生日历（type=date）与时间选择器（type=time），
    避免手动输入格式问题。"""
    return rx.hstack(
        rx.text(label, font_weight="bold", font_size="sm", width="70px"),
        rx.input(
            type="date",
            value=date_value,
            on_change=on_date,
            width="160px",
            class_name="iip-date-input",
        ),
        rx.text("时间", font_size="xs", color="gray"),
        rx.input(
            type="time",
            value=time_value,
            on_change=on_time,
            width="120px",
            class_name="iip-time-input",
        ),
        spacing="2",
        align="center",
    )


def _campaign_form() -> rx.Component:
    return rx.vstack(
        rx.card(
            rx.vstack(
                rx.heading(rx.cond(UIDState.form_id == 0, "新建采集进程", "编辑采集进程"), size="3"),
                rx.divider(),
                # 名称
                rx.hstack(
                    rx.text("进程名称", font_weight="bold", font_size="sm", width="110px"),
                    rx.input(value=UIDState.form_name, on_change=UIDState.on_name_change,
                             placeholder="如：2026夏日活动", width="100%"),
                    width="100%", align="center",
                ),
                # 服务器
                rx.hstack(
                    rx.text("选择服务器", font_weight="bold", font_size="sm", width="110px"),
                    rx.select.root(
                        rx.select.trigger(placeholder="选择服务器…"),
                        rx.select.content(
                            rx.foreach(
                                UIDState.guilds,
                                lambda g: rx.select.item(g.guild_name, value=g.guild_id),
                            ),
                        ),
                        value=UIDState.form_guild_id,
                        on_change=UIDState.on_guild_change,
                        width="100%",
                    ),
                    width="100%", align="center",
                ),
                # 频道
                rx.hstack(
                    rx.text("采集频道", font_weight="bold", font_size="sm", width="110px"),
                    rx.select.root(
                        rx.select.trigger(placeholder="选择频道…"),
                        rx.select.content(
                            rx.foreach(
                                UIDState.channels,
                                lambda c: rx.select.item(c["channel_name"], value=c["channel_id"]),
                            ),
                        ),
                        value=UIDState.form_channel_id,
                        on_change=UIDState.on_channel_change,
                        width="100%",
                    ),
                    width="100%", align="center",
                ),
                rx.text("提示：一个频道同时只能被一个运行中的进程占用", size="1", color="gray"),
                # 位数
                rx.hstack(
                    rx.text("UID 位数", font_weight="bold", font_size="sm", width="110px"),
                    rx.input(value=UIDState.form_length, on_change=UIDState.on_length_change,
                             placeholder="8", width="120px"),
                    width="100%", align="center",
                ),
                # 反应
                rx.hstack(
                    rx.text("有效反应", font_weight="bold", font_size="sm", width="110px"),
                    rx.input(value=UIDState.form_valid_reaction, on_change=UIDState.on_valid_reaction_change,
                             width="120px"),
                    width="100%", align="center",
                ),
                rx.hstack(
                    rx.text("重复/无效反应", font_weight="bold", font_size="sm", width="110px"),
                    rx.input(value=UIDState.form_duplicate_reaction, on_change=UIDState.on_duplicate_reaction_change,
                             width="120px"),
                    width="100%", align="center",
                ),
                spacing="3", width="100%",
            ),
            width="100%",
        ),
        rx.card(
            rx.vstack(
                rx.heading("时间范围", size="3"),
                rx.text("采集只在开始到结束时间内进行，超出自动结案；留空表示不限", size="1", color="gray"),
                rx.divider(),
                _dt_input("开始", UIDState.form_start_date, UIDState.form_start_time,
                          UIDState.on_start_date_change, UIDState.on_start_time_change),
                _dt_input("结束", UIDState.form_end_date, UIDState.form_end_time,
                          UIDState.on_end_date_change, UIDState.on_end_time_change),
                spacing="3", width="100%",
            ),
            width="100%",
        ),
        rx.card(
            rx.vstack(
                rx.heading("质询消息模板", size="3"),
                rx.text("支持 {user} {uid} {uid_length} 占位符", size="1", color="gray"),
                rx.divider(),
                rx.text("① 重叠质询", font_weight="bold", font_size="sm"),
                rx.text_area(value=UIDState.form_msg_overlap, on_change=UIDState.on_msg_overlap_change,
                             width="100%", rows="2"),
                rx.text("② 同一人多发质询", font_weight="bold", font_size="sm"),
                rx.text_area(value=UIDState.form_msg_multiple, on_change=UIDState.on_msg_multiple_change,
                             width="100%", rows="2"),
                rx.text("③ 位数不符质询", font_weight="bold", font_size="sm"),
                rx.text_area(value=UIDState.form_msg_length, on_change=UIDState.on_msg_length_change,
                             width="100%", rows="2"),
                spacing="3", width="100%",
            ),
            width="100%",
        ),
        rx.hstack(
            rx.button("返回列表", on_click=rx.redirect("/uid"), variant="soft", cursor="pointer"),
            rx.spacer(),
            rx.button("保存并运行", on_click=UIDState.save_campaign, color_scheme="plum", cursor="pointer"),
            width="100%",
        ),
        spacing="4", width="100%",
    )


@rx.page(route="/uid/new", title="新建采集进程", on_load=UIDState.start_new)
def uid_new_page() -> rx.Component:
    return with_sidebar(
        rx.fragment(
            page_shell(
                "新建采集进程", "配置频道、规则与时间范围，保存后立即开始运行",
                _campaign_form(),
            ),
            _flash_box(),
        ),
    )


# ===================== 进程详情 /uid/campaign/[id] =====================
def _report_section() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("采集报告", size="3"),
            rx.divider(),
            rx.grid(
                _stat_card("消息总数", UIDState.stats.total, "var(--gray-11)"),
                _stat_card("有效 UID", UIDState.stats.valid, "var(--green-9)"),
                _stat_card("重复", UIDState.stats.duplicate, "var(--orange-9)"),
                _stat_card("无效", UIDState.stats.invalid, "var(--red-9)"),
                _stat_card("去重有效数", UIDState.stats.unique_uids, "var(--plum-9)"),
                columns="5", spacing="3", width="100%",
            ),
            rx.hstack(
                rx.text("简略 UID 列表", font_weight="bold", font_size="sm"),
                rx.spacer(),
                rx.button("复制 UID", on_click=rx.set_clipboard(UIDState.copy_uid_list()),
                          size="2", variant="soft", cursor="pointer"),
                width="100%", align="center",
            ),
            rx.text_area(value=UIDState.uid_list.join("\n"), width="100%", rows="6", read_only=True),
            spacing="3", width="100%",
        ),
        width="100%",
    )


def _scan_row(t) -> rx.Component:
    """扫描任务历史行"""
    status_map = {"pending": ("排队中", "gray"), "processing": ("扫描中", "blue"),
                  "done": ("完成", "green"), "failed": ("失败", "red")}
    label, color = status_map.get(t.status, (t.status, "gray"))
    return rx.table.row(
        rx.table.cell(t.created_at),
        rx.table.cell(rx.badge(label, color_scheme=color)),
        rx.table.cell(rx.cond(
            t.status == "done",
            rx.text(f"新增 {t.scanned_new} · 重复 {t.scanned_dup} · 忽略 {t.out_of_window}"),
            rx.cond(t.status == "failed", t.error, "—"),
        )),
        rx.table.cell(rx.cond(t.processed_at != "", t.processed_at, "—")),
    )


def _scan_section() -> rx.Component:
    """手动扫描面板：任务历史 + 结果弹窗"""
    return rx.fragment(
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.heading("手动扫描", size="3"),
                    rx.text("Bot 掉线后查漏补缺：手动触发一次全量扫描，仅采纳进程时间范围内的消息", size="1", color="gray"),
                    rx.spacer(),
                    rx.button("手动扫描", on_click=UIDState.manual_scan, size="2", color_scheme="blue", cursor="pointer"),
                    rx.button("刷新结果", on_click=UIDState.refresh_scan_result, size="2", variant="soft", cursor="pointer"),
                    width="100%",
                ),
                rx.divider(),
                rx.cond(
                    UIDState.scan_tasks.length() > 0,
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("发起时间(北京)"),
                                rx.table.column_header_cell("状态"),
                                rx.table.column_header_cell("结果"),
                                rx.table.column_header_cell("完成时间(北京)"),
                            ),
                        ),
                        rx.table.body(
                            rx.foreach(UIDState.scan_tasks, _scan_row),
                        ),
                    ),
                    rx.text("暂无扫描记录。Bot 掉线或疑似漏采时可手动扫描补采。", color="gray", font_size="sm"),
                ),
                spacing="3", width="100%",
            ),
            width="100%",
        ),
        # 扫描结果弹窗
        rx.dialog.root(
            rx.dialog.trigger(rx.fragment()),
            rx.dialog.content(
                rx.dialog.title(UIDState.scan_result_title),
                rx.dialog.description(
                    rx.cond(
                        UIDState.scan_result.get("error") != "",
                        rx.text(UIDState.scan_result.get("error"), color="red"),
                        rx.vstack(
                            rx.hstack(
                                rx.text("本次新增采集", font_weight="bold", width="120px"),
                                rx.text(UIDState.scan_result.get("scanned_new", 0), color="green", font_weight="bold"),
                            ),
                            rx.hstack(
                                rx.text("已采集过的重复", font_weight="bold", width="120px"),
                                rx.text(UIDState.scan_result.get("scanned_dup", 0), color="orange", font_weight="bold"),
                            ),
                            rx.hstack(
                                rx.text("超出时间范围忽略", font_weight="bold", width="120px"),
                                rx.text(UIDState.scan_result.get("out_of_window", 0), color="gray", font_weight="bold"),
                            ),
                            spacing="2",
                        ),
                    ),
                ),
                rx.hstack(
                    rx.spacer(),
                    rx.dialog.close(rx.button("关闭", variant="soft", cursor="pointer")),
                    width="100%",
                ),
            ),
            open=UIDState.scan_show_result,
            on_open_change=UIDState.close_scan_result,
        ),
    )


def _record_row(r) -> rx.Component:
    return rx.table.row(
        rx.table.cell(r.created_at),
        rx.table.cell(r.user_name),
        rx.table.cell(r.uid),
        rx.table.cell(r.answer),
        rx.table.cell(_status_badge(r.status)),
        rx.table.cell(r.raw_content, max_width="280px", truncate=True),
    )


def _detail_section() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading("采集明细", size="3"),
                rx.spacer(),
                rx.select.root(
                    rx.select.trigger(),
                    rx.select.content(
                        rx.select.item("全部", value="all"),
                        rx.select.item("有效", value="valid"),
                        rx.select.item("重复", value="duplicate"),
                        rx.select.item("无效", value="invalid"),
                    ),
                    value=UIDState.filter_status,
                    on_change=UIDState.on_filter_status_change,
                    size="2",
                ),
                rx.input(placeholder="开始日期", value=UIDState.filter_start,
                         on_change=UIDState.on_filter_start_change, size="2"),
                rx.input(placeholder="结束日期", value=UIDState.filter_end,
                         on_change=UIDState.on_filter_end_change, size="2"),
                rx.button("查询", on_click=UIDState.load_report, size="2", cursor="pointer"),
            ),
            rx.divider(),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("时间(北京时间)"),
                        rx.table.column_header_cell("用户"),
                        rx.table.column_header_cell("UID"),
                        rx.table.column_header_cell("答案"),
                        rx.table.column_header_cell("状态"),
                        rx.table.column_header_cell("消息原文"),
                    ),
                ),
                rx.table.body(
                    rx.foreach(UIDState.records, _record_row),
                ),
            ),
            rx.cond(
                UIDState.records.length() == 0,
                rx.text("暂无记录", color="gray", font_size="sm"),
            ),
            spacing="3", width="100%",
        ),
        width="100%",
    )


@rx.page(route="/uid/campaign/[campaign_id]", title="采集进程详情",
         on_load=UIDState.load_campaign_detail)
def uid_detail_page() -> rx.Component:
    return with_sidebar(
        rx.fragment(
            page_shell(
                rx.cond(UIDState.current_campaign.name != "", UIDState.current_campaign.name, "进程详情"),
                rx.cond(
                    UIDState.current_campaign.status != "",
                    rx.hstack(
                        _status_badge(UIDState.current_campaign.status),
                        rx.text(
                            f"{UIDState.current_campaign.channel_name} · {UIDState.current_campaign.uid_length}位",
                            color="gray", font_size="sm",
                        ),
                        spacing="2",
                    ),
                ),
                rx.vstack(
                    rx.card(
                        rx.hstack(
                            rx.button("编辑配置", on_click=rx.redirect(f"/uid/edit/{UIDState.current_campaign.id}"), size="2", cursor="pointer"),
                            # 操作按钮按状态区分，且受时间范围约束
                            rx.cond(
                                UIDState.current_campaign.status == "running",
                                rx.hstack(
                                    rx.button("暂停", on_click=UIDState.set_status(UIDState.current_campaign.id, "paused"), size="2", variant="soft", cursor="pointer"),
                                    rx.button("结束", on_click=UIDState.set_status(UIDState.current_campaign.id, "ended"), size="2", color_scheme="red", cursor="pointer"),
                                    spacing="2",
                                ),
                                rx.cond(
                                    UIDState.current_campaign.status == "paused",
                                    rx.hstack(
                                        rx.button("继续", on_click=UIDState.set_status(UIDState.current_campaign.id, "running"), size="2", variant="soft", cursor="pointer"),
                                        rx.button("结束", on_click=UIDState.set_status(UIDState.current_campaign.id, "ended"), size="2", color_scheme="red", cursor="pointer"),
                                        spacing="2",
                                    ),
                                    rx.text("进程已结束，不可再操作", color="gray", font_size="sm"),
                                ),
                            ),
                            rx.button("删除", on_click=UIDState.delete_campaign(UIDState.current_campaign.id), size="2", color_scheme="red", variant="outline", cursor="pointer"),
                            rx.spacer(),
                            rx.button("返回列表", on_click=rx.redirect("/uid"), variant="soft", cursor="pointer"),
                            width="100%",
                            justify="center",
                            align="center",
                        ),
                        width="100%",
                    ),
                    _report_section(),
                    _scan_section(),
                    _detail_section(),
                    spacing="4", width="100%",
                ),
            ),
            _flash_box(),
        ),
    )


@rx.page(route="/uid/edit/[campaign_id]", title="编辑采集进程",
         on_load=UIDState.load_campaign_for_edit)
def uid_edit_page() -> rx.Component:
    return with_sidebar(
        rx.fragment(
            page_shell(
                "编辑采集进程", "修改频道、规则与时间范围，保存后即时生效",
                _campaign_form(),
            ),
            _flash_box(),
        ),
    )
