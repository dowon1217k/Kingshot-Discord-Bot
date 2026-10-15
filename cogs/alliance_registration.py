"""Alliance registration flow. /register links an in-game ID to a Discord account (multi-FID, cross-server). /unregister detaches one of your own."""
from .i18n import tr
import discord
from discord.ext import commands
import sqlite3
import asyncio
import logging
from contextlib import closing
from datetime import datetime, timezone
from .pimp_my_bot import theme, menu_timeout
from .alliance import check_alliance_kingdom
from .gift_state_resolver import get_alliance_kid
from .bot_level_mapping import parse_furnace_level, parse_state
from .alliance_member_edit import api_state_refusal, apply_member_edit
from .alliance_api_sync import look_up_new_member, store_new_member

logger = logging.getLogger('alliance')


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class AllianceRegistration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.conn_alliance = sqlite3.connect("db/alliance.sqlite", timeout=30.0, check_same_thread=False)
        self.c_alliance = self.conn_alliance.cursor()

        self.conn_users = sqlite3.connect("db/users.sqlite", timeout=30.0, check_same_thread=False)
        self.c_users = self.conn_users.cursor()

    async def cog_unload(self):
        self.conn_alliance.close()
        self.conn_users.close()

    # ── Registration state helpers ─────────────────────────────────────────

    def _get_user_row(self, fid: int):
        """Return (fid, discord_id, discord_server_id, alliance, nickname) or None."""
        self.c_users.execute(
            "SELECT fid, discord_id, discord_server_id, alliance, nickname "
            "FROM users WHERE fid = ?",
            (fid,),
        )
        return self.c_users.fetchone()

    def _linked_fids_for(self, discord_id: int) -> list:
        """All FIDs owned by this Discord user across all servers.
        Returns list of (fid, nickname, alliance, discord_server_id)."""
        self.c_users.execute(
            "SELECT fid, nickname, alliance, discord_server_id "
            "FROM users WHERE discord_id = ? "
            "ORDER BY nickname COLLATE NOCASE",
            (discord_id,),
        )
        return self.c_users.fetchall()

    def set_registration_enabled(self, enabled: bool) -> None:
        """Persist the global self-registration toggle to settings.sqlite."""
        try:
            with sqlite3.connect("db/settings.sqlite") as conn:
                cursor = conn.cursor()
                cursor.execute("CREATE TABLE IF NOT EXISTS register_settings (enabled BOOLEAN)")
                cursor.execute("SELECT COUNT(*) FROM register_settings")
                exists = cursor.fetchone()[0] > 0
                if exists:
                    cursor.execute(
                        "UPDATE register_settings SET enabled = ? WHERE rowid = 1",
                        (enabled,),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO register_settings VALUES (?)", (enabled,)
                    )
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating register settings: {e}")
            print(f"Error updating register settings: {e}")

    def is_registration_enabled(self) -> bool:
        """Check if registration is enabled in the settings database."""
        try:
            with closing(sqlite3.connect("db/settings.sqlite")) as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='register_settings'")
                table_exists = cursor.fetchone()

                if not table_exists:
                    return False

                cursor.execute("SELECT enabled FROM register_settings WHERE rowid = 1")
                result = cursor.fetchone()

                return bool(result[0]) if result else False

        except Exception as e:
            logger.error(f"Error checking registration status: {e}")
            print(f"Error checking registration status: {e}")
            return False

    async def alliance_autocomplete(self, interaction: discord.Interaction, current: str):
        def _read():
            with sqlite3.connect("db/alliance.sqlite", timeout=30.0) as conn:
                return conn.execute("SELECT alliance_id, name FROM alliance_list").fetchall()
        alliances = await asyncio.to_thread(_read)

        return [
            discord.app_commands.Choice(name=name, value=alliance_id)
            for alliance_id, name in alliances if current.lower() in name.lower()
        ][:25]

    def _alliance_exists(self, alliance_id: int) -> bool:
        with sqlite3.connect("db/alliance.sqlite", timeout=30.0) as conn:
            return conn.execute(
                "SELECT 1 FROM alliance_list WHERE alliance_id = ?", (alliance_id,)
            ).fetchone() is not None

    # ── DB writes ──────────────────────────────────────────────────────────

    def _write_users(self, sql: str, params: tuple):
        # Roll back on failure: this connection lives as long as the cog and would hold the lock.
        try:
            self.c_users.execute(sql, params)
            self.conn_users.commit()
        except sqlite3.Error:
            self.conn_users.rollback()
            raise

    def _insert_new_user(self, fid: int, user_data: dict, alliance: int,
                         discord_id: int, server_id: int):
        self._write_users(
            "INSERT INTO users (fid, nickname, furnace_lv, kid, stove_lv_content, "
            "alliance, discord_id, discord_server_id, discord_id_updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fid, user_data["nickname"], user_data["stove_lv"], user_data["kid"],
             user_data.get("stove_lv_content"), alliance, discord_id, server_id, _now_iso()),
        )

    def _attach_discord_to_existing(self, fid: int, discord_id: int, server_id: int):
        self._write_users(
            "UPDATE users SET discord_id = ?, discord_server_id = ?, "
            "discord_id_updated_at = ? WHERE fid = ?",
            (discord_id, server_id, _now_iso(), fid),
        )

    def _move_registration_to_server(self, fid: int, new_server_id: int):
        self._write_users(
            "UPDATE users SET discord_server_id = ?, discord_id_updated_at = ? "
            "WHERE fid = ?",
            (new_server_id, _now_iso(), fid),
        )

    def _detach_discord(self, fid: int):
        self._write_users(
            "UPDATE users SET discord_id = NULL, discord_server_id = NULL, "
            "discord_id_updated_at = ? WHERE fid = ?",
            (_now_iso(), fid),
        )

    # ── /register ──────────────────────────────────────────────────────────

    @discord.app_commands.command(
        name="register",
        description=tr('registration.description'),
    )
    @discord.app_commands.describe(
        fid=tr('registration.uid_option'),
        alliance=tr('registration.alliance_option'),
        kingdom=tr('registration.kingdom_option'),
        name=tr('registration.name_option'),
        level=tr('registration.level_option'),
    )
    @discord.app_commands.rename(fid="id")
    @discord.app_commands.autocomplete(alliance=alliance_autocomplete)
    async def register(self, interaction: discord.Interaction, fid: int, alliance: int,
                       kingdom: "int | None" = None, name: "str | None" = None,
                       level: "str | None" = None):
        if not self.is_registration_enabled():
            await interaction.response.send_message(
                f"{theme.deniedIcon} {tr('registration.disabled')}",
                ephemeral=True
            )
            return

        furnace_lv = None
        if level is not None:
            furnace_lv = parse_furnace_level(level)
            if furnace_lv is None:
                await interaction.response.send_message(
                    f"{theme.deniedIcon} {tr('registration.invalid_level')}", ephemeral=True)
                return

        caller_id = interaction.user.id
        current_server_id = interaction.guild_id if interaction.guild else None

        # Autocomplete is only a suggestion UI - users can submit any integer.
        if not self._alliance_exists(alliance):
            await interaction.response.send_message(
                f"{theme.deniedIcon} {tr('registration.missing_alliance')}",
                ephemeral=True,
            )
            return

        existing = self._get_user_row(fid)

        if existing and existing[1] is not None and existing[1] != caller_id:
            await interaction.response.send_message(
                f"{theme.deniedIcon} {tr('registration.duplicate')}",
                ephemeral=True,
            )
            return

        if existing and existing[1] == caller_id:
            existing_server_id = existing[2]
            if existing_server_id == current_server_id:
                changed = []
                if name or furnace_lv:
                    changed = await asyncio.to_thread(apply_member_edit, fid,
                                                      nickname=name, furnace_lv=furnace_lv)
                note = tr('registration.updated_fields', v0=', '.join(changed)) if changed else tr("registration.no_changes")
                await interaction.response.send_message(
                    tr('registration.already_registered', v0=theme.verifiedIcon, v1=fid, v2=note),
                    ephemeral=True,
                )
                return
            view = _MoveServerView(
                cog=self, fid=fid, caller_id=caller_id,
                old_server_id=existing_server_id, new_server_id=current_server_id,
            )
            old_name = self._server_name_or_id(existing_server_id, interaction)
            new_name = self._server_name_or_id(current_server_id, interaction)
            await interaction.response.send_message(
                tr('registration.move_prompt', v0=theme.infoIcon, v1=fid, v2=old_name, v3=new_name),
                view=view, ephemeral=True,
            )
            return

        if existing:
            self._attach_discord_to_existing(fid, caller_id, current_server_id)
            if name or furnace_lv:
                await asyncio.to_thread(apply_member_edit, fid,
                                        nickname=name, furnace_lv=furnace_lv)
            await self._send_register_success(interaction, fid, caller_id, action="linked")
            return

        # The API lookup and the kingdom probe are slow, so defer first.
        await interaction.response.defer(ephemeral=True)
        kid = typed_kid = None
        if kingdom is not None:
            kid = typed_kid = parse_state(kingdom)
            if kid is None:
                await interaction.followup.send(
                    f"{theme.deniedIcon} {tr('registration.invalid_kingdom')}", ephemeral=True)
                return
        member = await look_up_new_member(self.bot, fid, alliance, name, furnace_lv, probe=typed_kid is None)
        if member.kid is not None:
            kid = member.kid
        elif kid is None and await asyncio.to_thread(get_alliance_kid, alliance) is None:
            # No home kingdom to inherit or confirm against, so we can't work it out.
            await interaction.followup.send(
                tr('registration.kingdom_required', v0=theme.infoIcon), ephemeral=True)
            return

        kingdom_error = api_state_refusal(check_alliance_kingdom(alliance, kid), member.kid, typed_kid)
        if kingdom_error:
            await interaction.followup.send(f"{theme.deniedIcon} {kingdom_error}", ephemeral=True)
            return

        user_data = {"nickname": member.nickname, "stove_lv": member.furnace_lv, "kid": kid}
        self._insert_new_user(fid, user_data, alliance, caller_id, current_server_id)
        await store_new_member(member, fid)
        await self._send_register_success(interaction, fid, caller_id, action="registered")

    async def _send_register_success(self, interaction: discord.Interaction,
                                     fid: int, caller_id: int, action: str):
        all_linked = self._linked_fids_for(caller_id)
        if len(all_linked) > 1:
            lines = "\n".join(
                f"  {theme.fidIcon} `{f}` — {n or tr('registration.unnamed')}"
                for f, n, _, _ in all_linked
            )
            extra = tr('registration.linked_characters', v0=len(all_linked), v1=lines)
        else:
            extra = ""
        verb = tr('registration.linked') if action == "linked" else tr('registration.registered')
        msg = tr('registration.success_message', v0=theme.verifiedIcon, v1=verb, v2=fid, v3=extra)
        # Called from both the deferred (new-user) and non-deferred (attach) paths.
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    def _server_name_or_id(self, server_id, interaction):
        if server_id is None:
            return "(no server)"
        guild = self.bot.get_guild(server_id) if self.bot else None
        if guild and guild.name:
            return guild.name
        if interaction.guild and interaction.guild.id == server_id:
            return interaction.guild.name
        return f"server `{server_id}`"

    # ── /unregister ────────────────────────────────────────────────────────

    async def unregister_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = self._linked_fids_for(interaction.user.id)
        cur = (current or "").lower()
        choices = []
        for fid, nickname, alliance, _ in rows:
            label = f"{nickname or tr('registration.unnamed')} ({fid})"
            if cur and cur not in str(fid) and cur not in (nickname or "").lower():
                continue
            choices.append(discord.app_commands.Choice(name=label[:100], value=fid))
            if len(choices) >= 25:
                break
        return choices

    @discord.app_commands.command(
        name="unregister",
        description=tr('registration.unregister_description'),
    )
    @discord.app_commands.describe(fid=tr('registration.unlink_option'))
    @discord.app_commands.rename(fid="id")
    @discord.app_commands.autocomplete(fid=unregister_autocomplete)
    async def unregister(self, interaction: discord.Interaction, fid: int):
        caller_id = interaction.user.id
        existing = self._get_user_row(fid)

        if not existing:
            await interaction.response.send_message(
                tr('registration.not_registered', v0=theme.deniedIcon, v1=fid),
                ephemeral=True,
            )
            return

        linked_discord_id = existing[1]
        if linked_discord_id is None:
            await interaction.response.send_message(
                tr('registration.not_linked', v0=theme.deniedIcon, v1=fid),
                ephemeral=True,
            )
            return

        if linked_discord_id != caller_id:
            await interaction.response.send_message(
                tr('registration.wrong_owner', v0=theme.deniedIcon, v1=fid),
                ephemeral=True,
            )
            return

        self._detach_discord(fid)
        remaining = self._linked_fids_for(caller_id)
        if remaining:
            lines = "\n".join(
                f"  {theme.fidIcon} `{f}` — {n or tr('registration.unnamed')}"
                for f, n, _, _ in remaining
            )
            extra = tr('registration.remaining_characters', v0=len(remaining), v1=lines)
        else:
            extra = tr('registration.no_characters')
        await interaction.response.send_message(
            tr('registration.unlink_success', v0=theme.verifiedIcon, v1=fid, v2=extra),
            ephemeral=True,
        )


class _MoveServerView(discord.ui.View):
    def __init__(self, cog: AllianceRegistration, fid: int, caller_id: int,
                 old_server_id, new_server_id):
        super().__init__(timeout=menu_timeout())
        self.cog = cog
        self.fid = fid
        self.caller_id = caller_id
        self.old_server_id = old_server_id
        self.new_server_id = new_server_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.caller_id:
            await interaction.response.send_message(
                tr('registration.wrong_prompt', v0=theme.deniedIcon),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label=tr('registration.move_button'), style=discord.ButtonStyle.success,
                       emoji=f"{theme.verifiedIcon}")
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.cog._move_registration_to_server(self.fid, self.new_server_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=tr('registration.moved', v0=theme.verifiedIcon, v1=self.fid),
            view=self,
        )

    @discord.ui.button(label=tr('common.cancel'), style=discord.ButtonStyle.secondary,
                       emoji=f"{theme.backIcon}")
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=tr('registration.move_cancelled', v0=theme.infoIcon),
            view=self,
        )


async def setup(bot):
    await bot.add_cog(AllianceRegistration(bot))
