from __future__ import annotations
import os, asyncio, sqlite3, contextlib, aiohttp, discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

# ── env vars (ضعهم في Railway Variables) ──────────────────────────────────────
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
BOT_TOKEN     = os.getenv("BOT_TOKEN", "changeme")
API_BASE      = os.getenv("API_BASE", "http://localhost:8000")
GUILD_ID      = int(os.environ["GUILD_ID"])
TESTER_ROLE   = os.getenv("TESTER_ROLE", "Tester")
TICKET_CAT    = os.getenv("TICKET_CATEGORY", "Tickets")
DB_PATH       = Path(os.getenv("DB_PATH", "lytier_bot.db"))

# ── constants ─────────────────────────────────────────────────────────────────
MODS  = ['VANILLA','SWORD','UHC','SPEAR & MACE','MACE','AXE','POT','SMP']
TIERS = ['HT1','HT2','HT3','HT4','HT5','LT1','LT2','LT3','LT4','LT5']

TIER_COLORS = {
    'HT1':0xD4AF37,'HT2':0xC0C0C0,'HT3':0xCD7F32,
    'HT4':0x7B9EBF,'HT5':0x5A7A9A,'LT1':0x4A6A8A,
    'LT2':0x3A5070,'LT3':0x2A3850,'LT4':0x1A2638,'LT5':0x2A2A35,
}

STEVE_UUID = "8667ba71b85a4004af54457a9734eed7"

MOD_OPTIONS = [
    discord.SelectOption(label="VANILLA",    emoji="<:emoji_1:1569697593628565635>", value="VANILLA"),
    discord.SelectOption(label="SWORD",      emoji="<:emoji_5:1569697687350284288>", value="SWORD"),
    discord.SelectOption(label="MACE",       emoji="<:emoji_3:1569697636607336538>", value="MACE"),
    discord.SelectOption(label="SPEAR MACE", emoji="<:emoji_6:1569698644523884685>", value="SPEAR MACE"),
    discord.SelectOption(label="AXE",        emoji="<:emoji_7:1569698919515168778>", value="AXE"),
    discord.SelectOption(label="SMP",        emoji="<:emoji_8:1569699066030325861>", value="SMP"),
    discord.SelectOption(label="POT",        emoji="<:emoji_9:1569699936134627448>", value="POT"),
    discord.SelectOption(label="UHC",        emoji="<:emoji_2:1569697618307846225>", value="UHC"),
]

# ── database ──────────────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS role_map (
    guild_id  INTEGER NOT NULL,
    tier      TEXT    NOT NULL,
    role_id   INTEGER NOT NULL,
    PRIMARY KEY (guild_id, tier)
);

CREATE TABLE IF NOT EXISTS players (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    discord   TEXT,
    premium   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tiers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER NOT NULL REFERENCES players(id),
    mod        TEXT    NOT NULL,
    tier       TEXT    NOT NULL,
    tester     TEXT,
    tested_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(player_id, mod)
);
"""

@contextlib.contextmanager
def get_db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init_db():
    with get_db() as db:
        db.executescript(DDL)

def db_get_role_map(guild_id: int) -> dict[str, int]:
    with get_db() as db:
        rows = db.execute(
            "SELECT tier, role_id FROM role_map WHERE guild_id = ?", (guild_id,)
        ).fetchall()
    return {r["tier"]: r["role_id"] for r in rows}

def db_set_role(guild_id: int, tier: str, role_id: int):
    with get_db() as db:
        db.execute(
            "INSERT INTO role_map (guild_id, tier, role_id) VALUES (?,?,?) "
            "ON CONFLICT(guild_id, tier) DO UPDATE SET role_id = excluded.role_id",
            (guild_id, tier, role_id)
        )

def db_upsert_player(username: str, discord_tag: str, premium: bool,
                     mod: str, tier: str, tester: str):
    with get_db() as db:
        db.execute(
            "INSERT INTO players (username, discord, premium) VALUES (?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET discord=excluded.discord, premium=excluded.premium",
            (username, discord_tag, int(premium))
        )
        pid = db.execute(
            "SELECT id FROM players WHERE username = ?", (username,)
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO tiers (player_id, mod, tier, tester) VALUES (?,?,?,?) "
            "ON CONFLICT(player_id, mod) DO UPDATE SET "
            "tier=excluded.tier, tester=excluded.tester, tested_at=datetime('now')",
            (pid, mod, tier, tester)
        )

# ── helpers ───────────────────────────────────────────────────────────────────
def skin_url(username: str, premium: bool, size: int = 128) -> str:
    uuid = username if premium else STEVE_UUID
    return f"https://crafatar.com/avatars/{uuid}?size={size}&overlay"

# ── bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot  = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
G    = discord.Object(id=GUILD_ID)

# ══════════════════════════════════════════════════════════════════════════════
# /welcome
# ══════════════════════════════════════════════════════════════════════════════
@tree.command(name="welcome", description="Show the welcome message", guild=G)
async def welcome(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏆 Welcome to LyTier Test",
        description=(
            "**Welcome to the best ranking server in Libya**\n\n"
            "Here we test you to determine if you are among the best "
            "Libyan Minecraft players."
        ),
        color=0xC8151B,
    )
    embed.add_field(
        name="📋 Available Mods",
        value="\n".join(f"{o.emoji} **{o.label}**" for o in MOD_OPTIONS),
        inline=False,
    )
    embed.set_footer(text="LyTier Test • Libya's #1 Minecraft PvP Ranking")
    await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /tier  — Tester role فقط
# ══════════════════════════════════════════════════════════════════════════════
@tree.command(name="tier", description="Submit a tier test result", guild=G)
@app_commands.describe(
    nameplayer="Minecraft username",
    user="Discord user tested",
    mod="Mod tested",
    tier="Tier assigned (HT1–LT5)",
    premium="Premium account?",
)
@app_commands.choices(
    mod =[app_commands.Choice(name=m, value=m) for m in MODS],
    tier=[app_commands.Choice(name=t, value=t) for t in TIERS],
)
async def tier_cmd(
    interaction: discord.Interaction,
    nameplayer:  str,
    user:        discord.Member,
    mod:         app_commands.Choice[str],
    tier:        app_commands.Choice[str],
    premium:     bool = False,
):
    # ── Tester role check ──
    tester_role = discord.utils.get(interaction.guild.roles, name=TESTER_ROLE)
    if tester_role and tester_role not in interaction.user.roles:
        await interaction.response.send_message(
            f"❌ You need the **{TESTER_ROLE}** role to submit tier results.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    # ── push to API (optional — also writes locally below) ──
    if API_BASE != "http://localhost:8000":
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{API_BASE}/api/tier",
                json={
                    "username": nameplayer, "discord": str(user),
                    "mod": mod.value, "tier": tier.value,
                    "tester": str(interaction.user), "premium": premium,
                },
                params={"token": BOT_TOKEN}
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    await interaction.followup.send(f"❌ API error: {body}", ephemeral=True)
                    return

    # ── write directly to local DB ──
    db_upsert_player(nameplayer, str(user), premium, mod.value, tier.value, str(interaction.user))

    # ── build embed ──
    color = TIER_COLORS.get(tier.value, 0x4A6A8A)
    embed = discord.Embed(color=color)
    embed.set_author(
        name="LyTier Test — Tier Result",
        icon_url=skin_url(STEVE_UUID, False, 32)
    )
    embed.add_field(name="Name",       value=f"**{nameplayer}**",  inline=True)
    embed.add_field(name="Discord",    value=user.mention,          inline=True)
    embed.add_field(name="\u200b",     value="\u200b",              inline=True)
    embed.add_field(name="Mod",        value=f"`{mod.value}`",      inline=True)
    embed.add_field(name="Tier",       value=f"**{tier.value}**",   inline=True)
    embed.add_field(name="Account",    value="Premium" if premium else "Cracked", inline=True)
    embed.add_field(name="Tester by",  value=interaction.user.mention, inline=False)
    embed.set_thumbnail(url=skin_url(nameplayer, premium))
    embed.set_footer(text="LyTier Test • Libya's #1 Minecraft PvP Ranking")

    # ── auto-role: شيل القديم، أعطِ الجديد ──
    gmap = db_get_role_map(interaction.guild_id)
    if gmap:
        all_tier_role_ids = set(gmap.values())
        to_remove = [r for r in user.roles if r.id in all_tier_role_ids]
        if to_remove:
            await user.remove_roles(*to_remove, reason="LyTier tier update")
        new_rid = gmap.get(tier.value)
        if new_rid:
            new_role = interaction.guild.get_role(new_rid)
            if new_role:
                await user.add_roles(new_role, reason=f"LyTier {tier.value}")
                embed.add_field(name="Role assigned", value=new_role.mention, inline=False)

    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /auto_role  — admins فقط، محفوظ في DB
# ══════════════════════════════════════════════════════════════════════════════
@tree.command(name="auto_role", description="Map a tier to a Discord role (admin only)", guild=G)
@app_commands.describe(
    tier="Tier to map",
    role="Role to assign for this tier",
)
@app_commands.choices(
    tier=[app_commands.Choice(name=t, value=t) for t in TIERS],
)
@app_commands.checks.has_permissions(administrator=True)
async def auto_role_cmd(
    interaction: discord.Interaction,
    tier: app_commands.Choice[str],
    role: discord.Role,
):
    db_set_role(interaction.guild_id, tier.value, role.id)

    gmap  = db_get_role_map(interaction.guild_id)
    lines = "\n".join(
        f"`{t}` → <@&{gmap[t]}>" for t in TIERS if t in gmap
    ) or "None set yet."

    embed = discord.Embed(
        title="✅ Auto-Role Saved",
        description=f"`{tier.value}` → {role.mention}\n\n**Full mapping:**\n{lines}",
        color=TIER_COLORS.get(tier.value, 0xC8151B),
    )
    embed.set_footer(text="LyTier Test • Libya's #1 Minecraft PvP Ranking")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@auto_role_cmd.error
async def auto_role_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)

# ══════════════════════════════════════════════════════════════════════════════
# /lookup
# ══════════════════════════════════════════════════════════════════════════════
@tree.command(name="lookup", description="Look up a player's tier profile", guild=G)
@app_commands.describe(player="Minecraft username")
async def lookup(interaction: discord.Interaction, player: str):
    await interaction.response.defer()
    with get_db() as db:
        p = db.execute(
            "SELECT id, username, discord, premium FROM players WHERE username = ?",
            (player,)
        ).fetchone()
        if not p:
            await interaction.followup.send(f"❌ `{player}` not found.", ephemeral=True)
            return
        rows = db.execute(
            "SELECT mod, tier FROM tiers WHERE player_id = ?", (p["id"],)
        ).fetchall()

    embed = discord.Embed(title=p["username"], color=0xC8151B)
    embed.set_thumbnail(url=skin_url(p["username"], bool(p["premium"])))
    embed.add_field(name="Discord", value=p["discord"] or "—", inline=True)
    embed.add_field(name="Account", value="Premium" if p["premium"] else "Cracked", inline=True)
    if rows:
        embed.add_field(
            name="Tiers",
            value="\n".join(f"`{r['mod']}` → **{r['tier']}**" for r in rows),
            inline=False,
        )
    else:
        embed.add_field(name="Tiers", value="No tiers yet", inline=False)
    embed.set_footer(text="LyTier Test • Libya's #1 Minecraft PvP Ranking")
    await interaction.followup.send(embed=embed)

# ══════════════════════════════════════════════════════════════════════════════
# /ticket
# ══════════════════════════════════════════════════════════════════════════════
class ModSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a mod…",
            min_values=1, max_values=1,
            options=MOD_OPTIONS,
        )

    async def callback(self, interaction: discord.Interaction):
        mod   = self.values[0]
        guild = interaction.guild

        category = discord.utils.get(guild.categories, name=TICKET_CAT)
        if not category:
            category = await guild.create_category(TICKET_CAT)

        ticket_num   = len(category.channels) + 1
        channel_name = f"ticket-{ticket_num}"

        tester_role = discord.utils.get(guild.roles, name=TESTER_ROLE)
        overwrites  = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if tester_role:
            overwrites[tester_role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True
            )

        channel = await guild.create_text_channel(
            channel_name, category=category, overwrites=overwrites,
            topic=f"Ticket #{ticket_num} | Mod: {mod} | {interaction.user}",
        )

        embed = discord.Embed(
            title=f"Ticket #{ticket_num} — {mod}",
            description=(
                f"{interaction.user.mention} opened a ticket for **{mod}**.\n\n"
                "A tester will be with you shortly.\n"
                "Use `/close` to close this channel when done."
            ),
            color=0xC8151B,
        )
        embed.set_footer(text="LyTier Test • Libya's #1 Minecraft PvP Ranking")
        await channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Ticket created: {channel.mention}", ephemeral=True
        )


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ModSelect())


@tree.command(name="ticket", description="Open a tier-test ticket", guild=G)
async def ticket_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Open a Tier Test Ticket",
        description=(
            "**Welcome to the best ranking server in Libya**\n\n"
            "Here we test you to determine if you are among the best "
            "Libyan Minecraft players.\n\n"
            "Select the mod you want to be tested in:"
        ),
        color=0xC8151B,
    )
    embed.set_footer(text="LyTier Test • Libya's #1 Minecraft PvP Ranking")
    await interaction.response.send_message(embed=embed, view=TicketView())

# ══════════════════════════════════════════════════════════════════════════════
# /close
# ══════════════════════════════════════════════════════════════════════════════
@tree.command(name="close", description="Close this ticket channel", guild=G)
async def close_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    if not (ch.name.startswith("ticket-") and ch.category and ch.category.name == TICKET_CAT):
        await interaction.response.send_message("❌ Not a ticket channel.", ephemeral=True)
        return
    await interaction.response.send_message("🔒 Closing ticket…")
    await asyncio.sleep(3)
    await ch.delete(reason=f"Closed by {interaction.user}")

# ══════════════════════════════════════════════════════════════════════════════
# startup
# ══════════════════════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    init_db()
    bot.add_view(TicketView())
    await tree.sync(guild=G)
    print(f"[LyTier Bot] {bot.user} | Guild: {GUILD_ID} | DB: {DB_PATH}")

bot.run(DISCORD_TOKEN)
