import discord
from discord.ext import commands, tasks
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timedelta
import asyncio
import re
from discord.ui import Modal, View, Button, TextInput
from discord import app_commands
from discord.ext.commands import Context
from flask import Flask
from threading import Thread

# Basic imports for the Discord bot
import asyncio
from threading import Thread


# Initialize Firebase Admin SDK
cred = credentials.Certificate('firebase-credentials.json')  # Replace with your actual file name
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://botx09-ac3ba-default-rtdb.firebaseio.com'  # Your Firebase Realtime Database URL
})

# Initialize the bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
# Initialize event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Function to log punishments to Firebase
def log_punishment(user_id, punishment_type, reason, duration=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ref = db.reference(f"punishments/{user_id}")

    # Get current cases to determine next case ID
    current_cases = ref.get() or {}
    next_case_id = str(len(current_cases) + 1).zfill(4)  # Pad with zeros for consistent formatting

    punishment_data = {
        "case_id": next_case_id,
        "user_id": user_id,
        "punishment_type": punishment_type,
        "reason": reason,
        "timestamp": timestamp,
        "duration": duration
    }

    ref.child(next_case_id).set(punishment_data)
    return next_case_id

#Custom decorator to check for moderator role
def has_mod_role():
    async def predicate(ctx):
        mod_role_id = 1365869028958011544
        mod_role = ctx.guild.get_role(mod_role_id)
        if not mod_role:
            await ctx.send("Error: Moderator role not found. Please check the role ID.")
            return False
        return mod_role in ctx.author.roles
    return commands.check(predicate)

# 1. **Warn Command**
@bot.command()
@has_mod_role()
async def warn(ctx, member: discord.Member, *, reason=None):
    if reason is None:
        await ctx.send("Please provide a reason for the warning.")
        return

    log_punishment(member.id, "warn", reason)

    try:
        await member.send(f"You have been warned in {ctx.guild.name} for: {reason}")
    except discord.Forbidden:
        await ctx.send(f"Could not DM {member.name}, but they have been warned.")

    embed = discord.Embed(title="Warning", description=f"{member.mention} has been warned for: {reason}", color=discord.Color.purple())
    await ctx.send(embed=embed)

# 2. **Ban Command**
@bot.command()
@has_mod_role()
async def ban(ctx, member: discord.Member, *, reason=None):
    if reason is None:
        await ctx.send("Please provide a reason for the ban.")
        return

    log_punishment(member.id, "ban", reason)

    await member.send(f"You have been banned from {ctx.guild.name} for: {reason}")
    await member.ban(reason=reason)

    embed = discord.Embed(title="Ban", description=f"{member.mention} has been banned for: {reason}", color=discord.Color.purple())
    await ctx.send(embed=embed)

# 3. **Unban Command**
@bot.command()
@has_mod_role()
async def unban(ctx, user: discord.User, *, reason=None):
    if reason is None:
        await ctx.send("Please provide a reason for the unban.")
        return

    log_punishment(user.id, "unban", reason)

    await ctx.guild.unban(user, reason=reason)

    embed = discord.Embed(title="Unban", description=f"{user.mention} has been unbanned for: {reason}", color=discord.Color.purple())
    await ctx.send(embed=embed)

# 4. **Kick Command**
@bot.command()
@has_mod_role()
async def kick(ctx, member: discord.Member, *, reason=None):
    if reason is None:
        await ctx.send("Please provide a reason for the kick.")
        return

    log_punishment(member.id, "kick", reason)

    await member.send(f"You have been kicked from {ctx.guild.name} for: {reason}")
    await member.kick(reason=reason)

    embed = discord.Embed(title="Kick", description=f"{member.mention} has been kicked for: {reason}", color=discord.Color.purple())
    await ctx.send(embed=embed)

# 5. **Mute Command (Now a Timeout)**
@bot.command()
@has_mod_role()
async def mute(ctx, member: discord.Member, duration: str, *, reason=None):
    if reason is None:
        await ctx.send("Please provide a reason for the mute.")
        return

    log_punishment(member.id, "timeout", reason, duration)

    await member.send(f"You have been timed out in {ctx.guild.name} for {duration} for: {reason}")

    # Parse the duration
    timeout_duration = parse_duration(duration)
    if timeout_duration is None:
        await ctx.send("Invalid duration format. Please use a valid format like '1m', '2h', or '30s'.")
        return

    timeout_end = discord.utils.utcnow() + timeout_duration

    try:
        await member.timeout(timeout_end, reason=reason)
    except Exception as e:
        await ctx.send(f"Error applying timeout: {str(e)}")
        return

    embed = discord.Embed(title="Timeout", description=f"{member.mention} has been timed out for {duration} for: {reason}", color=discord.Color.purple())
    await ctx.send(embed=embed)

# 6. **Unmute Command**
@bot.command()
@has_mod_role()
async def unmute(ctx, member: discord.Member, *, reason=None):
    if reason is None:
        await ctx.send("Please provide a reason for the unmute.")
        return

    log_punishment(member.id, "unmute", reason)

    await member.send(f"You have been unmuted in {ctx.guild.name} for: {reason}")

    try:
        await member.timeout(None, reason=reason)
    except Exception as e:
        await ctx.send(f"Error removing timeout: {str(e)}")
        return

    embed = discord.Embed(title="Unmute", description=f"{member.mention} has been unmuted for: {reason}", color=discord.Color.purple())
    await ctx.send(embed=embed)

# 7. **Modlogs Command**
@bot.command()
@has_mod_role()
async def modlogs(ctx, member: discord.Member):
    ref = db.reference(f'punishments/{member.id}')
    punishments = ref.get()

    if punishments is None:
        await ctx.send(f"No punishments found for {member.mention}.")
        return

    # Convert punishments to list and sort by timestamp
    punishment_list = list(punishments.values())
    punishment_list.sort(key=lambda x: x['timestamp'], reverse=True)

    items_per_page = 5
    pages = [punishment_list[i:i + items_per_page] for i in range(0, len(punishment_list), items_per_page)]
    current_page = 0

    def create_embed(page_num):
        embed = discord.Embed(
            title=f"{member.name}'s Punishment Logs",
            color=discord.Color.purple(),
            timestamp=datetime.now()
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        embed.set_footer(text=f"Page {page_num + 1}/{len(pages)} | Total Records: {len(punishment_list)}")

        for log in pages[page_num]:
            # Convert punishment type to title case and add emoji
            punishment_type = log['punishment_type'].title()
            emoji = {
                "Warn": "⚠️",
                "Ban": "🔨",
                "Unban": "🔓",
                "Kick": "👢",
                "Timeout": "⏰",
                "Unmute": "🔊"
            }.get(punishment_type, "📝")

            case_id = log.get('case_id', 'N/A')
            embed.add_field(
                name=f"{emoji} {punishment_type} (Case #{case_id})",
                value=f"**Reason:** {log.get('reason', 'No reason provided')}\n**Time:** {log.get('timestamp', 'No time recorded')}"
                + (f"\n**Duration:** {log['duration']}" if log.get('duration') else ""),
                inline=False
            )
        return embed

    message = await ctx.send(embed=create_embed(current_page))

    # Add reactions only if there are multiple pages
    if len(pages) > 1:
        await message.add_reaction("◀️")
        await message.add_reaction("▶️")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["◀️", "▶️"]

        while True:
            try:
                reaction, user = await bot.wait_for("reaction_add", timeout=60.0, check=check)

                if str(reaction.emoji) == "▶️" and current_page < len(pages) - 1:
                    current_page += 1
                    await message.edit(embed=create_embed(current_page))
                elif str(reaction.emoji) == "◀️" and current_page > 0:
                    current_page -= 1
                    await message.edit(embed=create_embed(current_page))

                await message.remove_reaction(reaction, user)
            except asyncio.TimeoutError:
                break

# Task that runs every 20 minutes
@tasks.loop(minutes=20)
async def do_periodic_task():
    # This could be any action, such as sending a message
    # Here we're sending a message to a specific channel
    channel = bot.get_channel(1365748874366681189)  # Replace with your channel ID
    if channel:
        await channel.send("I'm still here!")  # You can change this message

# Start the periodic task when the bot is ready
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    do_periodic_task.start()  # Start the loop

# Function to parse durations (like '1m', '2h', '30s')
def parse_duration(duration):
    pattern = re.compile(r"(\d+)([smh])")
    match = pattern.fullmatch(duration)
    if not match:
        return None

    value, unit = match.groups()
    value = int(value)

    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)

@bot.command()
@has_mod_role()
async def removecase(ctx, case_id: str, *, reason="No reason provided"):
    # Search for the case in all users' punishment logs
    ref = db.reference('punishments')
    all_users = ref.get() or {}

    for user_id, cases in all_users.items():
        if case_id in cases:
            # Remove the case
            ref.child(f"{user_id}/{case_id}").delete()

            embed = discord.Embed(
                title="Case Removed",
                description=f"Case #{case_id} has been removed\nReason: {reason}",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            return

    await ctx.send(f"Case #{case_id} not found.")

@bot.command(name="commands")
@has_mod_role()
async def show_commands(ctx):
    try:
        embed = discord.Embed(
            title="🛠️ Moderator Commands",
            description="Here's a list of available moderation commands:",
            color=discord.Color.purple()
        )

        embed.add_field(name="!warn @user [reason]", value="Warns a member.", inline=False)
        embed.add_field(name="!ban @user [reason]", value="Bans a member.", inline=False)
        embed.add_field(name="!unban user_id [reason]", value="Unbans a previously banned user.", inline=False)
        embed.add_field(name="!kick @user [reason]", value="Kicks a member.", inline=False)
        embed.add_field(name="!mute @user [duration] [reason]", value="Timeouts a member. (e.g., 10m, 2h)", inline=False)
        embed.add_field(name="!unmute @user [reason]", value="Removes a member's timeout.", inline=False)
        embed.add_field(name="!modlogs @user", value="Displays a member's punishment history.", inline=False)
        embed.add_field(name="!removecase case_id [reason]", value="Deletes a punishment record by case ID.", inline=False)

        embed.set_footer(text="Only visible to users with Moderator role.")
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else discord.Embed.Empty)

        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")



CATEGORY_ID = 1366141177887330484  # Approval category ID
tree = bot.tree
  # All post approval channels go here

class ForHireModal(Modal):
    def __init__(self, user):
        super().__init__(title="🛠️ For Hire Post")
        self.user = user
        self.description = TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=500)
        self.payment = TextInput(label="Payment", max_length=100)
        self.portfolio = TextInput(label="Portfolio URL", max_length=300)
        self.add_item(self.description)
        self.add_item(self.payment)
        self.add_item(self.portfolio)

    async def on_submit(self, interaction: discord.Interaction):
        await create_approval_channel(interaction.guild, self.user, "forhire", {
            "description": self.description.value,
            "payment": self.payment.value,
            "portfolio": self.portfolio.value
        }, interaction)


class HiringModal(Modal):
    def __init__(self, user):
        super().__init__(title="📢 Hiring Post")
        self.user = user
        self.description = TextInput(label="Job Description", style=discord.TextStyle.paragraph, max_length=500)
        self.payment = TextInput(label="Payment", max_length=100)
        self.deadline = TextInput(label="Deadline", max_length=100)
        self.add_item(self.description)
        self.add_item(self.payment)
        self.add_item(self.deadline)

    async def on_submit(self, interaction: discord.Interaction):
        await create_approval_channel(interaction.guild, self.user, "hiring", {
            "description": self.description.value,
            "payment": self.payment.value,
            "deadline": self.deadline.value
        }, interaction)


class SellingModal(Modal):
    def __init__(self, user):
        super().__init__(title="🛒 Selling Post")
        self.user = user
        self.description = TextInput(label="Item Description", style=discord.TextStyle.paragraph, max_length=500)
        self.payment = TextInput(label="Price", max_length=100)
        self.image_url = TextInput(label="Image URL", max_length=300)
        self.add_item(self.description)
        self.add_item(self.payment)
        self.add_item(self.image_url)

    async def on_submit(self, interaction: discord.Interaction):
        await create_approval_channel(interaction.guild, self.user, "selling", {
            "description": self.description.value,
            "payment": self.payment.value,
            "image_url": self.image_url.value
        }, interaction)

# 🔧 Create approval channel for any post type
async def create_approval_channel(guild, user, post_type, fields, interaction):
    # Check bot permissions
    if not guild.me.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Bot doesn't have permission to create channels. Please contact server admin.", ephemeral=True)
        return

    category = guild.get_channel(CATEGORY_ID)
    if not category:
        await interaction.response.send_message("❌ Approval category not found.", ephemeral=True)
        return

    channel_name = f"{post_type}-{user.name}".replace(" ", "-").lower()
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),  # Hide from everyone
        guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True),  # Allow bot
        guild.get_role(1363637131041570987): discord.PermissionOverwrite(read_messages=True),  # Role 1
        guild.get_role(1363638072167760054): discord.PermissionOverwrite(read_messages=True),  # Role 2
    }



    try:
        post_channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)
    except discord.Forbidden as e:
        await interaction.response.send_message(f"❌ Error creating channel: {str(e)}. Please contact server admin.", ephemeral=True)
        return
    except Exception as e:
        await interaction.response.send_message(f"❌ An unexpected error occurred: {str(e)}", ephemeral=True)
        return

    # Save to Firebase
    ref = db.reference(f"posts/{user.id}")
    post_data = fields.copy()
    post_data.update({
        "channel_id": post_channel.id,
        "post_type": post_type,
        "approved": False,
        "declined": False,
        "timestamp": datetime.now().isoformat()
    })
    ref.set(post_data)

    # Create approval embed
    embed = discord.Embed(
        title=f"{post_type.capitalize()} Post - Pending Approval",
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    for key, val in fields.items():
        embed.add_field(name=key.capitalize(), value=val, inline=False)
    embed.set_footer(text="Awaiting moderator action...")

    # Buttons
    view = View()

    async def approve_callback(btn_interaction):
        ref.child("approved").set(True)
        await post_channel.send(f"{user.mention} ✅ Your post was approved by {btn_interaction.user.mention}. You can now use `/repost` to post it in the appropriate channel.")
        await user.send(f"✅ Your {post_type} post has been approved! You can now use `/repost` to publish it in the appropriate channel.")
        await btn_interaction.response.send_message("Post approved!", ephemeral=True)
        await asyncio.sleep(10)
        await post_channel.delete()

    async def decline_callback(btn_interaction):
        ref.child("declined").set(True)
        await post_channel.delete()
        await user.send(f"❌ Your {post_type} post was declined. You can submit a new post after making the necessary changes.")
        await btn_interaction.response.send_message("Post declined and deleted.", ephemeral=True)

    approve_btn = Button(label="Approve", style=discord.ButtonStyle.success)
    approve_btn.callback = approve_callback
    decline_btn = Button(label="Decline", style=discord.ButtonStyle.danger)
    decline_btn.callback = decline_callback
    view.add_item(approve_btn)
    view.add_item(decline_btn)

    await post_channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"✅ Your post has been submitted to {post_channel.mention} for approval!", ephemeral=True)

# /post command


@bot.tree.command(name="post", description="Submit a post for hire, hiring, or selling.")
@app_commands.describe(type="Select the type of post you want to create")
@app_commands.choices(type=[
    app_commands.Choice(name="For Hire", value="forhire"),
    app_commands.Choice(name="Hiring", value="hiring"),
    app_commands.Choice(name="Selling", value="selling")
])
async def post(interaction: discord.Interaction, type: str):
    user = interaction.user
    type = type.lower()

    # Check if the user has an existing pending post
    ref = db.reference(f'posts/{user.id}')
    existing_post = ref.get()
    if existing_post and not existing_post.get("approved") and not existing_post.get("declined"):
        await interaction.response.send_message("❌ You already have a pending post. Please wait for it to be approved or declined before submitting a new one.", ephemeral=True)
        return

    if type == "forhire":
        await interaction.response.send_modal(ForHireModal(user))
    elif type == "hiring":
        await interaction.response.send_modal(HiringModal(user))
    elif type == "selling":
        await interaction.response.send_modal(SellingModal(user))
    else:
        await interaction.response.send_message("❌ Invalid post type. Use: `forhire`, `hiring`, or `selling`.", ephemeral=True)



# ✅ Approve/Decline from Shell or Command
@bot.command()
async def approve(ctx, post_type: str, user_id: int):
    ref = db.reference(f"{post_type}/{user_id}")
    post = ref.get()
    if post:
        ref.child("approved").set(True)
        await ctx.send(f"✅ Approved {post_type} post for user `{user_id}`.")
    else:
        await ctx.send("❌ Post not found.")

@bot.command()
async def decline(ctx, post_type: str, user_id: int):
    ref = db.reference(f"{post_type}/{user_id}")
    post = ref.get()
    if post:
        ref.child("declined").set(True)
        channel_id = post.get("channel_id")
        channel = ctx.guild.get_channel(channel_id)
        if channel:
            await channel.delete()
        await ctx.send(f"❌ Declined and removed channel for user `{user_id}`.")
    else:
        await ctx.send("❌ Post not found.")






@bot.tree.command(name="repost", description="Post your approved post to the appropriate channel.")
@app_commands.describe(type="Select which post you want to repost")
@app_commands.choices(type=[
    app_commands.Choice(name="For Hire", value="forhire"),
    app_commands.Choice(name="Hiring", value="hiring"),
    app_commands.Choice(name="Selling", value="selling")
])
async def repost(interaction: discord.Interaction, type: str):
    user = interaction.user

    # Check cooldown from Firebase
    current_time = datetime.now().timestamp()
    cooldown_ref = db.reference(f'cooldowns/{user.id}/{type}')
    last_repost = cooldown_ref.get()

    if last_repost:
        remaining = last_repost - current_time + (300)
        if remaining > 0:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            await interaction.response.send_message(f"❌ Please wait {hours}h {minutes}m before reposting.", ephemeral=True)
            return

    # FIX: Check correct post path
    ref = db.reference(f'posts/{user.id}')
    post = ref.get()
    if not post or not post.get("approved"):
        await interaction.response.send_message(f"❌ You don't have an approved {type} post to repost.", ephemeral=True)
        return

    # Channel IDs for different post types
    channel_ids = {
        "forhire": 1366119533391122442,
        "hiring": 1366119591926956093,
        "selling": 1366142055008571505
    }

    target_channel = interaction.guild.get_channel(channel_ids[type])

    if not target_channel:
        await interaction.response.send_message("❌ Target channel not found.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"{type.capitalize()} Post",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

    for key, val in post.items():
        if key not in ["channel_id", "approved", "declined", "timestamp", "post_type"]:
            embed.add_field(name=key.capitalize(), value=val, inline=False)

    await target_channel.send(content=user.mention, embed=embed)

    cooldown_ref.set(current_time)

    ref.delete()

    await interaction.response.send_message("✅ Your post has been published!", ephemeral=True)











@tree.command(name="ping", description="Check the bot's latency.")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)

    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"The bot is alive and responding!\n\n**Latency:** `{latency_ms}ms`",
        color=discord.Color.purple()
    )

    if bot.user.avatar:
        embed.set_thumbnail(url=bot.user.avatar.url)

    embed.set_footer(text="Ping command executed")
    await interaction.response.send_message(embed=embed)





@tasks.loop(minutes=20)
async def send_hello():
    channel = bot.get_channel(1366152984446238751)
    if channel:
        await channel.send("Syncing...")

@send_hello.before_loop
async def before_send_hello():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    send_hello.start()  # Start the task only after the bot is ready


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'Logged in as {bot.user.name}')
    # Set the "Playing" status
    await bot.change_presence(activity=discord.Game(name="moderating TimeDevs"))

# Add any other bot commands or event listeners here


        # Run the bot with your token
bot.run('MTM2NjA3MjIyMDgyODMwNzUyMA.GHPexx.OhjyZ4qO6KgyK8m0RMeUboaerH7LTWZwPHnI3c')
