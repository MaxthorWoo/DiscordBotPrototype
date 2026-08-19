"""统一抽奖管理页（传统抽奖 + 即开番赏 + 消息模板）"""
import reflex as rx
from ..state.draw_state import DrawState
from ..components.sidebar import page_shell, with_sidebar
from .messages import message_list_panel, editor_panel


LABEL_WIDTH = "90px"
INPUT_WIDTH = "360px"


def form_row(label: str, control: rx.Component) -> rx.Component:
    """统一表单行：标签右对齐 + 控件左对齐"""
    return rx.hstack(
        rx.text(label, width=LABEL_WIDTH, text_align="right", font_size="sm"),
        control,
        spacing="3",
        align="center",
        width="100%",
    )


# ===== 传统抽奖组件 =====
def raffle_create_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("创建传统抽奖", size="4"),
            form_row(
                "抽奖标题",
                rx.input(
                    value=DrawState.raffle_create_title,
                    placeholder="抽奖标题",
                    on_change=DrawState.set_raffle_create_title,
                    width=INPUT_WIDTH,
                ),
            ),
            form_row(
                "抽奖描述",
                rx.input(
                    value=DrawState.raffle_create_description,
                    placeholder="奖品描述（可选）",
                    on_change=DrawState.set_raffle_create_description,
                    width=INPUT_WIDTH,
                ),
            ),
            rx.hstack(
                rx.text("中奖人数", width=LABEL_WIDTH, text_align="right", font_size="sm"),
                rx.input(
                    value=DrawState.raffle_create_winner_count.to(str),
                    type="number", min=1,
                    on_change=DrawState.handle_raffle_winner_count,
                    width="100px",
                ),
                rx.text("开奖时间", width=LABEL_WIDTH, text_align="right", font_size="sm", margin_left="1em"),
                rx.input(
                    value=DrawState.raffle_create_draw_time,
                    type="datetime-local",
                    on_change=DrawState.set_raffle_create_draw_time,
                    width="210px",
                ),
                spacing="3", align="center", width="100%",
            ),
            form_row(
                "发布频道",
                rx.select.root(
                    rx.select.trigger(placeholder="选择频道..."),
                    rx.select.content(
                        rx.foreach(
                            DrawState.channel_options,
                            lambda ch: rx.select.item(ch["channel_name"], value=ch["channel_id"]),
                        ),
                    ),
                    value=DrawState.raffle_create_channel_id,
                    on_change=DrawState.set_raffle_create_channel_id,
                    width=INPUT_WIDTH,
                ),
            ),
            rx.hstack(
                rx.button("创建抽奖", on_click=DrawState.create_raffle, color_scheme="blue", cursor="pointer"),
                rx.cond(
                    DrawState.raffle_create_status != "",
                    rx.text(DrawState.raffle_create_status, font_size="sm", color="gray"),
                ),
                spacing="3", padding_left=LABEL_WIDTH,
            ),
            spacing="3", width="100%", align="start",
        ),
        width="100%",
    )


def raffle_list() -> rx.Component:
    return rx.cond(
        DrawState.raffles,
        rx.vstack(
            rx.foreach(
                DrawState.raffles,
                lambda r: rx.card(
                    rx.hstack(
                        rx.vstack(
                            rx.hstack(
                                rx.text(r["title"], font_weight="bold", font_size="md"),
                                rx.cond(
                                    r["is_drawn"],
                                    rx.badge("已开奖", color_scheme="yellow"),
                                    rx.cond(
                                        r["is_active"],
                                        rx.badge("进行中", color_scheme="green"),
                                        rx.badge("已取消", color_scheme="gray"),
                                    ),
                                ),
                                spacing="2", align="center",
                            ),
                            rx.hstack(
                                rx.text(
                                    "参与 " + r["participant_count"].to(str)
                                    + " | 中奖 " + r.get("actual_winners", 0).to(str)
                                    + "/" + r["winner_count"].to(str),
                                    font_size="1", color="gray",
                                ),
                                rx.cond(
                                    r["is_drawn"],
                                    rx.text(""),
                                    rx.cond(
                                        r["draw_time"] != None,
                                        rx.text(r["draw_time"]),
                                        rx.text("手动开奖"),
                                    ),
                                ),
                                spacing="3", align="center",
                            ),
                            spacing="1", align="start",
                        ),
                        rx.spacer(),
                        rx.button("查看", size="2", color_scheme="blue", cursor="pointer",
                                  on_click=lambda _: DrawState.view_raffle_detail(r["id"])),
                        rx.button("删除", size="2", color_scheme="red", variant="outline", cursor="pointer",
                                  on_click=lambda _: DrawState.confirm_delete_raffle(r["id"])),
                        spacing="2", width="100%", align="center",
                    ),
                    width="100%",
                ),
            ),
            spacing="2", width="100%",
        ),
        rx.text("暂无传统抽奖数据", color="gray"),
    )


def raffle_detail_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.hstack(
                    rx.text("抽奖详情 — " + DrawState.raffle_detail.get("title", "").to(str)),
                    rx.spacer(),
                    rx.dialog.close(rx.icon_button("x", variant="ghost", color_scheme="gray", cursor="pointer")),
                    align="center",
                ),
            ),
            rx.dialog.description(
                rx.vstack(
                    rx.hstack(
                        rx.text("参与人数: " + DrawState.raffle_detail.get("participant_count", 0).to(str)),
                        rx.text("中奖人数: " + DrawState.raffle_detail.get("winner_count", 1).to(str)),
                        rx.cond(
                            DrawState.raffle_detail.get("draw_time") != "",
                            rx.text("开奖时间: " + DrawState.raffle_detail.get("draw_time", "").to(str)),
                            rx.text("开奖时间: 手动"),
                        ),
                        spacing="4", font_size="1",
                    ),
                    rx.divider(),
                    rx.heading("参与者名单", size="3"),
                    rx.cond(
                        DrawState.raffle_participants,
                        rx.box(
                            rx.table.root(
                                rx.table.header(
                                    rx.table.row(
                                        rx.table.column_header_cell("用户"),
                                        rx.table.column_header_cell("参与时间"),
                                        rx.table.column_header_cell("结果"),
                                    )
                                ),
                                rx.table.body(
                                    rx.foreach(
                                        DrawState.raffle_participants,
                                        lambda p: rx.table.row(
                                            rx.table.cell(p["user_name"]),
                                            rx.table.cell(p["joined_at"]),
                                            rx.table.cell(
                                                rx.cond(
                                                    p["is_winner"],
                                                    rx.badge("🏆 中奖", color_scheme="yellow"),
                                                    rx.text("—"),
                                                ),
                                            ),
                                        ),
                                    ),
                                ),
                                width="100%",
                            ),
                            max_height="400px", overflow_y="auto",
                        ),
                        rx.text("暂无参与者"),
                    ),
                    spacing="3", width="100%",
                ),
                width="100%",
            ),
            max_width="650px",
        ),
        open=DrawState.raffle_detail_modal_open,
        on_open_change=DrawState.on_raffle_detail_dialog_change,
    )


def raffle_delete_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("确认删除"),
            rx.dialog.description(
                rx.text("确定要删除这条传统抽奖记录吗？所有参与数据也将被清除。此操作不可撤销。"),
            ),
            rx.hstack(
                rx.dialog.close(rx.button("取消", variant="outline", cursor="pointer")),
                rx.button("确认删除", color_scheme="red", cursor="pointer",
                          on_click=DrawState.execute_delete_raffle),
                spacing="3", justify="end", width="100%",
            ),
        ),
        open=DrawState.raffle_delete_confirm_open,
        on_open_change=DrawState.on_raffle_delete_dialog_change,
    )


# ===== 即开番赏组件 =====
_MAX_PRIZE_ROWS = 15


def _prize_item_by_idx(idx: int) -> rx.Component:
    """Explicit-index prize row — avoids rx.foreach closure bugs in Reflex 0.9.x"""
    p = DrawState.prizes[idx]
    return rx.hstack(
        rx.input(
            value=p.tier_label,
            placeholder="S/A/B/LAST",
            on_change=DrawState.set_prize_field_by_idx(idx, "tier_label"),
            width="90px",
            id=f"prize-idx-{idx}-tier",
        ),
        rx.input(
            value=p.prize_name,
            placeholder="手办/钥匙扣...",
            on_change=DrawState.set_prize_field_by_idx(idx, "prize_name"),
            width="160px",
            id=f"prize-idx-{idx}-name",
        ),
        rx.input(
            value=p.emoji,
            placeholder="🎁",
            on_change=DrawState.set_prize_field_by_idx(idx, "emoji"),
            width="80px",
            id=f"prize-idx-{idx}-emoji",
        ),
        rx.input(
            value=p.count.to(str),
            type="number",
            min=1,
            on_change=DrawState.set_prize_field_by_idx(idx, "count"),
            width="70px",
            id=f"prize-idx-{idx}-count",
        ),
        rx.button(
            "✕",
            size="1",
            variant="ghost",
            color_scheme="red",
            cursor="pointer",
            on_click=DrawState.remove_prize_row_by_idx(idx),
            id=f"prize-idx-{idx}-del",
        ),
        spacing="2",
        align="center",
        width="100%",
        id=f"prize-row-idx-{idx}",
    )


def lottery_create_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("创建即开番赏（固定奖池模式）", size="4"),
            form_row(
                "标题",
                rx.input(value=DrawState.lottery_create_title, placeholder="一番赏标题",
                         on_change=DrawState.set_lottery_create_title, width=INPUT_WIDTH),
            ),
            form_row(
                "描述",
                rx.input(value=DrawState.lottery_create_description, placeholder="奖品池描述（可选）",
                         on_change=DrawState.set_lottery_create_description, width=INPUT_WIDTH),
            ),
            rx.hstack(
                rx.text("开始时间", width=LABEL_WIDTH, text_align="right", font_size="sm"),
                rx.input(value=DrawState.lottery_create_start_time, type="datetime-local",
                         on_change=DrawState.set_lottery_create_start_time, width="190px"),
                rx.text("结束时间", width=LABEL_WIDTH, text_align="right", font_size="sm", margin_left="1em"),
                rx.input(value=DrawState.lottery_create_end_time, type="datetime-local",
                         on_change=DrawState.set_lottery_create_end_time, width="190px"),
                spacing="3", align="center", width="100%",
            ),
            rx.hstack(
                rx.text("总抽数", width=LABEL_WIDTH, text_align="right", font_size="sm"),
                rx.input(value=DrawState.lottery_create_total_slots.to(str), type="number", min=1,
                         on_change=DrawState.handle_lottery_total_slots, width="100px"),
                rx.text("每人限抽", width=LABEL_WIDTH, text_align="right", font_size="sm", margin_left="1em"),
                rx.input(value=DrawState.lottery_create_max_draws.to(str), type="number", min=1,
                         on_change=DrawState.handle_lottery_max_draws, width="100px"),
                spacing="3", align="center", width="100%",
            ),
            form_row(
                "发布频道",
                rx.select.root(
                    rx.select.trigger(placeholder="选择频道..."),
                    rx.select.content(
                        rx.foreach(
                            DrawState.channel_options,
                            lambda ch: rx.select.item(ch["channel_name"], value=ch["channel_id"]),
                        ),
                    ),
                    value=DrawState.lottery_create_channel_id,
                    on_change=DrawState.set_lottery_create_channel_id,
                    width=INPUT_WIDTH,
                ),
            ),
            rx.divider(),
            rx.heading("奖品配置", size="4"),
            rx.text(
                "奖池总数 " + DrawState.lottery_create_total_slots.to(str)
                + " 抽。未分配奖项的剩余抽数为「谢谢参与」（创建时自动填充）",
                font_size="xs", color="gray",
            ),
            rx.cond(
                DrawState.prizes,
                rx.vstack(
                    rx.hstack(
                        rx.text("等级", width="90px", font_size="xs", color="gray"),
                        rx.text("奖品名", width="160px", font_size="xs", color="gray"),
                        rx.text("emoji", width="80px", font_size="xs", color="gray"),
                        rx.text("数量", width="70px", font_size="xs", color="gray"),
                        rx.text("", width="32px"),
                        spacing="2", align="center", width="100%", padding_left="0.5em",
                    ),
                    *[
                        rx.cond(
                            DrawState.prizes.length() > i,
                            _prize_item_by_idx(i),
                        )
                        for i in range(_MAX_PRIZE_ROWS)
                    ],
                    spacing="2", align="start", width="100%",
                ),
                rx.text("请添加至少一个奖品", color="gray"),
            ),
            rx.hstack(
                rx.button("+ 添加奖品", on_click=DrawState.add_prize_row, size="2", variant="soft", cursor="pointer"),
                spacing="3", padding_left=LABEL_WIDTH,
            ),
            rx.hstack(
                rx.button("创建抽奖", on_click=DrawState.create_lottery, color_scheme="blue", cursor="pointer"),
                rx.cond(
                    DrawState.lottery_create_status != "",
                    rx.text(DrawState.lottery_create_status, font_size="sm", color="gray"),
                ),
                spacing="3", padding_left=LABEL_WIDTH,
            ),
            spacing="3", width="100%", align="start",
        ),
        width="100%",
    )


def lottery_list() -> rx.Component:
    return rx.cond(
        DrawState.lotteries,
        rx.vstack(
            rx.foreach(
                DrawState.lotteries,
                lambda l: rx.card(
                    rx.hstack(
                        rx.vstack(
                            rx.hstack(
                                rx.text(l["title"], font_weight="bold", font_size="md"),
                                rx.cond(
                                    l["is_active"],
                                    rx.badge("进行中", color_scheme="green"),
                                    rx.badge("已结束", color_scheme="gray"),
                                ),
                                spacing="2", align="center",
                            ),
                            rx.text(
                                "已抽 " + l["slots_drawn"].to(str)
                                + "/" + l["total_slots"].to(str)
                                + " | 剩余 " + l["slots_left"].to(str)
                                + " | 限 " + l["max_draws_per_user"].to(str) + " 次/人",
                                font_size="1", color="gray",
                            ),
                            spacing="1", align="start",
                        ),
                        rx.spacer(),
                        rx.button("查看", size="2", color_scheme="blue", cursor="pointer",
                                  on_click=lambda _: DrawState.view_lottery_detail(l["id"])),
                        rx.button("删除", size="2", color_scheme="red", variant="outline", cursor="pointer",
                                  on_click=lambda _: DrawState.confirm_delete_lottery(l["id"])),
                        spacing="2", width="100%", align="center",
                    ),
                    width="100%",
                ),
            ),
            spacing="2", width="100%",
        ),
        rx.text("暂无即开番赏数据", color="gray"),
    )


def lottery_detail_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.hstack(
                    rx.text("抽奖详情 — " + DrawState.lottery_detail_title.to(str)),
                    rx.spacer(),
                    rx.dialog.close(rx.icon_button("x", variant="ghost", color_scheme="gray", cursor="pointer")),
                    align="center",
                ),
            ),
            rx.dialog.description(
                rx.vstack(
                    rx.text(
                        "进度 " + DrawState.lottery_detail_slots_drawn.to(str)
                        + "/" + DrawState.lottery_detail_total_slots.to(str)
                        + " | 中奖 " + DrawState.lottery_detail_hit_count.to(str) + " 人次"
                        + " | 剩余 " + DrawState.lottery_detail_slots_left.to(str) + " 抽",
                        font_size="sm",
                    ),
                    rx.divider(),
                    rx.heading("奖品剩余", size="3"),
                    rx.cond(
                        DrawState.lottery_detail_prizes,
                        rx.vstack(
                            rx.foreach(
                                DrawState.lottery_detail_prizes,
                                lambda p: rx.hstack(
                                    rx.text(p.get("emoji", "🎁").to(str)),
                                    rx.text(p.get("tier_label", "").to(str) + " — " + p.get("prize_name", "").to(str)),
                                    rx.spacer(),
                                    rx.text(p.get("remaining", 0).to(str) + "/" + p.get("total_count", 1).to(str)),
                                    rx.cond(
                                        p.get("remaining", 0) == 0,
                                        rx.badge("售罄", color_scheme="red"),
                                    ),
                                    spacing="2", width="100%",
                                ),
                            ),
                            spacing="1",
                        ),
                        rx.text("无奖品"),
                    ),
                    rx.divider(),
                    rx.heading("最近抽取", size="3"),
                    rx.cond(
                        DrawState.lottery_detail_recent_draws,
                        rx.vstack(
                            rx.foreach(
                                DrawState.lottery_detail_recent_draws,
                                lambda d: rx.text(
                                    d["emoji"].to(str) + " **" + d["user_name"].to(str)
                                    + "** → " + d["tier_label"].to(str) + " " + d["prize_name"].to(str),
                                    font_size="sm",
                                ),
                            ),
                            spacing="1",
                        ),
                        rx.text("暂无抽取记录", color="gray"),
                    ),
                    rx.divider(),
                    rx.heading("中奖记录（仅中奖）", size="3"),
                    rx.cond(
                        DrawState.lottery_draw_records,
                        rx.box(
                            rx.table.root(
                                rx.table.header(
                                    rx.table.row(
                                        rx.table.column_header_cell("用户"),
                                        rx.table.column_header_cell("奖品"),
                                        rx.table.column_header_cell("时间"),
                                    )
                                ),
                                rx.table.body(
                                    rx.foreach(
                                        DrawState.lottery_draw_records,
                                        lambda r: rx.table.row(
                                            rx.table.cell(r["user_name"]),
                                            rx.table.cell(
                                                r.get("emoji", "").to(str) + " " + r.get("tier_label", "").to(str)
                                                + " — " + r.get("prize_name", "").to(str)
                                            ),
                                            rx.table.cell(r["drawn_at"]),
                                        ),
                                    ),
                                ),
                                width="100%",
                            ),
                            max_height="250px", overflow_y="auto",
                        ),
                        rx.text("暂无中奖记录", color="gray"),
                    ),
                    spacing="3", width="100%",
                ),
                width="100%",
            ),
            max_width="750px",
        ),
        open=DrawState.lottery_detail_modal_open,
        on_open_change=DrawState.on_lottery_detail_dialog_change,
    )


def lottery_delete_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("确认删除"),
            rx.dialog.description(
                rx.text("确定要删除这条即开番赏记录吗？所有奖品和抽取记录也将被清除。此操作不可撤销。"),
            ),
            rx.hstack(
                rx.dialog.close(rx.button("取消", variant="outline", cursor="pointer")),
                rx.button("确认删除", color_scheme="red", cursor="pointer",
                          on_click=DrawState.execute_delete_lottery),
                spacing="3", justify="end", width="100%",
            ),
        ),
        open=DrawState.lottery_delete_confirm_open,
        on_open_change=DrawState.on_lottery_delete_dialog_change,
    )


# ===== 类型选择 =====
def top_bar() -> rx.Component:
    return rx.hstack(
        rx.text("抽奖类型", font_size="sm"),
        rx.select.root(
            rx.select.trigger(),
            rx.select.content(
                rx.select.item("传统抽奖", value="raffle"),
                rx.select.item("即开番赏", value="lottery"),
            ),
            value=DrawState.draw_type,
            on_change=DrawState.set_draw_type,
            width="160px",
        ),
        spacing="2", align="center", width="100%",
    )


# ===== 列表弹窗 =====
def list_dialog() -> rx.Component:
    """抽奖列表弹窗 — 按当前 draw_type 显示对应列表"""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    DrawState.draw_type == "raffle",
                    "传统抽奖列表",
                    "即开番赏列表",
                ),
            ),
            # 按类型切换显示对应列表
            rx.cond(
                DrawState.draw_type == "raffle",
                raffle_list(),
                lottery_list(),
            ),
            max_width="900px",
            width="100%",
            max_height="80vh",
            overflow="auto",
        ),
        open=DrawState.list_modal_open,
        on_open_change=DrawState.on_list_modal_change,
    )


# ===== 页面 =====
@rx.page(route="/draw", title="抽奖管理", on_load=DrawState.load_data)
def draw_page() -> rx.Component:
    return with_sidebar(
        rx.fragment(
            page_shell(
                "抽奖管理",
                "创建抽奖活动 / 编辑抽奖消息模板（点击右上角图标查看活动列表）",
                top_bar(),
                rx.divider(),
                # ---------- 按类型显示（仅创建表单，不再占主页面空间） ----------
                rx.cond(
                    DrawState.draw_type == "raffle",
                    raffle_create_card(),
                    lottery_create_card(),
                ),
                # ---------- 抽奖消息模板编辑（复用消息配置编辑器，只显示当前类型相关） ----------
                rx.divider(),
                rx.heading(
                    rx.cond(
                        DrawState.draw_type == "raffle",
                        "📝 传统抽奖消息模板",
                        "📝 即开番赏消息模板",
                    ),
                    size="4",
                ),
                rx.text(
                    "编辑该类型抽奖的公告 / 结果 / 提示文案，可用变量按需排列",
                    font_size="sm", color="gray",
                ),
                rx.hstack(
                    rx.box(message_list_panel(), width="320px", min_width="260px"),
                    rx.box(editor_panel(), width="100%"),
                    spacing="4", align="start", width="100%",
                ),
                # 标题栏右侧：抽奖列表图标
                header_action=rx.icon_button(
                    rx.icon("list", size=18),
                    variant="ghost",
                    size="2",
                    color_scheme="gray",
                    cursor="pointer",
                    on_click=DrawState.open_list_modal,
                ),
            ),
            # 抽奖详情/删除弹窗（保留，即使主页面不显示列表，弹窗仍可被内部触发）
            raffle_detail_dialog(),
            raffle_delete_dialog(),
            lottery_detail_dialog(),
            lottery_delete_dialog(),
            # 抽奖列表弹窗（图标按钮触发）
            list_dialog(),
        ),
    )
