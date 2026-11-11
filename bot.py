
import os
import re
import logging
import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
TESTER_ROLE_ID = int(os.getenv("TESTER_ROLE_ID", "0"))
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0"))

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

TIERS = ["LT5", "LT4", "LT3", "LT2", "LT1",
         "HT5", "HT4", "HT3", "HT2", "HT1"]

COLORS = {
    "LT5": 0x7F8C8D, "LT4": 0x95A5A6,
    "LT3": 0x3498DB, "LT2": 0x2980B9,
    "LT1": 0x1ABC9C, "HT5": 0x2ECC71,
    "HT4": 0xF1C40F, "HT3": 0xE67E22,
    "HT2": 0xE74C3C, "HT1": 0x9B59B6,
}

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# RAM only: data resets after restart
tier_cache = {}
open_tickets = {}


def get_role(guild):
    return guild.get_role(TESTER_ROLE_ID) if TESTER_ROLE_ID else None


def get_category(guild):
    category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
    return category if isinstance(category, discord.CategoryChannel) else None


def is_staff(member):
    role = get_role(member.guild)
    return (
        member.guild_permissions.manage_channels
        or member.guild_permissions.administrator
        or (role is not None and role in member.roles)
    )


class CloseTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="lytier:close"
    )
    async def close(self, interaction, button):
        channel = interaction.channel

        match = re.search(
            r"ticket_owner=(\d+)",
            channel.topic or ""
        )
        owner_id = int(match.group(1)) if match else 0

        staff = (
            isinstance(interaction.user, discord.Member)
            and is_staff(interaction.user)
        )

        if interaction.user.id != owner_id and not staff:
            return await interaction.response.send_message(
                "Only ticket owner or staff can close this ticket.",
                ephemeral=True
            )

        await interaction.response.send_message("Closing ticket...")
        open_tickets.pop(owner_id, None)
        await channel.delete()


class AccountModal(discord.ui.Modal):
    def __init__(self, mode):
        super().__init__(title="Account Type")
        self.mode = mode

        self.account = discord.ui.TextInput(
            label="Premium or Cracked",
            placeholder="Premium or Cracked",
            min_length=7,
            max_length=7
        )
        self.add_item(self.account)

    async def on_submit(self, interaction):
        account = self.account.value.strip().lower()

        if account not in ("premium", "cracked"):
            return await interaction.response.send_message(
                "Enter Premium or Cracked only.",
                ephemeral=True
            )

        guild = interaction.guild
        old_id = open_tickets.get(interaction.user.id)

        if old_id:
            old = guild.get_channel(old_id)
            if old:
                return await interaction.response.send_message(
                    f"You already have a ticket: {old.mention}",
                    ephemeral=True
                )

        role = get_role(guild)

        overwrites = {
            guild.default_role:
                discord.PermissionOverwrite(view_channel=False),

            interaction.user:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
        }

        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True
            )

        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        name = re.sub(
            r"[^a-z0-9-]",
            "-",
            interaction.user.name.lower()
        )[:18]

        try:
            channel = await guild.create_text_channel(
                f"ticket-{name}",
                category=get_category(guild),
                overwrites=overwrites,
                topic=f"ticket_owner={interaction.user.id}"
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Bot needs Manage Channels permission.",
                ephemeral=True
            )

        open_tickets[interaction.user.id] = channel.id

        embed = discord.Embed(
            title="نورت في Lytier test 🇱🇾",
            description=(
                f"أهلًا {interaction.user.mention}!\n\n"
                "تم فتح تذكرتك بنجاح.\n"
                "انتظر أحد المختبرين حتى يبدأ اختبارك."
            ),
            color=0x5865F2
        )

        embed.add_field(
            name="Mod:",
            value=f"{self.mode} {MODS[self.mode]}"
        )
        embed.add_field(
            name="Account:",
            value=account.title()
        )

        await channel.send(
            content=(
                f"{interaction.user.mention} "
                f"{role.mention if role else ''}"
            ),
            embed=embed,
            view=CloseTicket()
        )

        await interaction.response.send_message(
            f"Ticket created: {channel.mention}",
            ephemeral=True
        )


class ModeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=mode.title(),
                value=mode,
                emoji=discord.PartialEmoji.from_str(MODS[mode])
            )
            for mode in MODS
        ]

        super().__init__(
            placeholder="Choose your test mode...",
            options=options,
            custom_id="lytier:mode"
        )

    async def callback(self, interaction):
        await interaction.response.send_modal(
            AccountModal(self.values[0])
        )


class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ModeSelect())


@bot.tree.command(
    name="ticket_panel",
    description="Send Lytier ticket panel"
)
@app_commands.guild_only()
async def ticket_panel(interaction):
    embed = discord.Embed(
        title="Lytier 🇱🇾 | Test Center",
        description=(
            "Welcome to Lytier Test!\n\n"
            "Choose your test mode below.\n"
            "Then select Premium or Cracked.\n\n"
            "A private ticket will be created for you."
        ),
        color=0x5865F2
    )

    await interaction.response.send_message(
        embed=embed,
        view=TicketPanel()
    )


@bot.tree.command(
    name="tier",
    description="Publish player tier"
)
@app_commands.guild_only()
@app_commands.describe(
    player="Minecraft username",
    mod="Test mode",
    tier="Tier result"
)
@app_commands.choices(
    mod=[
        app_commands.Choice(name=m.title(), value=m)
        for m in MODS
    ],
    tier=[
        app_commands.Choice(name=t, value=t)
        for t in TIERS
    ]
)
async def tier_command(interaction, player, mod, tier):

    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        return await interaction.response.send_message(
            "Only testers can publish tiers.",
            ephemeral=True
        )

    if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", player):
        return await interaction.response.send_message(
            "Invalid Minecraft username.",
            ephemeral=True
        )

    tier_cache[(player.lower(), mod.value)] = tier.value

    embed = discord.Embed(
        title="Lytier 🇱🇾",
        color=COLORS[tier.value]
    )

    embed.add_field(name="Name:", value=player, inline=True)
    embed.add_field(
        name="Mod:",
        value=f"{mod.value} {MODS[mod.value]}",
        inline=True
    )

    label = "Low tier:" if tier.value.startswith("LT") else "High tier:"

    embed.add_field(
        name=label,
        value=tier.value,
        inline=True
    )

    embed.add_field(
        name="Test by:",
        value=interaction.user.mention
    )

    embed.set_thumbnail(
        url=f"https://mc-heads.net/body/{player}/100"
    )

    await interaction.response.send_message(embed=embed)


async def setup_commands():
    bot.add_view(TicketPanel())
    bot.add_view(CloseTicket())

    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()


bot.setup_hook = setup_commands


@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")


if not TOKEN:
    raise RuntimeError("TOKEN is missing from Railway Variables.")

bot.run(TOKEN)

