"""机器人消息模板配置页面"""
import reflex as rx
from ..state.message_state import MessageState
from ..components.sidebar import page_shell, with_sidebar


def message_list_panel() -> rx.Component:
    """左侧：消息类型列表（仅显示轻量标题，变量说明移到右侧）"""
    return rx.box(
        rx.vstack(
            rx.heading("消息类型", size="4"),
            rx.divider(),
            # 列表项：超出最大高度后内部滚动（仅显示中文名）
            rx.scroll_area(
                rx.vstack(
                    rx.foreach(
                        MessageState.messages,
                        lambda m: rx.card(
                            rx.vstack(
                                rx.text(
                                    m["display_name"],
                                    font_weight="bold",
                                    font_size="sm",
                                ),
                                rx.cond(
                                    m["is_customized"],
                                    rx.badge("已自定义", color_scheme="orange", size="1"),
                                ),
                                spacing="1",
                                width="100%",
                                align="start",
                            ),
                            width="100%",
                            cursor="pointer",
                            border=rx.cond(
                                MessageState.editing_key == m["message_key"],
                                "2px solid var(--accent-8)",
                                "1px solid var(--gray-5)",
                            ),
                            on_click=MessageState.begin_edit(m["message_key"]),
                        ),
                    ),
                    spacing="2",
                    width="100%",
                ),
                height="65vh",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def editor_panel() -> rx.Component:
    """右侧：编辑区 — 标题用中文名，变量说明放在文本框上方"""
    return rx.card(
        rx.cond(
            MessageState.editing_key != "",
            rx.vstack(
                rx.vstack(
                    rx.heading(MessageState.editing_display_name, size="4"),
                    rx.text(
                        MessageState.editing_key,
                        font_size="xs",
                        color="gray",
                        font_family="monospace",
                    ),
                    spacing="0",
                    align="start",
                ),
                # 变量说明区（放在文本框上方，逐行解释变量含义）
                rx.cond(
                    MessageState.selected_var_lines.length() > 0,
                    rx.vstack(
                        rx.text("可用变量（直接插入到文本中）", font_weight="bold", font_size="sm"),
                        rx.box(
                            rx.vstack(
                                rx.foreach(
                                    MessageState.selected_var_lines,
                                    lambda v: rx.hstack(
                                        rx.badge(
                                            rx.text("{" + v["name"] + "}"),
                                            variant="soft",
                                            color_scheme="purple",
                                            size="1",
                                        ),
                                        rx.text(
                                            rx.cond(
                                                v["desc"] != "",
                                                v["desc"],
                                                "（未提供说明）",
                                            ),
                                            font_size="sm",
                                            color="gray",
                                        ),
                                        spacing="2",
                                        align="center",
                                        width="100%",
                                    ),
                                ),
                                spacing="1",
                                width="100%",
                            ),
                            background="var(--gray-3)",
                            padding="3",
                            border_radius="md",
                            width="100%",
                        ),
                        spacing="1",
                        width="100%",
                    ),
                ),
                rx.text("消息内容", font_weight="bold", font_size="sm"),
                rx.text_area(
                    value=MessageState.edit_value,
                    on_change=MessageState.set_edit_value,
                    min_height="150px",
                    width="100%",
                    font_size="sm",
                ),
                rx.hstack(
                    rx.button(
                        "保存",
                        color_scheme="green",
                        cursor="pointer",
                        on_click=MessageState.save_message,
                    ),
                    rx.button(
                        "重置为默认",
                        variant="soft",
                        color_scheme="red",
                        cursor="pointer",
                        on_click=MessageState.reset_message(
                            MessageState.editing_key,
                        ),
                    ),
                    rx.spacer(),
                    rx.button(
                        "取消",
                        variant="outline",
                        cursor="pointer",
                        on_click=MessageState.cancel_edit,
                    ),
                    spacing="2",
                    width="100%",
                ),
                # 当前文本预览
                rx.text(
                    "效果预览：",
                    font_weight="bold",
                    font_size="sm",
                    margin_top="0.5em",
                ),
                rx.card(
                    rx.text(
                        MessageState.edit_value,
                        font_size="sm",
                        white_space="pre-wrap",
                    ),
                    width="100%",
                    background="var(--gray-3)",
                ),
                spacing="3",
                width="100%",
            ),
            # 未选择时
            rx.vstack(
                rx.icon("arrow-left", size=40, color="gray"),
                rx.text(
                    "← 从左侧列表选择一条消息开始编辑",
                    color="gray",
                    font_size="sm",
                ),
                spacing="3",
                align="center",
                justify="center",
                min_height="300px",
                width="100%",
            ),
        ),
        width="100%",
        min_height="400px",
    )


@rx.page(
    route="/messages",
    title="消息配置",
    on_load=MessageState.load_data,
)
def messages_page() -> rx.Component:
    return with_sidebar(
        rx.fragment(
            page_shell(
                "消息配置",
                "管理机器人的回复消息模板",
                # 左右双栏（比例 30% : 70%）
                rx.hstack(
                    rx.box(message_list_panel(), width="30%", min_width="240px"),
                    rx.box(editor_panel(), width="70%", min_width="400px"),
                    spacing="4",
                    align="start",
                    width="100%",
                ),
            ),
            # 浮动飘字
            rx.cond(
                MessageState.toast_text != "",
                rx.box(
                    rx.text(
                        MessageState.toast_text,
                        font_size="sm",
                        color="white",
                    ),
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
