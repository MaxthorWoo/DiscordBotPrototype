"""
即开型抽奖 Cog（固定奖池 + 打乱 + 按序抽取）
用户点击按钮 → 弹出确认 Modal → 抽取下一个槽位 → 临时消息告知结果 → 更新公告面板。

消息模板 key 说明：
  lottery_embed_desc       → 公告 Embed 描述文字
  lottery_draw_ephemeral   → 抽取结果（临时消息）
  lottery_draw_blocked     → 被拒绝（已达上限）
  lottery_force_close_announce → 强制清空公告
"""
import datetime

import discord
from discord.ext import commands, tasks

from shared_lib import crud


# ========== 确认 Modal ==========

class LotteryConfirmModal(discord.ui.Modal):
    """点击按钮后弹出确认窗口"""

    def __init__(
        self,
        cog: "LotteryCog",
        lottery_id: int,
        title: str = "确认抽奖",
        confirm_label: str = "输入「抽」确认抽取",
        confirm_placeholder: str = "输入「抽」确认",
    ):
        # 标题等文本由按钮回调读模板后传入；本方法内不做任何 DB 调用（防止超时）
        super().__init__(title=title)

        self.cog = cog
        self.lottery_id = lottery_id

        self.confirm_text = discord.ui.TextInput(
            label=confirm_label,
            placeholder=confirm_placeholder,
            style=discord.TextStyle.short,
            required=True,
            min_length=1,
            max_length=1,
        )
        self.add_item(self.confirm_text)

    async def on_submit(self, interaction: discord.Interaction):
        # 验证输入
        if self.confirm_text.value.strip() != "抽":
            wrong_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_modal_confirm_wrong",
            ) or "❌ 请输入「抽」来确认"
            await interaction.response.send_message(wrong_text, ephemeral=True)
            return

        # 先 defer 防止 3 秒超时
        await interaction.response.defer(ephemeral=True)

        user_id = str(interaction.user.id)
        user_name = str(interaction.user)

        # 执行抽取（defer 已在上面调用，不会超时）
        result = crud.draw_instant(self.lottery_id, user_id, user_name)

        if result.get("blocked"):
            reply_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_draw_blocked",
                my_count=result.get("my_count", 0),
                max_draws=result.get("max_draws", 3),
            )
            await interaction.followup.send(reply_text, ephemeral=True)
            return

        if not result["success"]:
            err_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_draw_error",
                message=result.get("message", "抽取失败"),
            ) or "❌ 出错了，请稍后重试"
            await interaction.followup.send(err_text, ephemeral=True)
            if result.get("closed"):
                await self.cog._update_lottery_message(self.lottery_id)
            return

        # 成功 → 临时消息告知结果
        reply_text = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_draw_ephemeral",
            result_emoji=result["emoji"],
            result_text=result["message"],
            my_count=result["my_count"],
            max_draws=result["max_draws"],
            slots_left=result["slots_left"],
        )
        await interaction.followup.send(reply_text, ephemeral=True)

        # 更新公告面板
        await self.cog._update_lottery_message(self.lottery_id)


# ========== 按钮组件 ==========

class LotteryDrawButton(discord.ui.Button):
    """抽一发按钮 → 打开 Modal"""

    def __init__(self, cog: "LotteryCog", lottery_id: int):
        # 发布时创建（非交互回调），同步读 DB 安全（毫秒级）
        label = crud.get_message_text(crud.DEFAULT_BOT_ID, "lottery_draw_button") or "🎯 抽一发"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.success,
            custom_id=f"lottery:draw:{lottery_id}",
        )
        self.cog = cog
        self.lottery_id = lottery_id

    async def callback(self, interaction: discord.Interaction):
        try:
            # 异步上下文读取模板（单次 SQLite 读取 <10ms，不会超时）
            modal_title = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_modal_title",
            ) or "确认抽奖"
            confirm_label = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_modal_confirm_label",
            ) or "输入「抽」确认抽取"
            confirm_placeholder = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_modal_confirm_placeholder",
            ) or "输入「抽」确认"

            modal = LotteryConfirmModal(
                self.cog, self.lottery_id,
                title=modal_title,
                confirm_label=confirm_label,
                confirm_placeholder=confirm_placeholder,
            )
            await interaction.response.send_modal(modal)
        except Exception as e:
            import traceback
            print(f"[Lottery] 按钮回调异常 (lottery_id={self.lottery_id}): {e}")
            traceback.print_exc()
            try:
                fail_text = crud.get_message_text(
                    crud.DEFAULT_BOT_ID, "lottery_draw_fail",
                ) or "❌ 出错了，请稍后重试"
                await interaction.response.send_message(fail_text, ephemeral=True)
            except Exception:
                pass


class LotteryDrawView(discord.ui.View):
    """持久化 View"""

    def __init__(self, cog: "LotteryCog", lottery_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.lottery_id = lottery_id
        self.add_item(LotteryDrawButton(cog, lottery_id))


# ========== Cog 主体 ==========

class LotteryCog(commands.Cog):
    """即开型抽奖：固定奖池 + 打乱 + 按序抽取 + 24h 强制清空"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._publish_loop.start()
        self._force_close_loop.start()

    async def cog_unload(self):
        self._publish_loop.cancel()
        self._force_close_loop.cancel()

    # ---------- Bot 启动恢复 ----------

    async def _restore_views(self):
        await self.bot.wait_until_ready()
        lotteries = crud.get_all_active_lottery_messages()
        for l in lotteries:
            if l["message_id"]:
                try:
                    self.bot.add_view(
                        LotteryDrawView(self, l["id"]),
                        message_id=int(l["message_id"]),
                    )
                except Exception as e:
                    print(f"[Lottery] 恢复 View 失败 (lottery_id={l['id']}): {e}")
        print(f"[Lottery] 已恢复 {len(lotteries)} 个活跃抽奖 View")

    @commands.Cog.listener()
    async def on_ready(self):
        await self._restore_views()

    # ---------- 发布轮询 ----------

    @tasks.loop(seconds=10)
    async def _publish_loop(self):
        try:
            if not self.bot.is_ready():
                return
            unpub = crud.get_unpublished_lotteries()
            for l in unpub:
                if l.get("channel_id"):
                    await self.publish_lottery(l["id"], l["channel_id"])
                    print(f"[Lottery] 已发布抽奖 #{l['id']}: {l['title']}")
        except Exception as e:
            print(f"[Lottery] _publish_loop 异常: {e}")

    @_publish_loop.before_loop
    async def _before_publish_loop(self):
        await self.bot.wait_until_ready()

    # ---------- 强制清空轮询 ----------

    @tasks.loop(seconds=30)
    async def _force_close_loop(self):
        try:
            if not self.bot.is_ready():
                return
            expired = crud.get_expired_lotteries(hours=24.0)
            for l in expired:
                result = crud.force_close_lottery(l["id"])
                if not result:
                    continue
                print(f"[Lottery] 强制清空 #{l['id']}: {l['title']}（剩余 {l['slots_left']} 抽）")

                # 发布强制清空公告
                await self._send_force_close_announce(result)

                # 更新公告面板
                await self._update_lottery_message(l["id"])
        except Exception as e:
            print(f"[Lottery] _force_close_loop 异常: {e}")

    @_force_close_loop.before_loop
    async def _before_force_close_loop(self):
        await self.bot.wait_until_ready()

    async def _send_force_close_announce(self, result: dict):
        """强制清空后在频道发公告"""
        try:
            if not result.get("channel_id"):
                return
            channel = self.bot.get_channel(int(result["channel_id"]))
            if not channel:
                return

            left_slots = result.get("left_slots", [])
            if left_slots:
                prize_line_tpl = crud.get_message_text(
                    crud.DEFAULT_BOT_ID, "lottery_force_close_prize_line",
                ) or "{emoji} {tier} — {name}"
                prize_summary = "\n".join(
                    prize_line_tpl.format(
                        emoji=s["emoji"],
                        tier=s["tier_label"],
                        name=s["prize_name"],
                    )
                    for s in left_slots
                )
            else:
                prize_summary = crud.get_message_text(
                    crud.DEFAULT_BOT_ID, "lottery_force_close_no_prize",
                ) or "无剩余奖品"

            announce_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_force_close_announce",
                title=result["title"],
                duration=24,
                left=result["left_count"],
                mentions=prize_summary,
            )
            await channel.send(announce_text)
        except Exception as e:
            print(f"[Lottery] 发送强制清空公告失败: {e}")

    # ---------- 公告发布 ----------

    async def publish_lottery(self, lottery_id: int, channel_id: str) -> bool:
        """Dashboard 创建抽奖后发布公告"""
        lottery = crud.get_lottery_status(lottery_id)
        if not lottery:
            return False

        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                print(f"[Lottery] 找不到频道 {channel_id}")
                return False

            embed = self._build_lottery_embed(lottery)
            view = LotteryDrawView(self, lottery_id)
            msg = await channel.send(embed=embed, view=view)
            self.bot.add_view(view, message_id=msg.id)
            crud.set_lottery_message_id(lottery_id, channel_id, str(msg.id))
            return True
        except Exception as e:
            print(f"[Lottery] publish_lottery 失败: {e}")
            return False

    # ---------- 公告面板更新 ----------

    async def _update_lottery_message(self, lottery_id: int):
        """每次抽取后更新公告 Embed"""
        lottery = crud.get_lottery_status(lottery_id)
        if not lottery:
            return

        try:
            if not lottery.get("message_id") or not lottery.get("channel_id"):
                return

            channel = self.bot.get_channel(int(lottery["channel_id"]))
            if not channel:
                return

            msg = await channel.fetch_message(int(lottery["message_id"]))
            embed = self._build_lottery_embed(lottery)

            if not lottery["is_active"]:
                # 已结束：移除按钮、发送结果公示
                await msg.edit(embed=embed, view=None)
                try:
                    self.bot.remove_view(LotteryDrawView(self, lottery_id))
                except Exception:
                    pass
                # 发送抽奖结果公示
                await self._send_result_announcement(lottery)
            else:
                await msg.edit(embed=embed)
        except Exception as e:
            print(f"[Lottery] 更新面板失败 (lottery_id={lottery_id}): {e}")

    async def _send_result_announcement(self, lottery: dict):
        """抽奖结束后，在频道发送中奖名单 Embed"""
        try:
            if not lottery.get("channel_id"):
                return
            channel = self.bot.get_channel(int(lottery["channel_id"]))
            if not channel:
                return

            # 获取所有中奖记录
            records = crud.get_lottery_draw_records(lottery["id"], limit=200)

            result_title = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_result_title",
                title=lottery["title"],
                lottery_id=lottery["id"],
            ) or f"🏆 {lottery['title']} — 抽奖结果公示"
            result_desc = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_result_desc",
                drawn=lottery["slots_drawn"],
                total=lottery["total_slots"],
                hit=lottery["hit_count"],
                title=lottery["title"],
            ) or f"共 {lottery['slots_drawn']}/{lottery['total_slots']} 抽\n中奖 {lottery['hit_count']} 人次"
            winner_field_name = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_result_winner_name",
            ) or "中奖名单"
            no_winner_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_result_no_winner",
            ) or "无中奖者"
            line_tpl = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_result_line",
            ) or "{emoji} {tier}-{name}"
            footer_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_result_footer",
                id=lottery["id"],
            ) or f"抽奖 ID: {lottery['id']} • 时间均为北京时间"

            embed = discord.Embed(
                title=result_title,
                description=result_desc,
                color=0xFEE75C,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )

            # 按用户分组统计
            if records:
                user_wins = {}
                for r in records:
                    uid = r["user_name"]
                    if uid not in user_wins:
                        user_wins[uid] = []
                    user_wins[uid].append(r)

                lines = []
                for uname, items in user_wins.items():
                    prize_text = " / ".join(
                        line_tpl.format(
                            emoji=it["emoji"],
                            tier=it["tier_label"],
                            name=it["prize_name"],
                        )
                        for it in items
                    )
                    lines.append(f"**{uname}** → {prize_text}")

                # Discord Embed field 限制 1024 字符
                chunk = ""
                for line in lines:
                    if len(chunk) + len(line) > 1000:
                        embed.add_field(name=winner_field_name, value=chunk, inline=False)
                        chunk = ""
                    chunk += line + "\n"
                if chunk:
                    embed.add_field(name=winner_field_name, value=chunk, inline=False)
            else:
                embed.add_field(name=winner_field_name, value=no_winner_text, inline=False)

            embed.set_footer(text=footer_text)
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[Lottery] 发送结果公示失败 (lottery_id={lottery['id']}): {e}")

    # ---------- Embed 构建 ----------

    def _build_lottery_embed(self, lottery: dict) -> discord.Embed:
        """构建公告 Embed：奖池 + 进度 + 最近中奖（全部文本走消息模板）"""
        prizes = lottery.get("prizes", [])
        slots_total = lottery.get("total_slots", 100)
        slots_drawn = lottery.get("slots_drawn", 0)
        slots_left = lottery.get("slots_left", slots_total - slots_drawn)

        if lottery["is_active"]:
            color = 0x57F287
            status_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_status_active",
            ) or "🟢 进行中"
        else:
            color = 0x8D8D8D
            status_text = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_status_ended",
            ) or "⚫ 已结束"

        # 描述（消息模板）
        description = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_desc",
            title=lottery.get("title", ""),
            description=lottery.get("description") or "",
            total_slots=slots_total,
            max_draws_per_user=lottery.get("max_draws_per_user", 3),
        )

        embed_title = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_title",
            title=lottery["title"],
            lottery_id=lottery["id"],
        ) or f"🎰 {lottery['title']}"
        footer_text = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_footer",
            id=lottery["id"],
        ) or f"抽奖 ID: {lottery['id']} • 时间均为北京时间"

        embed = discord.Embed(
            title=embed_title,
            description=description,
            color=color,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        # 进度条
        bar_len = 20
        filled = int(bar_len * slots_drawn / max(slots_total, 1))
        bar = "▓" * filled + "░" * (bar_len - filled)
        progress_name = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_progress_name",
            drawn=slots_drawn, total=slots_total,
        ) or f"📊 进度 {slots_drawn}/{slots_total}"
        progress_value = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_progress_value",
            bar=bar, left=slots_left, total=slots_total,
        ) or f"`{bar}` 剩余 {slots_left} 抽"
        embed.add_field(
            name=progress_name,
            value=progress_value,
            inline=False,
        )

        # 奖品清单（含已抽完状态）
        if prizes:
            prize_normal_tpl = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_prize_normal",
            ) or "{emoji} **{tier}** {name} `[{remaining}/{total}]`"
            prize_soldout_tpl = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_prize_soldout",
            ) or "{emoji} **{tier}** ~~{name}~~ 已售罄 `[{remaining}/{total}]`"
            prizes_name = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_prizes_name",
            ) or "🏆 奖池"
            prize_lines = []
            for p in prizes:
                sold_out = p["remaining"] == 0
                tpl = prize_soldout_tpl if sold_out else prize_normal_tpl
                prize_lines.append(
                    tpl.format(
                        emoji=p["emoji"],
                        tier=p["tier_label"],
                        name=p["prize_name"],
                        remaining=p["remaining"],
                        total=p["total_count"],
                    )
                )
            embed.add_field(
                name=prizes_name,
                value="\n".join(prize_lines),
                inline=False,
            )

        # 最近中奖
        recent = lottery.get("recent_draws", [])
        if recent:
            recent_hit_tpl = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_recent_hit",
            ) or "{emoji} **{user}** → {tier} {name}"
            recent_miss_tpl = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_recent_miss",
            ) or "😔 **{user}** → 谢谢参与"
            recent_name = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_recent_name",
            ) or "📜 最近抽取"
            recent_lines = []
            for r in recent[:8]:
                if r["is_hit"]:
                    recent_lines.append(
                        recent_hit_tpl.format(
                            emoji=r["emoji"],
                            user=r["user_name"],
                            tier=r["tier_label"],
                            name=r["prize_name"],
                        )
                    )
                else:
                    recent_lines.append(
                        recent_miss_tpl.format(user=r["user_name"])
                    )
            embed.add_field(
                name=recent_name,
                value="\n".join(recent_lines),
                inline=False,
            )

        status_name = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_status_name",
        ) or "状态"
        endtime_name = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_endtime_name",
        ) or "结束时间"
        endtime_value = lottery.get("end_time") or ""
        if not endtime_value:
            endtime_value = crud.get_message_text(
                crud.DEFAULT_BOT_ID, "lottery_embed_endtime_na",
            ) or "未设置"
        limit_name = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_limit_name",
        ) or "每人限抽"
        limit_value = crud.get_message_text(
            crud.DEFAULT_BOT_ID, "lottery_embed_limit_value",
            n=lottery.get("max_draws_per_user", 3),
        ) or f"{lottery.get('max_draws_per_user', 3)} 次"

        embed.add_field(name=status_name, value=status_text, inline=True)
        embed.add_field(name=endtime_name, value=endtime_value, inline=True)
        embed.add_field(name=limit_name, value=limit_value, inline=True)

        embed.set_footer(text=footer_text)
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(LotteryCog(bot))
