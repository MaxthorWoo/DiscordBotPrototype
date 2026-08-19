"""
传统抽奖 Cog — 定时开奖 / 手动开奖。
管理员在 Dashboard 创建抽奖，Bot 发送公告 Embed + 参与按钮，
用户点击按钮参与；到时间自动开奖并 @ 中奖者。

消息模板 key 说明：
  raffle_embed_desc   → 公告 Embed 描述文字
  raffle_result_desc  → 开奖结果 Embed 描述文字
  raffle_join_success → 报名成功提示
  raffle_already_joined → 重复报名提示
  raffle_announce_draw → 中奖公告 @ 消息
"""
import datetime

import discord
from discord.ext import commands, tasks

from shared_lib import crud
from shared_lib.utils.time_utils import now_beijing, format_datetime_beijing


# ========== 按钮组件（持久化） ==========

class RaffleJoinButton(discord.ui.Button):
    """参与抽奖按钮，每个抽奖实例使用唯一的 custom_id。"""

    def __init__(self, cog: "RaffleCog", raffle_id: int):
        label = crud.get_message_text(crud.DEFAULT_BOT_ID, "raffle_join_button") or "🎫 参与抽奖"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id=f"raffle:join:{raffle_id}",
        )
        self.cog = cog
        self.raffle_id = raffle_id

    async def callback(self, interaction: discord.Interaction):
        result = crud.join_raffle(
            self.raffle_id,
            str(interaction.user.id),
            str(interaction.user),
        )
        if result["already_joined"]:
            msg = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "raffle_already_joined",
            )
        elif result["success"]:
            count = result.get("count", "?")
            msg = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "raffle_join_success",
                count=count,
            )
            # 更新原公告消息 Embed（刷新参与人数）
            await self.cog._update_raffle_message(self.raffle_id)
        else:
            msg = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "raffle_draw_error",
                message=result.get("message", "操作失败"),
            ) or f"❌ {result.get('message', '操作失败')}"

        await interaction.response.send_message(msg, ephemeral=True)


class RaffleManualDrawButton(discord.ui.Button):
    """手动开奖按钮（仅管理员可点击）。"""

    def __init__(self, cog: "RaffleCog", raffle_id: int):
        label = crud.get_message_text(crud.DEFAULT_BOT_ID, "raffle_manual_button") or "✋ 手动开奖"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.danger,
            custom_id=f"raffle:manual:{raffle_id}",
        )
        self.cog = cog
        self.raffle_id = raffle_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            denied_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "raffle_manual_permission_denied",
            ) or "❌ 只有管理员可以手动开奖。"
            await interaction.response.send_message(denied_text, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await self.cog._execute_draw(self.raffle_id, manual_user=interaction.user)
        done_text = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_manual_done",
        ) or "✅ 已执行开奖。"
        await interaction.followup.send(done_text, ephemeral=True)


class RafflePublicView(discord.ui.View):
    """公告消息上的公开 View。

    - 定时抽奖 (is_manual=False): 仅显示「参与抽奖」按钮
    - 手动抽奖 (is_manual=True):  仅显示「手动开奖」按钮
    """

    def __init__(self, cog: "RaffleCog", raffle_id: int, is_manual: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.raffle_id = raffle_id
        if is_manual:
            self.add_item(RaffleManualDrawButton(cog, raffle_id))
        else:
            self.add_item(RaffleJoinButton(cog, raffle_id))


# ========== Cog 主体 ==========

class RaffleCog(commands.Cog):
    """传统抽奖：定时开奖 + 手动开奖"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._draw_loop.start()
        self._publish_loop.start()

    async def cog_unload(self):
        self._draw_loop.cancel()
        self._publish_loop.cancel()

    # ---------- Bot 启动时恢复所有活跃抽奖的 View ----------

    async def _restore_views(self):
        """等待 Bot Ready 后，为所有活跃抽奖注册 View"""
        await self.bot.wait_until_ready()
        raffles = crud.get_all_active_raffle_messages()
        for r in raffles:
            if r["message_id"]:
                try:
                    is_manual = not r.get("draw_time")  # 没有开奖时间 = 手动开奖
                    self.bot.add_view(
                        RafflePublicView(self, r["id"], is_manual=is_manual),
                        message_id=int(r["message_id"]),
                    )
                except Exception as e:
                    print(f"[Raffle] 恢复 View 失败 (raffle_id={r['id']}): {e}")
        print(f"[Raffle] 已恢复 {len(raffles)} 个活跃抽奖 View")

    @commands.Cog.listener()
    async def on_ready(self):
        await self._restore_views()

    # ---------- 定时轮询开奖 ----------

    @tasks.loop(seconds=15)
    async def _draw_loop(self):
        try:
            if not self.bot.is_ready():
                return
            pending = crud.get_pending_draw_raffles()
            for r in pending:
                bot_id = r.get("bot_id", crud.DEFAULT_BOT_ID)
                if bot_id != crud.DEFAULT_BOT_ID:
                    continue  # 只处理当前 Bot（多 Bot 支持占位）
                await self._execute_draw(r["id"])
        except Exception as e:
            print(f"[Raffle] _draw_loop 异常: {e}")

    @_draw_loop.before_loop
    async def _before_draw_loop(self):
        await self.bot.wait_until_ready()

    # ---------- 发布轮询：检测 Dashboard 新创建的抽奖 ----------

    @tasks.loop(seconds=10)
    async def _publish_loop(self):
        try:
            if not self.bot.is_ready():
                return
            unpub = crud.get_unpublished_raffles()
            for r in unpub:
                if r.get("channel_id"):
                    await self.publish_raffle(r["id"], r["channel_id"])
                    print(f"[Raffle] 已发布抽奖 #{r['id']}: {r['title']}")
        except Exception as e:
            print(f"[Raffle] _publish_loop 异常: {e}")

    @_publish_loop.before_loop
    async def _before_publish_loop(self):
        await self.bot.wait_until_ready()

    # ---------- 公共：发布抽奖公告（Dashboard 调用） ----------

    async def publish_raffle(self, raffle_id: int, channel_id: str) -> bool:
        """
        Dashboard 创建抽奖后调用此方法，在指定频道发布公告。
        """
        raffle_data = crud.get_raffle(raffle_id)
        if not raffle_data:
            return False

        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                print(f"[Raffle] 找不到频道 {channel_id}")
                return False

            # 区分手动 / 定时抽奖
            is_manual = not raffle_data.get("draw_time")

            embed = self._build_raffle_embed(raffle_data)
            view = RafflePublicView(self, raffle_id, is_manual=is_manual)

            msg = await channel.send(embed=embed, view=view)

            # 持久化绑定 View 到该消息
            self.bot.add_view(view, message_id=msg.id)

            crud.set_raffle_message_id(raffle_id, channel_id, str(msg.id))
            return True
        except Exception as e:
            print(f"[Raffle] publish_raffle 失败: {e}")
            return False

    # ---------- 原消息更新（报名后刷新参与人数） ----------

    async def _update_raffle_message(self, raffle_id: int):
        """用户报名后，更新原公告 Embed 显示最新参与人数"""
        raffle_data = crud.get_raffle(raffle_id)
        if not raffle_data or not raffle_data.get("is_active"):
            return

        try:
            if not raffle_data.get("message_id") or not raffle_data.get("channel_id"):
                return

            channel = self.bot.get_channel(int(raffle_data["channel_id"]))
            if not channel:
                return

            msg = await channel.fetch_message(int(raffle_data["message_id"]))
            embed = self._build_raffle_embed(raffle_data)
            await msg.edit(embed=embed)
        except Exception as e:
            print(f"[Raffle] 更新公告消息失败 (raffle_id={raffle_id}): {e}")

    # ---------- 内部：构建 Embed ----------

    def _build_raffle_embed(self, raffle: dict) -> discord.Embed:
        """开奖前的公告 Embed（使用消息模板）"""
        is_drawn = raffle.get("is_drawn", False)
        is_active = raffle.get("is_active", False)
        is_manual = not raffle.get("draw_time")

        if is_drawn:
            status_icon = "🔴"
            status_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "raffle_status_drawn",
            ) or "已开奖"
            color = 0xFEE75C
        elif is_active:
            status_icon = "🟢"
            status_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "raffle_status_active",
            ) or "进行中"
            color = 0x57F287
        else:
            status_icon = "⚫"
            status_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "raffle_status_ended",
            ) or "已结束"
            color = 0x99AAB5

        draw_type = "手动开奖" if is_manual else "定时开奖"
        draw_time_str = raffle.get("draw_time") or "手动开奖（管理员点击按钮）"
        participant_count = raffle.get("participant_count", 0)

        # 默认描述（无自定义描述时兜底）
        default_desc = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_embed_default_desc",
            draw_type=draw_type,
            title=raffle.get("title", ""),
        ) or f"🎟️ {draw_type} — 点击下方按钮参与！"

        # 从数据库读取可自定义的消息模板
        description = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_embed_desc",
            title=raffle.get("title", ""),
            description=(raffle.get("description") or default_desc),
            winner_count=raffle["winner_count"],
            draw_time=draw_time_str,
            participant_count=participant_count,
            status_icon=status_icon,
            status_text=status_text,
            raffle_id=raffle["id"],
        )

        embed_title = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_embed_title",
            title=raffle["title"],
            raffle_id=raffle["id"],
        ) or f"🎟️ {raffle['title']}"
        footer_text = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_embed_footer",
            id=raffle["id"],
        ) or f"抽奖 ID: {raffle['id']} • 时间均为北京时间"

        embed = discord.Embed(
            title=embed_title,
            description=description,
            color=color,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_footer(text=footer_text)
        return embed

    def _build_drawn_embed(self, raffle: dict, winners: list[dict]) -> discord.Embed:
        """开奖后的结果 Embed（使用消息模板）"""
        participant_count = raffle.get("participant_count", 0)
        draw_time = format_datetime_beijing(datetime.datetime.now(datetime.timezone.utc))

        description = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_result_desc",
            title=raffle.get("title", ""),
            description=raffle.get("description") or "",
            participant_count=participant_count,
            winner_count=len(winners),
            draw_time=draw_time,
            raffle_id=raffle["id"],
        )

        winner_line_tpl = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_result_winner_line",
        ) or "🏆 {user}"
        no_winner_text = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_result_no_winner",
        ) or "无人中奖"
        winner_names = (
            "\n".join(winner_line_tpl.format(user=w["user_name"]) for w in winners)
            if winners else no_winner_text
        )

        result_title = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_result_title",
            title=raffle["title"],
            raffle_id=raffle["id"],
        ) or f"🎟️ {raffle['title']} [已开奖]"
        winner_field_name = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_result_winner_name",
        ) or "中奖者"
        footer_text = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "raffle_result_footer",
            id=raffle["id"],
        ) or f"抽奖 ID: {raffle['id']} • 时间均为北京时间"

        embed = discord.Embed(
            title=result_title,
            description=description,
            color=0xFEE75C,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name=winner_field_name, value=winner_names, inline=False)
        embed.set_footer(text=footer_text)
        return embed

    # ---------- 开奖执行 ----------

    async def _execute_draw(self, raffle_id: int, manual_user: discord.User = None):
        """执行开奖：抽取中奖者，更新公告，发 @ 通知"""
        result = crud.draw_raffle_winners(raffle_id)
        raffle_data = crud.get_raffle(raffle_id)
        if not raffle_data:
            return

        # 编辑原公告消息（移除按钮，显示结果）
        try:
            if raffle_data.get("message_id"):
                channel = self.bot.get_channel(int(raffle_data["channel_id"]))
                if channel:
                    msg = await channel.fetch_message(int(raffle_data["message_id"]))
                    embed = self._build_drawn_embed(
                        raffle_data, result.get("winners", [])
                    )
                    await msg.edit(embed=embed, view=None)
        except Exception as e:
            print(f"[Raffle] 编辑公告消息失败: {e}")

        # 发送中奖公告 @ 中奖者（使用消息模板）
        try:
            announce_ch = raffle_data.get("announce_channel_id") or raffle_data.get("channel_id")
            channel = self.bot.get_channel(int(announce_ch))
            if channel and result["success"] and result["winners"]:
                mentions = " ".join(f"<@{w['user_id']}>" for w in result["winners"])
                operator = "管理员手动" if manual_user else "定时自动"
                announce_text = crud.get_message_text(
                    crud.DEFAULT_BOT_ID, "raffle_announce_draw",
                    title=raffle_data["title"],
                    operator=operator,
                    mentions=mentions,
                    winner_count=len(result["winners"]),
                    participant_count=raffle_data.get("participant_count", 0),
                )
                await channel.send(announce_text)
            elif channel and not result["success"]:
                fail_text = crud.get_message_text(
                    crud.DEFAULT_BOT_ID, "raffle_draw_failed",
                    title=raffle_data["title"],
                    message=result.get("message", "未知错误"),
                ) or f"🎟️ **{raffle_data['title']}** 开奖失败：{result.get('message', '未知错误')}"
                await channel.send(fail_text)
        except Exception as e:
            print(f"[Raffle] 发送中奖公告失败: {e}")

        # 移除持久化 View
        try:
            if raffle_data.get("message_id"):
                self.bot.remove_view(RafflePublicView(self, raffle_id))
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(RaffleCog(bot))
