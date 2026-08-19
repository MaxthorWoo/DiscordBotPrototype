import reflex as rx
from ..state import EventState, BotState
from ..components.sidebar import page_shell, with_sidebar


@rx.page(route="/", on_load=[EventState.load_events, BotState.load_bot])
def home_page() -> rx.Component:
    return with_sidebar(
        page_shell(
            "机器人管理后台",
            # 未配置 Bot 时的引导
            rx.cond(
                ~BotState.has_token,
                rx.callout(
                    rx.hstack(
                        rx.icon("info", size=16),
                        rx.vstack(
                            rx.text("尚未配置 Bot Token，前往设置以激活平台功能", font_size="sm"),
                            rx.link(
                                "前往 Bot 设置 →",
                                href="/bot-settings",
                                font_size="sm",
                                color="var(--accent-10)",
                            ),
                            spacing="1",
                        ),
                        spacing="3",
                        align="start",
                    ),
                    color_scheme="blue",
                    width="100%",
                ),
            ),
            rx.heading("系统日志", size="4"),
            rx.foreach(
                EventState.events,
                lambda log: rx.card(
                    rx.hstack(
                        rx.badge(log["source"], color_scheme=rx.cond(log["source"]=="bot", "blue", "green")),
                        rx.badge(log["type"]),
                        rx.text(log["msg"]),
                        rx.text(log["time"], font_size="sm", color="gray"),
                    )
                )
            ),
        )
    )
