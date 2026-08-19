"""广播页面 — 消息编辑 + @mention + 实时预览"""

import reflex as rx

from ..state.broadcast_state import BroadcastState
from ..components.sidebar import page_shell, with_sidebar
from shared_lib.models import TARGET_CHANNEL, TARGET_FORUM_NEW, TARGET_FORUM_REPLY

TARGET_OPTIONS = [
    (TARGET_CHANNEL, "普通消息"),
    (TARGET_FORUM_NEW, "论坛发帖"),
    (TARGET_FORUM_REPLY, "回复帖子"),
]

# ── 注入前端格式化 JS（选区感知） ──
FMT_JS = """
function fmtApply(openMark, closeMark, placeholder) {
    const ta = document.getElementById('broadcast-textarea');
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    let cursorPos, selEnd;
    if (start !== end) {
        // 有选中文字 → 包裹
        const selected = ta.value.substring(start, end);
        ta.value = ta.value.substring(0, start) + openMark + selected + closeMark + ta.value.substring(end);
        cursorPos = start + openMark.length + selected.length + closeMark.length;
        selEnd = cursorPos;
    } else {
        // 无选中 → 插入占位文本
        const mid = openMark + placeholder + closeMark;
        ta.value = ta.value.substring(0, start) + mid + ta.value.substring(end);
        cursorPos = start + openMark.length;
        selEnd = cursorPos + placeholder.length;
    }
    // 通知 React 值已变化
    ta.dispatchEvent(new Event('input', {bubbles: true}));
    ta.focus();
    // 双 rAF 等 React 重渲染完成后恢复光标
    requestAnimationFrame(function() {
        requestAnimationFrame(function() {
            ta.setSelectionRange(cursorPos, selEnd);
        });
    });
}
"""


# ── Copilot 风格按钮（用于 @提及 / #引用） ──
def mention_button(icon: str, label: str, on_click):
    return rx.tooltip(
        rx.icon_button(
            rx.icon(icon, size=16),
            variant="ghost",
            size="1",
            on_click=on_click,
            color_scheme="plum",
            cursor="pointer",
        ),
        content=label,
    )


# ── 成员项：头像 + 名字（缺失回退默认图标 / ID） ──
# 整行可点击（width=100%），悬浮高亮覆盖整行；上下内边距留出间距。
def _member_item(m) -> rx.Component:
    has_avatar = m["avatar_url"] != ""
    avatar = rx.cond(
        has_avatar,
        rx.avatar(
            src=m["avatar_url"],
            size="2",
            border_radius="full",
        ),
        rx.box(
            rx.icon("user", size=16),
            width="32px",
            height="32px",
            border_radius="full",
            background="var(--gray-a3)",
            display="flex",
            align_items="center",
            justify_content="center",
        ),
    )
    return rx.button(
        rx.hstack(
            avatar,
            rx.vstack(
                rx.text(
                    rx.cond(m["display_name"] != "", m["display_name"], m["user_id"]),
                    font_size="14px",
                ),
                rx.text(
                    rx.cond(m["display_name"] != "", f"@{m['display_name']}", m["user_id"]),
                    font_size="12px",
                    color="gray",
                ),
                spacing="0",
                align="start",
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        variant="ghost",
        width="100%",
        padding_x="0.75rem",
        padding_y="0.6rem",
        border_radius="8px",
        cursor="pointer",
        on_click=lambda: BroadcastState.insert_mention_user(m["user_id"]),
    )


# ── 频道项：默认 # 图标 + 频道名（缺失回退 ID） ──
def _channel_item(c) -> rx.Component:
    return rx.button(
        rx.hstack(
            rx.box(
                rx.icon("hash", size=16),
                width="32px",
                height="32px",
                border_radius="full",
                background="var(--gray-a3)",
                display="flex",
                align_items="center",
                justify_content="center",
            ),
            rx.vstack(
                rx.text(
                    rx.cond(c["channel_name"] != "", c["channel_name"], c["channel_id"]),
                    font_size="14px",
                ),
                rx.text(
                    rx.cond(c["channel_name"] != "", f"#{c['channel_name']}", c["channel_id"]),
                    font_size="12px",
                    color="gray",
                ),
                spacing="0",
                align="start",
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        variant="ghost",
        width="100%",
        padding_x="0.75rem",
        padding_y="0.6rem",
        border_radius="8px",
        cursor="pointer",
        on_click=lambda: BroadcastState.insert_mention_channel(c["channel_id"]),
    )


# ── 提及弹窗：@成员 / #频道 选择 ──
def mention_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    BroadcastState.mention_mode == "member",
                    "选择要提及的成员",
                    "选择要引用的频道",
                ),
                size="3",
            ),
            rx.hstack(
                rx.icon("search", size=14),
                rx.input(
                    placeholder=rx.cond(
                        BroadcastState.mention_mode == "member",
                        "输入成员名搜索…",
                        "输入频道名搜索…",
                    ),
                    value=BroadcastState.mention_search,
                    on_change=BroadcastState.on_mention_search_change,
                    size="1",
                    width="100%",
                ),
                spacing="2",
                width="100%",
                align="center",
            ),
            # 列表区域：上下留白，与搜索框、取消按钮拉开间隙
            rx.cond(
                BroadcastState.mention_mode == "member",
                rx.cond(
                    BroadcastState.mention_results.length() > 0,
                    rx.vstack(
                        rx.foreach(BroadcastState.mention_results, _member_item),
                        max_height="300px",
                        overflow_y="auto",
                        width="100%",
                        spacing="3",
                        padding_top="0.75rem",
                        padding_bottom="0.75rem",
                    ),
                    rx.text("无匹配成员", size="1", color="gray", padding="1rem"),
                ),
                rx.cond(
                    BroadcastState.channel_search_hits.length() > 0,
                    rx.vstack(
                        rx.foreach(BroadcastState.channel_search_hits, _channel_item),
                        max_height="300px",
                        overflow_y="auto",
                        width="100%",
                        spacing="3",
                        padding_top="0.75rem",
                        padding_bottom="0.75rem",
                    ),
                    rx.text("无匹配频道", size="1", color="gray", padding="1rem"),
                ),
            ),
            rx.hstack(
                rx.spacer(),
                rx.dialog.close(
                    rx.button("取消", variant="soft", size="1", cursor="pointer"),
                ),
                width="100%",
                padding_top="0.5rem",
            ),
            width="420px",
            max_width="90vw",
        ),
        open=BroadcastState.mention_panel_open,
        on_open_change=BroadcastState.on_dialog_open_change,
    )


# ── 头部连接符（嵌入 rx.foreach） ──
def _guild_option(g: dict):
    return rx.select.item(g["guild_name"], value=g["guild_id"])


def _channel_option(ch: dict):
    return rx.select.item(ch["channel_name"], value=ch["channel_id"])


def _thread_option(t: dict):
    return rx.select.item(t["channel_name"], value=t["channel_id"])


# ═══════════════════════════════════════════════════════
#  ① 目标选择行
# ═══════════════════════════════════════════════════════

def target_selector() -> rx.Component:
    return rx.flex(
        rx.select.root(
            rx.select.trigger(placeholder="选择服务器"),
            rx.select.content(
                rx.foreach(BroadcastState.guilds_list, _guild_option)
            ),
            value=BroadcastState.selected_guild_id,
            on_change=BroadcastState.on_guild_change,
            default_value="",
        ),
        # 频道/论坛选择器（根据 target_type 动态切换）
        rx.select.root(
            rx.select.trigger(placeholder="选择目标"),
            rx.select.content(
                rx.cond(
                    BroadcastState.target_type == TARGET_CHANNEL,
                    rx.foreach(BroadcastState.channels_text, _channel_option),
                    rx.cond(
                        BroadcastState.target_type == TARGET_FORUM_NEW,
                        rx.foreach(BroadcastState.channels_forum, _channel_option),
                        rx.foreach(BroadcastState.channels_forum, _channel_option),
                    ),
                ),
            ),
            value=BroadcastState.selected_channel_id,
            on_change=BroadcastState.set_selected_channel,
        ),
        rx.select.root(
            rx.select.trigger(placeholder="目标类型"),
            rx.select.content(
                rx.select.item("普通消息", value=TARGET_CHANNEL),
                rx.select.item("论坛发帖", value=TARGET_FORUM_NEW),
                rx.select.item("回复帖子", value=TARGET_FORUM_REPLY),
            ),
            value=BroadcastState.target_type,
            on_change=BroadcastState.on_target_change,
            default_value=TARGET_CHANNEL,
        ),
        rx.cond(
            BroadcastState.target_type == TARGET_FORUM_NEW,
            rx.input(
                placeholder="帖子标题",
                value=BroadcastState.thread_name,
                on_change=BroadcastState.set_thread_name_evt,
                size="2",
            ),
        ),
        rx.cond(
            BroadcastState.target_type == TARGET_FORUM_REPLY,
            rx.select.root(
                rx.select.trigger(
                    placeholder=rx.cond(
                        BroadcastState.filtered_threads.length() > 0,
                        "选择帖子",
                        "该论坛暂无帖子",
                    )
                ),
                rx.select.content(
                    rx.cond(
                        BroadcastState.filtered_threads.length() > 0,
                        rx.foreach(BroadcastState.filtered_threads, _thread_option),
                    ),
                ),
                value=BroadcastState.selected_thread_id,
                on_change=BroadcastState.on_thread_select,
            ),
        ),
        spacing="2",
        width="100%",
        wrap="wrap",
    )


# ═══════════════════════════════════════════════════════
#  ②a 编辑区
# ═══════════════════════════════════════════════════════

def editor_panel() -> rx.Component:
    return rx.box(
        rx.flex(
            rx.text("编辑", weight="bold", size="2"),
            # 格式化工具栏
            rx.flex(
                mention_button("at-sign", "@提及成员", lambda: BroadcastState.set_mention_mode("member")),
                mention_button("hash", "#引用频道", lambda: BroadcastState.set_mention_mode("channel")),
                rx.separator(orientation="vertical", size="1"),
                mention_button("bold", "粗体 **text**", rx.call_script("fmtApply('**','**','粗体')")),
                mention_button("italic", "斜体 *text*", rx.call_script("fmtApply('*','*','斜体')")),
                mention_button("strikethrough", "删除线 ~~text~~", rx.call_script("fmtApply('~~','~~','删除')")),
                mention_button("code", "行内代码 `text`", rx.call_script("fmtApply('`','`','代码')")),
                mention_button("quote", "引用 > text", rx.call_script("fmtApply('> ','','引用')")),
                mention_button("eye-off", "剧透 ||text||", rx.call_script("fmtApply('||','||','剧透')")),
                spacing="1",
            ),
            justify="between",
            width="100%",
        ),
        # ── 正文 ──
        rx.text_area(
            placeholder="在此输入消息内容…\n\n支持 Discord Markdown:\n**粗体**  *斜体*  ~~删除~~  `代码`  ```代码块```\n> 引用  # 标题  - 列表  ||剧透||\n<@用户ID> @提及  <#频道ID> 频道引用",
            value=BroadcastState.content,
            on_change=BroadcastState.set_content_evt,
            min_height="280px",
            size="2",
            width="100%",
            id="broadcast-textarea",
        ),
        # ── 字符计数 ──
        rx.flex(
            rx.text(
                f"{BroadcastState.char_count} / 2000",
                size="1",
                color_scheme=rx.cond(BroadcastState.is_too_long, "red", "gray"),
                weight=rx.cond(BroadcastState.is_too_long, "bold", "regular"),
            ),
            rx.cond(
                BroadcastState.is_too_long,
                rx.text(" ⚠️ 已超长，将自动拆分为多条发送", size="1", color_scheme="red"),
            ),
            rx.cond(
                (BroadcastState.chunks.length() > 1),
                rx.text(
                    f" → 将拆为 {BroadcastState.chunks.length()} 条",
                    size="1",
                    color_scheme="gray",
                ),
            ),
            spacing="2",
        ),
        width="50%",
        padding="2",
    )


# ═══════════════════════════════════════════════════════
#  ②b 预览区
# ═══════════════════════════════════════════════════════

def preview_panel() -> rx.Component:
    return rx.box(
        rx.text("预览", weight="bold", size="2", margin_bottom="2"),
        rx.box(
            rx.markdown(
                BroadcastState.preview_content,
                width="100%",
            ),
            padding="4",
            border="1px solid var(--gray-a5)",
            border_radius="8px",
            min_height="280px",
            background="var(--gray-3)",
            width="100%",
        ),
        # 附件预览
        rx.cond(
            BroadcastState.attachments.length() > 0,
            rx.vstack(
                rx.text("附件预览:", size="1", weight="bold"),
                rx.foreach(
                    BroadcastState.attachments,
                    lambda att, idx: rx.flex(
                        rx.icon("image", size=14),
                        rx.text(att["filename"], size="1"),
                        rx.text(f"({att['size']} B)", size="1", color_scheme="gray"),
                        rx.icon_button(
                            rx.icon("x", size=12),
                            variant="ghost",
                            size="1",
                            color_scheme="red",
                            cursor="pointer",
                            on_click=lambda: BroadcastState.remove_attachment(idx),
                        ),
                        spacing="1",
                        align="center",
                    ),
                ),
                spacing="1",
            ),
        ),
        width="50%",
        padding="2",
    )


# ═══════════════════════════════════════════════════════
#  ③ 定时 / 发送
# ═══════════════════════════════════════════════════════

def schedule_panel() -> rx.Component:
    return rx.flex(
        rx.select.root(
            rx.select.trigger(),
            rx.select.content(
                rx.select.item("立即发送", value="immediate"),
                rx.select.item("定时发送", value="scheduled"),
            ),
            value=BroadcastState.schedule_type,
            on_change=BroadcastState.set_schedule_type_evt,
            default_value="immediate",
        ),
        rx.cond(
            BroadcastState.schedule_type == "scheduled",
            rx.flex(
                rx.input(
                    type="date",
                    value=BroadcastState.scheduled_date,
                    on_change=BroadcastState.set_scheduled_date_evt,
                    min=BroadcastState.today_str,
                    size="2",
                ),
                rx.input(
                    type="time",
                    value=BroadcastState.scheduled_time,
                    on_change=BroadcastState.set_scheduled_time_evt,
                    size="2",
                ),
                spacing="2",
            ),
        ),
        spacing="2",
        align="center",
    )


def action_bar() -> rx.Component:
    return rx.flex(
        schedule_panel(),
        rx.spacer(),
        rx.input(
            placeholder="任务名称（可选）",
            value=BroadcastState.task_name,
            on_change=BroadcastState.set_task_name_evt,
            size="2",
            width="200px",
        ),
        rx.upload(
            rx.button(
                rx.icon("upload", size=16),
                "上传图片",
                variant="soft",
                size="2",
                cursor="pointer",
            ),
            id="broadcast_upload",
            multiple=True,
            border="1px dashed var(--gray-a5)",
            padding="1",
            border_radius="6px",
        ),
        rx.button(
            "存草稿",
            variant="outline",
            size="2",
            cursor="pointer",
            on_click=BroadcastState.save_draft,
        ),
        rx.button(
            rx.icon("send", size=16),
            "发送",
            color_scheme="plum",
            size="2",
            cursor="pointer",
            on_click=BroadcastState.submit,
        ),
        width="100%",
        spacing="2",
        align="center",
        padding_y="2",
    )


# ═══════════════════════════════════════════════════════
#  ④ 发送历史弹窗
# ═══════════════════════════════════════════════════════

STATUS_MAP = {
    "pending": "待发送",
    "sent": "已发送",
    "failed": "失败",
    "draft": "草稿",
}


def _status_badge(status: str) -> rx.Component:
    colors = {"pending": "orange", "sent": "green", "failed": "red", "draft": "gray"}
    return rx.badge(
        STATUS_MAP.get(status, status),
        color_scheme=colors.get(status, "gray"),
        variant="soft",
        size="1",
    )


def _pagination_controls() -> rx.Component:
    return rx.flex(
        rx.icon_button(
            rx.icon("chevron-left", size=16),
            variant="ghost",
            size="1",
            cursor="pointer",
            disabled=BroadcastState.history_page <= 1,
            on_click=BroadcastState.go_history_page(BroadcastState.history_page - 1),
        ),
        rx.text(
            f"{BroadcastState.history_page} / {BroadcastState.history_total_pages}",
            size="1",
            white_space="nowrap",
        ),
        rx.icon_button(
            rx.icon("chevron-right", size=16),
            variant="ghost",
            size="1",
            cursor="pointer",
            disabled=BroadcastState.history_page >= BroadcastState.history_total_pages,
            on_click=BroadcastState.go_history_page(BroadcastState.history_page + 1),
        ),
        spacing="1",
        align="center",
    )


def history_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.flex(
                    rx.icon("clock", size=18),
                    rx.text("发送历史"),
                    rx.spacer(),
                    _pagination_controls(),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
            ),
            # 搜索栏
            rx.flex(
                rx.input(
                    placeholder="搜索任务名 / 内容…",
                    value=BroadcastState.history_search,
                    on_change=BroadcastState.set_history_search,
                    size="2",
                    width="280px",
                ),
                rx.spacer(),
                rx.text("每页:", size="1", color_scheme="gray"),
                rx.select.root(
                    rx.select.trigger(),
                    rx.select.content(
                        rx.select.item("10", value="10"),
                        rx.select.item("50", value="50"),
                        rx.select.item("100", value="100"),
                    ),
                    value=BroadcastState.history_per_page.to(str),
                    on_change=BroadcastState.set_history_per_page,
                    size="1",
                    width="80px",
                ),
                spacing="2",
                align="center",
                padding_bottom="2",
            ),
            # 表格
            rx.box(
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("任务名", width="150px"),
                            rx.table.column_header_cell("内容预览", width="200px"),
                            rx.table.column_header_cell("类型", width="70px"),
                            rx.table.column_header_cell("状态", width="80px"),
                            rx.table.column_header_cell("定时时间", width="130px"),
                            rx.table.column_header_cell("创建时间", width="130px"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(
                            BroadcastState.history_tasks,
                            lambda t: rx.table.row(
                                rx.table.cell(
                                    rx.cond(t["task_name"], t["task_name"], "-"),
                                    size="1",
                                ),
                                rx.table.cell(
                                    rx.tooltip(
                                        rx.text(t["content"], size="1", truncate=True),
                                        content=t["content"],
                                    ),
                                    size="1",
                                ),
                                rx.table.cell(
                                    rx.text(
                                        rx.cond(
                                            t["schedule_type"] == "scheduled",
                                            "定时",
                                            "即时",
                                        ),
                                        size="1",
                                    ),
                                ),
                                rx.table.cell(_status_badge(t["status"])),
                                rx.table.cell(
                                    rx.text(
                                        rx.cond(t["scheduled_at"], t["scheduled_at"], "-"),
                                        size="1",
                                    ),
                                ),
                                rx.table.cell(
                                    rx.text(
                                        rx.cond(t["created_at"], t["created_at"], "-"),
                                        size="1",
                                    ),
                                ),
                            ),
                        ),
                    ),
                    size="1",
                    width="100%",
                ),
                max_height="400px",
                overflow_y="auto",
                width="100%",
            ),
            # 底部页数信息
            rx.flex(
                rx.text(
                    f"共 {BroadcastState.history_total} 条",
                    size="1",
                    color_scheme="gray",
                ),
                rx.spacer(),
                _pagination_controls(),
                width="100%",
                padding_top="2",
            ),
            # 关闭按钮
            rx.flex(
                rx.spacer(),
                rx.dialog.close(
                    rx.button("关闭", variant="soft", size="2", cursor="pointer"),
                ),
                padding_top="2",
            ),
            max_width="800px",
        ),
        open=BroadcastState.history_modal_open,
        on_open_change=BroadcastState.on_history_dialog_change,
    )


# ═══════════════════════════════════════════════════════
#  页面主体
# ═══════════════════════════════════════════════════════

def broadcast_page() -> rx.Component:
    return rx.fragment(
        rx.script(FMT_JS),
        with_sidebar(
            page_shell(
                "消息广播",
                # ① 目标选择
                target_selector(),
                rx.separator(),
                # ② 编辑 + 预览
                rx.flex(
                    editor_panel(),
                    rx.separator(orientation="vertical"),
                    preview_panel(),
                    width="100%",
                    align="start",
                    gap="4",
                ),
                rx.separator(),
                # ③ 发送
                action_bar(),
                # Toast
                rx.cond(
                    BroadcastState.submit_toast != "",
                    rx.callout(
                        BroadcastState.submit_toast,
                        icon="info",
                        color_scheme="plum",
                    ),
                ),
                header_action=rx.icon_button(
                    rx.icon("clock", size=18),
                    variant="ghost",
                    size="2",
                    color_scheme="gray",
                    cursor="pointer",
                    on_click=BroadcastState.open_history,
                ),
            ),
        ),
        # ── @提及 / #引用 弹窗 ──
        mention_dialog(),
        # ── 发送历史弹窗 ──
        history_dialog(),
    )

