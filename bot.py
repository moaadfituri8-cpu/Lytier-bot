
import os
import re
import logging
from io import BytesIO
from urllib.parse import quote

import aiohttp
import asyncpg
import discord

from PIL import Image, ImageSequence
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput, Button


# ==========================================
# CONFIGURATION
# ==========================================

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
TESTER_ROLE_ID = int(os.getenv("TESTER_ROLE_ID", "0"))
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0"))

SKIN_RENDER_BASE = os.getenv(
    "SKIN_RENDER_BASE",
    "https://skinrender.dev"
).rstrip("/")

DATABASE_SSL = os.getenv("DATABASE_SSL", "require").lower()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ==========================================
# MODES
# ==========================================

MODS = {
    "VANILLA": "<:emoji_1:1569697593628565635>",
    "SWORD": "<:emoji_6:1569698369792774176>",
    "UHC": "<:emoji_2:1569697618307846225>",
    "SPEAR MACE": "<:emoji_6:1569698644523884685>",
    "MACE": "<:emoji_3:1569697636607336538>",
    "AXE": "<:emoji_7:1569698919515168778>",
    "POT": "<:emoji_9:1569699936134627448>",
    "SMP": "<:emoji_8:1569699066030325861>",
}


TIERS = [
    "HT1", "HT2", "HT3", "HT4", "HT5",
    "LT1", "LT2", "LT3", "LT4", "LT5"
]


TIER_COLORS = {
    "HT1": 0xFF3030,
    "HT2": 0xFF5555,
    "HT3": 0xFF7777,
    "HT4": 0xE67E22,
    "HT5": 0xF1C40F,
    "LT1": 0x3498DB,
    "LT2": 0x2980B9,
    "LT3": 0x1ABC9C,
    "LT4": 0x2ECC71,
    "LT5": 0x95A5A6,
}


# ==========================================
# BOT
# ==========================================

intents = discord.Intents.default()


class LytierBot(commands.Bot):

    async def setup_hook(self):

        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is missing!")

        ssl_value = "require" if DATABASE_SSL == "require" else None

        self.db = await asyncpg.create_pool(
            DATABASE_URL,
            ssl=ssl_value,
            min_size=1,
            max_size=5
        )

        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS player_tiers (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                player_name TEXT NOT NULL,
                mod TEXT NOT NULL,
                tier TEXT NOT NULL,
                tester_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(guild_id, player_name, mod)
            );
        """)

        self.add_view(TicketPanel())
        self.add_view(TicketControls())

        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        logging.info("Lytier bot is ready!")


bot = LytierBot(
    command_prefix="!",
    intents=intents
)


# ==========================================
# PERMISSIONS
# ==========================================

def is_tester(member):

    if member.guild_permissions.administrator:
        return True

    if TESTER_ROLE_ID == 0:
        return False

    return any(
        role.id == TESTER_ROLE_ID
        for role in member.roles
    )


# ==========================================
# SKIN RENDER
# ==========================================

async def get_skin_gif(player_name):

    encoded_name = quote(player_name)

    url = (
        f"{SKIN_RENDER_BASE}/render/"
        f"{encoded_name}/bust.apng"
        "?size=256&pose=walk&yaw=35&pitch=12&fit=false"
    )

    timeout = aiohttp.ClientTimeout(total=25)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:

            async with session.get(url) as response:

                if response.status != 200:
                    logging.warning(
                        "Skin API returned status %s",
                        response.status
                    )
                    return None

                apng_data = await response.read()

        original = Image.open(BytesIO(apng_data))

        frames = []
        durations = []

        for frame in ImageSequence.Iterator(original):

            frames.append(frame.convert("RGBA").copy())

            durations.append(
                frame.info.get("duration", 100)
            )

        if not frames:
            return None

        output = BytesIO()

        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
            optimize=True
        )

        output.seek(0)

        return output.getvalue()

    except Exception:
        logging.exception("Skin rendering failed.")
        return None


# ==========================================
# DATABASE
# ==========================================

async def save_tier(
    guild_id,
    player_name,
    mod,
    tier,
    tester_id
):

    await bot.db.execute("""
        INSERT INTO player_tiers (
            guild_id,
            player_name,
            mod,
            tier,
            tester_id
        )
        VALUES ($1, $2, $3, $4, $5)

        ON CONFLICT (guild_id, player_name, mod)
        DO UPDATE SET
            tier = EXCLUDED.tier,
            tester_id = EXCLUDED.tester_id,
            created_at = NOW();
    """,
        guild_id,
        player_name,
        mod,
        tier,
        tester_id
    )


# ==========================================
# TIER EMBED
# ==========================================

def make_tier_embed(
    player_name,
    mod,
    tier,
    tester,
    animated_skin
):

    tier = tier.upper()
    mod = mod.upper()

    if tier.startswith("LT"):
        tier_label = "Low tier:"
    else:
        tier_label = "High tier:"

    embed = discord.Embed(
        title="『 𝐋𝐲𝐭𝐢𝐞𝐫 🇱🇾 』",
        color=TIER_COLORS.get(tier, 0x5865F2)
    )

    embed.add_field(
        name="Name:",
        value=f"**{player_name}**",
        inline=False
    )

    embed.add_field(
        name="Mod:",
        value=f"**{mod} {MODS[mod]}**",
        inline=False
    )

    embed.add_field(
        name=tier_label,
        value=f"**{tier}**",
        inline=False
    )

    embed.add_field(
        name="Test by:",
        value=tester.mention,
        inline=False
    )

    embed.set_footer(
        text="Lytier Test 🇱🇾 • Official Tier Results"
    )

    if animated_skin:
        embed.set_thumbnail(url="attachment://skin.gif")

    else:
        # Static fallback if the animation API is unavailable
        embed.set_thumbnail(
            url=(
                f"{SKIN_RENDER_BASE}/render/"
                f"{quote(player_name)}/bust?size=200"
                "&yaw=35&pitch=12"
            )
        )

    return embed


# ==========================================
# TIER COMMAND
# ==========================================

@app_commands.guild_only()
@app_commands.choices(
    mod=[
        app_commands.Choice(name=name, value=name)
        for name in MODS
    ],
    tier=[
        app_commands.Choice(name=name, value=name)
        for name in TIERS
    ]
)
@bot.tree.command(
    name="tier",
    description="Publish a Minecraft player's tier."
)
async def tier_command(
    interaction: discord.Interaction,
    name: str,
    mod: app_commands.Choice[str],
    tier: app_commands.Choice[str]
):

    if not is_tester(interaction.user):
        return await interaction.response.send_message(
            "❌ ليس لديك صلاحية التستر.",
            ephemeral=True
        )

    player_name = name.strip()

    if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", player_name):
        return await interaction.response.send_message(
            "❌ اسم ماينكرافت غير صالح.",
            ephemeral=True
        )

    await interaction.response.defer()

    skin_gif = await get_skin_gif(player_name)

    embed = make_tier_embed(
        player_name,
        mod.value,
        tier.value,
        interaction.user,
        skin_gif is not None
    )

    await save_tier(
        interaction.guild_id,
        player_name,
        mod.value,
        tier.value,
        interaction.user.id
    )

    if skin_gif:

        file = discord.File(
            BytesIO(skin_gif),
            filename="skin.gif"
        )

        await interaction.followup.send(
            embed=embed,
            file=file
        )

    else:

        await interaction.followup.send(
            embed=embed
        )


# ==========================================
# TICKET PANEL
# ==========================================

class TicketPanel(View):

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketModSelect())


class TicketModSelect(Select):

    def __init__(self):

        options = []

        for name, emoji in MODS.items():

            options.append(
                discord.SelectOption(
                    label=name,
                    value=name,
                    emoji=discord.PartialEmoji.from_str(emoji),
                    description=f"Request a {name} test"
                )
            )

        super().__init__(
            placeholder="Choose your testing mode...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="lytier:ticket_mod"
        )

    async def callback(self, interaction):

        selected_mod = self.values[0]

        await interaction.response.send_modal(
            TicketAccountModal(selected_mod)
        )


# ==========================================
# PREMIUM / CRACKED MODAL
# ==========================================

class TicketAccountModal(Modal):

    def __init__(self, mod):

        super().__init__(
            title="Lytier Test • Account Type"
        )

        self.mod = mod

        self.account_type = TextInput(
            label="Premium or Cracked?",
            placeholder="Write Premium or Cracked",
            min_length=6,
            max_length=7,
            required=True
        )

        self.add_item(self.account_type)

    async def on_submit(self, interaction):

        account = self.account_type.value.strip().lower()

        if account not in ("premium", "cracked"):

            return await interaction.response.send_message(
                "❌ اكتب Premium أو Cracked فقط.",
                ephemeral=True
            )

        guild = interaction.guild

        if guild is None:
            return

        # Check existing ticket
        for channel in guild.text_channels:

            if channel.topic == f"lytier_ticket:{interaction.user.id}":

                return await interaction.response.send_message(
                    f"لديك تكت مفتوح بالفعل: {channel.mention}",
                    ephemeral=True
                )

        category = guild.get_channel(TICKET_CATEGORY_ID)

        if not isinstance(category, discord.CategoryChannel):
            category = None

        bot_member = guild.me

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),

            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True
            )
        }

        if bot_member:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True
            )

        if TESTER_ROLE_ID:

            tester_role = guild.get_role(TESTER_ROLE_ID)

            if tester_role:

                overwrites[tester_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

        safe_name = re.sub(
            r"[^a-z0-9-]",
            "-",
            interaction.user.name.lower()
        )[:20]

        try:

            channel = await guild.create_text_channel(
                name=f"test-{safe_name}",
                category=category,
                overwrites=overwrites,
                topic=f"lytier_ticket:{interaction.user.id}"
            )

            embed = discord.Embed(
                title="『 𝐋𝐲𝐭𝐢𝐞𝐫 𝐓𝐞𝐬𝐭 🇱🇾 』",
                description=(
                    f"Welcome to **Lytier Test**, {interaction.user.mention}!\n\n"

                    "نورت في **Lytier Test 🇱🇾**!\n"
                    "يسعدنا اختيارك لسيرفرنا، ونتمنى لك اختباراً ممتعاً.\n\n"

                    "**Ticket Information**\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"**Player:** {interaction.user.mention}\n"
                    f"**Game Mode:** {self.mod} {MODS[self.mod]}\n"
                    f"**Account Type:** {account.capitalize()}\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"

                    "**Before Your Test**\n"
                    "• تأكد من أنك اخترت المود الصحيح.\n"
                    "• انتظر حتى يتوفر أحد المختبرين.\n"
                    "• لا تقم بمنشن الإدارة بشكل متكرر.\n"
                    "• حافظ على الاحترام داخل التكت.\n\n"

                    "**Important**\n"
                    "سيتم اختبارك من قبل أحد أعضاء فريق الإدارة، "
                    "وبعد انتهاء الاختبار سيتم إرسال نتيجتك هنا.\n\n"

                    "يرجى الانتظار حتى تختبرك الإدارة.\n\n"

                    "**Thank you for choosing Lytier Test 🇱🇾**"
                ),
                color=0x5865F2
            )

            embed.set_footer(
                text="Lytier Test • Please wait for staff"
            )

            await channel.send(
                content=interaction.user.mention,
                embed=embed,
                view=TicketControls()
            )

            await interaction.response.send_message(
                f"✅ تم فتح تكتك بنجاح: {channel.mention}",
                ephemeral=True
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ البوت لا يملك صلاحية إنشاء الرومات.",
                ephemeral=True
            )

        except Exception:

            logging.exception("Ticket creation failed.")

            await interaction.response.send_message(
                "❌ حدث خطأ أثناء إنشاء التكت.",
                ephemeral=True
            )


# ==========================================
# TICKET CLOSE BUTTON
# ==========================================

class TicketControls(View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="lytier:close_ticket"
    )
    async def close_ticket(
        self,
        interaction,
        button
    ):

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            return

        topic = channel.topic or ""

        match = re.fullmatch(
            r"lytier_ticket:(\d+)",
            topic
        )

        if not match:

            return await interaction.response.send_message(
                "❌ هذه ليست قناة تكت.",
                ephemeral=True
            )

        owner_id = int(match.group(1))

        is_owner = interaction.user.id == owner_id
        staff = is_tester(interaction.user)

        if not is_owner and not staff:

            return await interaction.response.send_message(
                "❌ لا يمكنك إغلاق هذا التكت.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "🔒 سيتم إغلاق التكت."
        )

        await channel.delete(
            reason=f"Ticket closed by {interaction.user}"
        )


# ==========================================
# TICKET PANEL COMMAND
# ==========================================

@bot.tree.command(
    name="ticket_panel",
    description="Send the Lytier ticket panel."
)
@app_commands.guild_only()
async def ticket_panel_command(interaction):

    if not is_tester(interaction.user):

        return await interaction.response.send_message(
            "❌ ليس لديك صلاحية.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="『 𝐋𝐲𝐭𝐢𝐞𝐫 🇱🇾 』",
        description=(
            "Welcome to **Lytier Test 🇱🇾**!\n\n"

            "هل ترغب في معرفة مستواك والحصول على تقييم "
            "رسمي لمهاراتك في Minecraft؟ أنت في المكان الصحيح!\n\n"

            "من خلال نظام الاختبارات الخاص بنا، يمكنك طلب اختبار "
            "في المود الذي تفضله والحصول على تقييم من أحد المختبرين.\n\n"

            "**How to Start?**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "1. اختر المود الذي تريد اختباره من القائمة.\n"
            "2. ستظهر لك نافذة لتحديد نوع حسابك.\n"
            "3. اختر Premium أو Cracked.\n"
            "4. سيتم إنشاء تكت خاص بك مع فريق الإدارة.\n"
            "5. انتظر المختبر حتى يبدأ اختبارك.\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            "**Testing Rules**\n"
            "• اختر المود المناسب لك.\n"
            "• لا تفتح أكثر من تكت لنفس الطلب.\n"
            "• لا تزعج المختبرين بالمنشن المتكرر.\n"
            "• تعامل باحترام مع الجميع.\n\n"

            "نتمنى لك تجربة رائعة ونتيجة موفقة!\n\n"
            "**Lytier Test 🇱🇾**"
        ),
        color=0x5865F2
    )

    embed.set_footer(
        text="Select a game mode below to open your ticket."
    )

    await interaction.response.send_message(
        embed=embed,
        view=TicketPanel()
    )


# ==========================================
# START
# ==========================================

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing!")

bot.run(TOKEN)

