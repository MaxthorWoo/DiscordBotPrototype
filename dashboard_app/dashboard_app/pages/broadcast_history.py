"""广播历史页面"""

import reflex as rx

from ..state.broadcast_state import BroadcastState
from ..components.sidebar import with_sidebar

STATUS_BADGE = {
    "pending": ("clock", "gray"),
    "sent": ("check", "green"),
    "failed": ("x", "red"),
    "draft": ("file", "orange"),
}


def history_page() -> rx.Component:
    return with_sidebar(
        rx.vstack(
            rx.heading("发送历史", size="5"),
            rx.separator(),
            rx.text("历史记录功能开发中…", color_scheme="gray"),
            spacing="3",
            padding="4",
        ),
    )
