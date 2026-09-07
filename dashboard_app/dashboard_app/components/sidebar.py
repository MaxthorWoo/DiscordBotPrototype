"""侧边栏导航组件 — 路由高亮 + 悬浮效果 + 底部图标栏 + 设置弹窗"""
import reflex as rx
from ..state.bot_state import BotState


# ── 导航项配置 ───────────────────────────────────────────
NAV_ITEMS = [
    ("home",            "首页",      "/"),
    ("server",          "系统监控", "/guilds"),
    ("shield-alert",    "陷阱日志",  "/trap"),
    ("gift",            "礼包码管理", "/giftcodes"),
    ("message-square",  "消息配置",  "/messages"),
    ("radio",           "消息广播",  "/broadcast"),
    ("ticket",          "抽奖管理",  "/draw"),
]


# ── 导航状态：追踪当前路由 ───────────────────────────────
class NavState(rx.State):
    """侧边栏导航状态，提供当前路径用于高亮判断。

    注意：router.url 是【完整 URL】（含 origin，如 http://host:port/guilds），
    不能直接和导航 href（如 /guilds）比较，会导致高亮永远失效。
    必须用 router.route_id（纯路径），或从 url 中截取 pathname。
    """

    @rx.var(cache=False)
    def current_path(self) -> str:
        # route_id 是纯路径（如 /guilds）。注意：不能调用 urlparse(self.router.url)，
        # 因为在 @rx.var 里 self.router.url 是前端 Var，不是真实字符串，外部函数无法处理。
        # 直接用 route_id，并做规范化：去尾斜杠，空串回退为 "/"。
        path = self.router.route_id
        path = (path or "").rstrip("/")
        return path or "/"


# ── 导航链接 ─────────────────────────────────────────────
# 毛玻璃（frosted glass）风格：半透明背景 + backdrop-filter 模糊，
# 悬浮与激活态统一视觉，随背景渐变透出质感。
NAV_CSS = """
.side-nav-link {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    width: 100%;
    padding: 0.5rem 0.75rem;
    border-radius: 10px;
    background: transparent;
    color: var(--gray-11);
    font-size: 0.875rem;
    font-weight: 400;
    transition: all 0.2s ease;
    cursor: pointer;
    -webkit-backdrop-filter: blur(8px);
    backdrop-filter: blur(8px);
}
.side-nav-link:hover {
    background: rgba(128, 128, 128, 0.10);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    color: var(--gray-12);
}
.side-nav-link--active {
    background: rgba(171, 74, 186, 0.16);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    color: var(--plum-11);
    font-weight: 600;
    box-shadow: inset 0 0 0 1px rgba(171, 74, 186, 0.35),
                0 2px 8px rgba(0, 0, 0, 0.06);
}
.side-nav-link--active:hover {
    background: rgba(171, 74, 186, 0.22);
}
"""


def _nav_link(icon: str, label: str, href: str) -> rx.Component:
    """单个导航项 — 高亮由 NavState.current_path（route_id 纯路径）响应式驱动。

    - 首页(href="/")：仅当路径恰为 "/" 时高亮。
    - 其他导航：精确匹配，或当前路径是该导航下的子路径（如 /guilds/123 高亮 /guilds）。
    """
    if href == "/":
        is_active = NavState.current_path == "/"
    else:
        # 路径相等，或是以 "href/" 开头的子路径
        is_active = (NavState.current_path == href) | NavState.current_path.startswith(href + "/")
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=18),
            rx.text(label),
            # 激活态通过切换 CSS 类实现毛玻璃高亮
            class_name=rx.cond(
                is_active,
                "side-nav-link side-nav-link--active",
                "side-nav-link",
            ),
        ),
        href=href,
        width="100%",
        text_decoration="none",
    )


def nav_section() -> rx.Component:
    """导航菜单区块 — 固定 7 项，每项 icon 为字面量字符串"""
    return rx.vstack(
        _nav_link("home",           "首页",      "/"),
        _nav_link("server",         "系统监控", "/guilds"),
        _nav_link("shield-alert",   "陷阱日志",  "/trap"),
        _nav_link("gift",           "礼包码管理", "/giftcodes"),
        _nav_link("message-square", "消息配置",  "/messages"),
        _nav_link("radio",          "消息广播",  "/broadcast"),
        _nav_link("ticket",         "抽奖管理",  "/draw"),
        _nav_link("scan-eye",       "UID 采集",  "/uid"),
        spacing="1",
        width="100%",
        padding_x="2",
    )


# ── 统一机器人管理弹窗 ─────────────────────────────────
def bot_manager_dialog() -> rx.Component:
    """机器人管理弹窗：左侧机器人列表（点击切换），右侧逐字段行内编辑名称与 Token。

    点击列表里的某个机器人 = 整个后台切换到该机器人的管理平台（current_bot_id 全局生效）。
    新增机器人走二级弹窗，填写名称与 Token 后回到一级弹窗。
    """
    return rx.fragment(
        # ════ 一级弹窗：机器人管理 ════
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("机器人管理"),
                rx.dialog.description(
                    "点击左侧任意机器人即可切换整个后台到该机器人的管理平台；"
                    "右侧可逐行编辑其名称与 Token，保存即生效并自动上线",
                    size="2",
                    margin_bottom="6",
                ),
                # 主体：左列表 + 右编辑
                rx.hstack(
                    # ── 左：机器人列表 ──
                    rx.vstack(
                        rx.text("机器人列表", font_weight="bold", font_size="md", margin_bottom="2"),
                        rx.scroll_area(
                            rx.vstack(
                                rx.foreach(
                                    BotState.bots_list,
                                    lambda bot: rx.hstack(
                                        rx.box(
                                            width="8px",
                                            height="8px",
                                            border_radius="50%",
                                            background=rx.cond(
                                                bot["status"] == "online",
                                                "var(--green-9)",
                                                rx.cond(
                                                    bot["status"] == "offline",
                                                    "var(--yellow-9)",
                                                    rx.cond(
                                                        bot["status"] == "stopped",
                                                        "var(--gray-8)",
                                                        "var(--red-9)",  # unconfigured / error
                                                    ),
                                                ),
                                            ),
                                            flex_shrink="0",
                                        ),
                                        rx.vstack(
                                            rx.text(
                                                bot["bot_name"],
                                                font_size="sm",
                                                color=rx.cond(
                                                    bot["bot_id"] == BotState.current_bot_id,
                                                    "var(--plum-11)",
                                                    "var(--gray-12)",
                                                ),
                                                font_weight=rx.cond(
                                                    bot["bot_id"] == BotState.current_bot_id,
                                                    "600",
                                                    "400",
                                                ),
                                            ),
                                            rx.text(
                                                rx.cond(
                                                    bot["status"] == "online", "运行中",
                                                    rx.cond(
                                                        bot["status"] == "offline", "离线（进程异常）",
                                                        rx.cond(
                                                            bot["status"] == "stopped", "已停止",
                                                            rx.cond(
                                                                bot["status"] == "error", "启动失败",
                                                                "未配置 Token",
                                                            ),
                                                        ),
                                                    ),
                                                ),
                                                font_size="xs",
                                                color="var(--gray-10)",
                                            ),
                                            rx.cond(
                                                bot["status"] == "error",
                                                rx.text(
                                                    rx.cond(
                                                        bot["error"] != "",
                                                        bot["error"],
                                                        "启动失败，请检查 Token 与 Discord 应用权限",
                                                    ),
                                                    font_size="xs",
                                                    color="var(--red-10)",
                                                    max_width="150px",
                                                    white_space="normal",
                                                ),
                                                rx.fragment(),
                                            ),
                                            spacing="0",
                                            align="start",
                                        ),
                                        rx.spacer(),
                                        # 启动/停止按钮
                                        rx.cond(
                                            bot["status"] == "unconfigured",
                                            rx.tooltip(
                                                rx.icon("circle-alert", size=14, color="var(--red-9)"),
                                                content="需先配置 Token",
                                            ),
                                            rx.cond(
                                                bot["status"] == "online",
                                                rx.icon_button(
                                                    rx.icon("power-off", size=14),
                                                    on_click=BotState.stop_bot(bot["bot_id"]),
                                                    variant="ghost",
                                                    color_scheme="gray",
                                                    size="1",
                                                    cursor="pointer",
                                                ),
                                                rx.icon_button(
                                                    rx.icon("power", size=14),
                                                    on_click=BotState.start_bot(bot["bot_id"]),
                                                    variant="ghost",
                                                    color_scheme="green",
                                                    size="1",
                                                    cursor="pointer",
                                                ),
                                            ),
                                        ),
                                        spacing="2",
                                        align="center",
                                        width="100%",
                                        padding="0.5rem 0.7rem",
                                        border_radius="md",
                                        background=rx.cond(
                                            bot["bot_id"] == BotState.current_bot_id,
                                            "rgba(171, 74, 186, 0.16)",
                                            "transparent",
                                        ),
                                        cursor="pointer",
                                        on_click=BotState.select_bot(bot["bot_id"]),
                                    ),
                                ),
                                spacing="1",
                                width="100%",
                            ),
                            max_height="340px",
                            width="100%",
                        ),
                        # 新增机器人（仅按钮，点击弹出二级弹窗）
                        rx.button(
                            "＋ 新增机器人",
                            color_scheme="green",
                            variant="soft",
                            cursor="pointer",
                            width="100%",
                            margin_top="3",
                            on_click=BotState.open_add_dialog,
                        ),
                        spacing="2",
                        width="240px",
                        padding_right="4",
                        padding_top="2",
                        border_right="1px solid var(--gray-5)",
                    ),
                    # ── 右：选中机器人编辑区 ──
                    rx.vstack(
                        rx.text("当前机器人配置", font_weight="bold", font_size="md", margin_bottom="4"),
                        rx.cond(
                            BotState.is_loaded,
                            rx.vstack(
                                # ── Bot 名称行（展示/编辑）──
                                rx.cond(
                                    BotState.editing_name,
                                    # 编辑态
                                    rx.vstack(
                                        rx.text("Bot 名称", font_size="sm", color="var(--gray-11)"),
                                        rx.input(
                                            placeholder="例如：我的交易Bot",
                                            value=BotState.bot_name_input,
                                            on_change=BotState.set_bot_name,
                                            width="100%",
                                        ),
                                        rx.hstack(
                                            rx.button(
                                                "保存",
                                                color_scheme="green",
                                                cursor="pointer",
                                                on_click=BotState.save_name,
                                            ),
                                            rx.button(
                                                "取消",
                                                variant="ghost",
                                                cursor="pointer",
                                                on_click=BotState.cancel_name,
                                            ),
                                            spacing="2",
                                        ),
                                        spacing="2",
                                        width="100%",
                                    ),
                                    # 展示态
                                    rx.hstack(
                                        rx.vstack(
                                            rx.text("Bot 名称", font_size="sm", color="var(--gray-11)"),
                                            rx.text(
                                                BotState.bot_name,
                                                font_size="md",
                                                font_weight="bold",
                                            ),
                                            spacing="1",
                                            align="start",
                                        ),
                                        rx.spacer(),
                                        rx.icon_button(
                                            "pencil",
                                            on_click=BotState.edit_name,
                                            size="1",
                                            variant="ghost",
                                            color_scheme="gray",
                                            cursor="pointer",
                                            aria_label="编辑名称",
                                        ),
                                        align="center",
                                        width="100%",
                                    ),
                                ),
                                # ── Bot Token 行（展示/编辑）──
                                rx.cond(
                                    BotState.editing_token,
                                    # 编辑态
                                    rx.vstack(
                                        rx.text("Bot Token", font_size="sm", color="var(--gray-11)"),
                                        rx.cond(
                                            BotState.token_mask != "",
                                            rx.callout(
                                                rx.fragment(
                                                    rx.icon("shield-check", size=14),
                                                    rx.text(
                                                        f"{BotState.token_mask} 已配置，留空则保留原 Token",
                                                        font_size="xs",
                                                    ),
                                                ),
                                                color_scheme="green",
                                                size="1",
                                                width="100%",
                                            ),
                                            rx.text(
                                                "在 Discord Developer Portal → Bot 页面获取",
                                                font_size="xs",
                                                color="gray",
                                            ),
                                        ),
                                        rx.input(
                                            placeholder="输入或更新你的 Bot Token...",
                                            value=BotState.bot_token_input,
                                            on_change=BotState.set_bot_token,
                                            type="password",
                                            width="100%",
                                        ),
                                        rx.hstack(
                                            rx.button(
                                                "保存",
                                                color_scheme="green",
                                                cursor="pointer",
                                                on_click=BotState.save_token,
                                            ),
                                            rx.button(
                                                "测试连接",
                                                variant="outline",
                                                cursor="pointer",
                                                on_click=BotState.test_connection,
                                            ),
                                            rx.button(
                                                "取消",
                                                variant="ghost",
                                                cursor="pointer",
                                                on_click=BotState.cancel_token,
                                            ),
                                            spacing="2",
                                        ),
                                        rx.cond(
                                            BotState.test_result == "testing",
                                            rx.callout("正在测试连接...", color_scheme="gray", width="100%"),
                                        ),
                                        rx.cond(
                                            BotState.test_result == "success",
                                            rx.callout("连接成功！Token 有效", color_scheme="green", width="100%"),
                                        ),
                                        rx.cond(
                                            BotState.test_result == "failed",
                                            rx.callout(BotState.test_message, color_scheme="red", width="100%"),
                                        ),
                                        spacing="2",
                                        width="100%",
                                    ),
                                    # 展示态
                                    rx.hstack(
                                        rx.vstack(
                                            rx.text("Bot Token", font_size="sm", color="var(--gray-11)"),
                                            rx.cond(
                                                BotState.has_token,
                                                rx.hstack(
                                                    rx.icon("shield-check", size=14, color="var(--grass-9)"),
                                                    rx.text("•••••••• 已配置", font_size="md"),
                                                    spacing="2",
                                                    align="center",
                                                ),
                                                rx.text("未配置", font_size="md", color="var(--gray-9)"),
                                            ),
                                            spacing="1",
                                            align="start",
                                        ),
                                        rx.spacer(),
                                        rx.icon_button(
                                            "pencil",
                                            on_click=BotState.edit_token,
                                            size="2",
                                            variant="ghost",
                                            color_scheme="gray",
                                            cursor="pointer",
                                            aria_label="编辑 Token",
                                        ),
                                        align="center",
                                        width="100%",
                                    ),
                                ),
                                spacing="6",
                                width="100%",
                            ),
                            rx.text("请选择左侧的机器人", color="var(--gray-9)"),
                        ),
                        rx.spacer(),
                        rx.dialog.close(
                            rx.button("关闭", variant="soft", color_scheme="gray", cursor="pointer"),
                        ),
                        spacing="4",
                        width="360px",
                        padding_left="3",
                        padding_top="2",
                    ),
                    spacing="5",
                    align="start",
                    width="100%",
                ),
                spacing="5",
                max_width="760px",
                padding="6",
            ),
            open=BotState.show_manager,
            on_open_change=BotState.handle_manager_change,
        ),
        # ════ 二级弹窗：新增机器人 ════
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("新增机器人"),
                rx.dialog.description(
                    "填写机器人名称与 Token，保存后该机器人会出现在左侧列表中",
                    size="2",
                    margin_bottom="5",
                ),
                rx.vstack(
                    rx.text("机器人名称", font_size="sm", color="var(--gray-11)"),
                    rx.input(
                        placeholder="例如：我的交易Bot",
                        value=BotState.add_name_input,
                        on_change=BotState.set_add_name,
                        width="100%",
                    ),
                    rx.text("Bot Token（可选，留空可稍后在配置中填写）", font_size="sm", color="var(--gray-11)"),
                    rx.input(
                        placeholder="输入或更新你的 Bot Token...",
                        value=BotState.add_token_input,
                        on_change=BotState.set_add_token,
                        type="password",
                        width="100%",
                    ),
                    rx.cond(
                        BotState.add_toast != "",
                        rx.callout(BotState.add_toast, color_scheme="red", width="100%"),
                    ),
                    rx.hstack(
                        rx.button(
                            "保存",
                            color_scheme="green",
                            cursor="pointer",
                            on_click=BotState.confirm_add,
                        ),
                        rx.button(
                            "取消",
                            variant="ghost",
                            cursor="pointer",
                            on_click=BotState.cancel_add,
                        ),
                        rx.spacer(),
                        spacing="2",
                        width="100%",
                    ),
                    spacing="3",
                    width="100%",
                ),
                spacing="5",
                max_width="460px",
                padding="6",
            ),
            open=BotState.show_add_dialog,
            on_open_change=BotState.add_dialog_open_change,
        ),
    )


# ── 底部栏：Bot 状态 + 设置 + 主题 ───────────────────────
def sidebar_bottom() -> rx.Component:
    """侧边栏底部：Bot 名称 + 在线指示 + 设置齿轮 + 日夜切换"""
    return rx.vstack(
        # Bot 状态指示
        rx.cond(
            BotState.sidebar_bot_name != "",
            rx.hstack(
                rx.box(
                    width="8px",
                    height="8px",
                    border_radius="50%",
                    background=rx.cond(
                        BotState.is_active,
                        "var(--green-9)",
                        "var(--gray-8)",
                    ),
                    flex_shrink="0",
                ),
                rx.text(
                    BotState.sidebar_bot_name,
                    font_size="xs",
                    color="var(--gray-11)",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.text(
                "未配置 Bot",
                font_size="xs",
                color="var(--gray-9)",
            ),
        ),
        # 图标按钮：设置（机器人管理） + 日夜模式
        rx.hstack(
            rx.icon_button(
                rx.icon("settings", size=18),
                on_click=BotState.open_settings,
                variant="ghost",
                color_scheme="gray",
                size="2",
                cursor="pointer",
            ),
            rx.spacer(),
            rx.color_mode.button(
                size="1",
                variant="ghost",
                color_scheme="gray",
                cursor="pointer",
            ),
            spacing="2",
            justify="center",
            width="100%",
        ),
        spacing="3",
        width="100%",
        padding="2",
        # padding_top="3",
        # padding_x="1",
        border_top="1px solid var(--gray-5)",
    )


# ── 侧边栏主体 ───────────────────────────────────────────
def sidebar() -> rx.Component:
    """全局侧边栏导航 — 上方品牌 + 中间菜单 + 下方工具栏"""
    return rx.box(
        # 注入自定义 CSS（高亮由 Reflex 响应式 prop 驱动，无需 JS）
        rx.html(f"<style>{NAV_CSS}</style>"),
        rx.vstack(
            # Logo / 品牌
            rx.hstack(
                rx.icon("mountain", size=22, color="var(--plum-9)"),
                rx.heading("DiscordBot", size="5", color="var(--plum-11)"),
                spacing="2",
                align="center",
            ),
            rx.divider(size="4"),
            # 导航菜单
            nav_section(),
            # 弹性空白
            rx.box(flex="1"),
            # 底部工具栏
            sidebar_bottom(),
            # 容器样式
            class_name="iip-sidebar",
            spacing="3",
            width="220px",
            height="100vh",
            padding="1em",
            border_right="1px solid var(--gray-5)",
            position="fixed",
            left="0",
            top="0",
        ),
    )


# ── 统一页面外壳 ─────────────────────────────────────────
def page_shell(
    title: str,
    subtitle: str = "",
    *children: rx.Component,
    header_action: rx.Component | None = None,
) -> rx.Component:
    """统一页面布局外壳 — 标题 + 分隔线 + 内容，标准化间距

    Args:
        title: 页面标题
        subtitle: 可选的副标题
        *children: 页面主体内容
        header_action: 可选的标题栏右侧操作（如图标按钮），传入则显示在标题右上角
    """
    # 编译期分支：根据是否传入 header_action 选择标题行右侧结构
    if header_action is not None:
        title_row = rx.hstack(
            rx.vstack(
                rx.heading(title, size="6"),
                rx.cond(
                    subtitle != "",
                    rx.text(subtitle, color="gray", font_size="sm"),
                ),
                spacing="1",
            ),
            rx.spacer(),
            header_action,
            width="100%",
            align="center",
        )
    else:
        title_row = rx.hstack(
            rx.vstack(
                rx.heading(title, size="6"),
                rx.cond(
                    subtitle != "",
                    rx.text(subtitle, color="gray", font_size="sm"),
                ),
                spacing="1",
            ),
            width="100%",
        )

    return rx.box(
        rx.vstack(
            title_row,
            rx.divider(size="4"),
            *children,
            spacing="4",
            width="100%",
        ),
        padding="2em",
        max_width="1200px",
        width="100%",
        margin_x="auto",  # 在减去 sidebar 后的空间内水平居中
    )


# ── 全局背景：渐变 + 左上角淡淡光芒 ──────────────────────
# 色系沿用主题（plum 主色 + gray 背景），左上角一抹柔和光芒。
# 关键：只在一个最外层容器上铺一次渐变，侧边栏与内容区全部透明，
# 保证背景连续无断层，全局只有一个背景。
GRADIENT_CSS = (
    "radial-gradient(circle at top left, rgba(171, 74, 186, 0.16), "
    "rgba(171, 74, 186, 0.05) 30%, transparent 55%), "
    "linear-gradient(160deg, var(--gray-1) 0%, var(--gray-2) 60%, var(--gray-3) 100%)"
)
GLOBAL_BG_CSS = f"""
body {{
    background: {GRADIENT_CSS};
    background-attachment: fixed;
    background-repeat: no-repeat;
    background-size: cover;
}}
/* 最外层整体布局容器：从左到右连续铺同一渐变，避免断层 */
.iip-layout {{
    background: {GRADIENT_CSS} !important;
    min-height: 100vh;
}}
/* 侧边栏与内容区全部透明，露出统一背景 */
.iip-sidebar,
.iip-content {{
    background: transparent !important;
}}
"""


# ── 页面布局包裹器 ───────────────────────────────────────
def with_sidebar(content: rx.Component) -> rx.Component:
    """在页面内容外包裹侧边栏布局，含全局弹窗"""
    return rx.hstack(
        # 注入全局背景样式（body 渐变 + 左上角光芒）
        rx.html(f"<style>{GLOBAL_BG_CSS}</style>"),
        sidebar(),
        rx.box(
            content,
            class_name="iip-content",
            flex="1",
            margin_left="220px",
            background="transparent",
        ),
        # 全局飘字
        rx.cond(
            BotState.save_toast != "",
            rx.box(
                rx.text(BotState.save_toast, font_size="sm", color="white"),
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
        # 统一机器人管理弹窗（全局存在）
        bot_manager_dialog(),
        # 布局容器：从左到右连续铺同一渐变，避免断层
        class_name="iip-layout",
        width="100%",
        min_height="100vh",
        background=GRADIENT_CSS,
    )
