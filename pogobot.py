#!/usr/bin/python3
# -*- coding: utf-8 -*-
import re
import string

import discord
import os, sys
import schedule, time

from discord.ext import commands
import asyncio
import configparser
from datetime import datetime, timedelta

from utility import get_field_by_name, check_footer, \
    get_role_from_name, get_static_map_url, load_locale, load_base_stats, \
    load_cp_multipliers, load_gyms, get_gym_coords, get_cp_range, \
    get_pokemon_id_from_name, printr, pokemon_match, check_roles, get_types, get_name, \
    get_map_dir_url

BOT_PREFIX = "!"
BOT_TOKEN = None
MOD_ROLE_ID = None
RAID_ROLE_ID = None
BOT_ROLE_ID = None
ANYONE_RAID_POST = False
IMAGE_URL = ""
EGG_IMAGE_URL = ""
RAID_CHANNELS = None
EX_RAID_CHANNEL = None
GMAPS_KEY = None
PAYPAL_DONATION_LINK = "https://www.paypal.me/uicraids"

bot = commands.Bot(command_prefix=BOT_PREFIX, case_insensitive=True,
                   description='A bot that manages Pokemon Go Discord communities.')

running_updater = False

reaction_list = ["mystic", "valor", "instinct", "1⃣", "2⃣", "3⃣", "❌", "✅", "🖍"]#, "🔃"]


async def raid_purge(channel, after=None):
    return await channel.purge(after=after)


def scheduled_purge(loop):
    global bot
    # Purge messages from the last 2 days
    after = datetime.now() - timedelta(days=2)
    for channel_id in RAID_CHANNELS:
        channel = bot.get_channel(int(channel_id))
        loop.create_task(raid_purge(channel, after))
        time.sleep(0.01)


@bot.event
@asyncio.coroutine
async def on_ready():
    global running_updater

    printr(discord.version_info)
    printr('Logged in as: {}'.format(bot.user.name))
    printr('Bot ID: {}'.format(bot.user.id))
    printr('Raid Role ID: {}'.format(RAID_ROLE_ID))
    printr("Mod Role ID: {}".format(MOD_ROLE_ID))
    printr("Image URL: {}".format(IMAGE_URL))
    printr("Ex-Raid Channel: {}".format(EX_RAID_CHANNEL))
    printr("GMaps Key: {}...".format(GMAPS_KEY[:10]))
    printr('------')

    loop = asyncio.get_event_loop()
    schedule.every().day.at("00:01").do(scheduled_purge, loop=loop)

    # Start a new continuous run thread.
    schedule.run_continuously(0)
    # Allow a small time for separate thread to register time stamps.
    time.sleep(0.001)

@bot.event
# Payload( PartialEmoji, Message_id, Channel_id, User_id)
async def on_raw_reaction_add(*payload):
    m_payload = payload[0]
    try:
        emoji = m_payload.emoji
        mid = m_payload.message_id
        channel = bot.get_channel(m_payload.channel_id)
        user = channel.guild.get_member(m_payload.user_id) if channel else bot.get_user(m_payload.user_id)
    except AttributeError:
        printr("Attribute not found")
        return

    if not channel or (emoji and emoji.name not in reaction_list):
        return
    try:
        message = await channel.fetch_message(mid)
        if message:
            await on_reaction_add(message, emoji, user)
    except discord.NotFound:
        printr("Message {} not found".format(mid))


@bot.event
# Payload( PartialEmoji, Message_id, Channel_id, User_id)
async def on_raw_reaction_remove(*payload):
    m_payload = payload[0]
    try:
        emoji = m_payload.emoji
        mid = m_payload.message_id
        channel = bot.get_channel(m_payload.channel_id)
        user = channel.guild.get_member(m_payload.user_id) if channel else bot.get_user(m_payload.user_id)
    except AttributeError:
        printr("Attribute not found")
        return

    if emoji and emoji.name not in reaction_list:
        return

    if not channel:
        return
    try:
        message = await channel.fetch_message(mid)
        if message:
            await on_reaction_remove(message, emoji, user)
    except discord.NotFound:
        printr("Message id {} not found".format(mid))


async def on_reaction_add(message, emoji, user):
    def confirm(m):
        if m.author == user:
            return True
        return False

    channel = message.channel
    if user == bot.user or message.author != bot.user or \
            not message.embeds:
        return
    loc = get_field_by_name(message.embeds[0].fields, "Location")
    loc = loc.value if loc else "Unknown"
    if emoji.name == "❌":
        if check_roles(user, MOD_ROLE_ID) or \
                message.embeds[0].author == user.name:
            ask = await channel.send("{} are you sure you would like to "
                                     "delete raid *{}*? (yes/ignore)"
                                     .format(user.mention, loc))
            try:
                msg = await bot.wait_for("message", timeout=45.0, check=confirm)
                if msg.content.lower().startswith("y"):
                    printr("Raid {} deleted by user {}".format(loc, user.name))
                    await channel.send("Raid **{}** deleted by {}"
                                       .format(loc, user.mention),
                                       delete_after=20.0)
                    await message.delete()
                    await ask.delete()
                    await msg.delete()
                    return
                else:
                    await message.remove_reaction(emoji, user)
                    await ask.delete()
            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                await ask.delete()
        return
    if emoji.name == "🖍":
        if message.embeds[0].author == user.name or \
                check_roles(user, MOD_ROLE_ID) or \
                check_roles(user, RAID_ROLE_ID):

            print("ask")

            ask = await channel.send("{}, edit raid at {}? (delete, pokemon, "
                                     "location, time, role, cancel)"
                                     .format(user.mention, loc))
            try:
                msg = await bot.wait_for("message", timeout=30.0, check=confirm)
                if msg.content.lower().startswith("del"):    # delete post
                    printr("Raid {} deleted by user {}".format(loc, user.name))
                    await channel.send("Raid **{}** deleted by {}"
                                       .format(loc, user.mention),
                                       delete_after=20.0)
                    await message.delete()
                elif msg.content.lower().startswith("p"):    # change pokemon
                    if " " in msg.content:
                        pkmn = msg.content.split(' ', 1)[1].strip()
                        await editraidpokemon(message, pkmn)
                        location = get_field_by_name(message.embeds[0].fields,
                                                  "Location:")
                        loc = location.value if location else "Unknown"
                        await channel.send("Updated Raid at *{}* to **{}**"
                                           .format(loc, pkmn))
                    else:
                        await channel.send("{}, unable to process pokemon!"
                                           .format(user.mention),
                                           delete_after=20.0)
                elif msg.content.lower().startswith("l"):  # change location
                    if " " in msg.content:
                        loc = msg.content.split(' ', 1)[1].strip()
                        location = get_field_by_name(message.embeds[0].fields,
                                                  "Location:")
                        await editraidlocation(message, loc)
                        await channel.send(
                            "Updated Raid at {} to **{}**"
                            .format(location.value if location else "Unknown",
                                    loc))
                    else:
                        await channel.send("{}, unable to process location!"
                                           .format(user.mention),
                                           delete_after=20.0)
                elif msg.content.lower().startswith("t"):  # change time
                    if " " in msg.content:
                        timer = msg.content.split(' ', 1)[1]
                        await editraidtime(message, timer)
                        location = get_field_by_name(message.embeds[0].fields,
                                                  "Location:")
                        await channel.send(
                            "Updated Raid at *{}* to time: **{}**"
                            .format(location.value if location else "Unknown",
                                    timer))
                    else:
                        await channel.send("{}, unable to process time!"
                                           .format(user.mention),
                                           delete_after=30.0)
                    await message.remove_reaction(emoji, user)
                elif msg.content.lower().startswith("r"):  # change role
                    printr("Edit role")
                    if not check_footer(message, "ex-"):
                        await channel.send("{}, not an Ex-raid, "
                                           "cannot change role."
                                           .format(user.mention),
                                           delete_after=20.0)
                    elif " " in msg.content:
                        role = msg.content.split(' ', 1)[1]
                        printr(role)
                        await editraidrole(message, role)
                        location = get_field_by_name(message.embeds[0].fields,
                                                  "Location:")
                        await channel.send(
                            "Updated Raid at *{}* to role: **{}**"
                            .format(location.value if location else "Unknown",
                                    role))
                    else:
                        await channel.send("{}, unable to process role!"
                                           .format(user.mention),
                                           delete_after=30.0)
                else:
                    await channel.send("{}, I do not understand that option."
                                       .format(user.mention), delete_after=20.0)
                await ask.delete()
                await msg.delete()
                await message.remove_reaction(emoji, user)
                return
            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                await channel.send("{} response timed out. Try again."
                                   .format(user.mention), delete_after=20.0)
                await ask.delete()
                return
    if emoji.name == "🔃":
        if message.embeds[0].author == user.name or \
                check_roles(user, MOD_ROLE_ID) or \
                check_roles(user, RAID_ROLE_ID):
            try:

                await message.remove_reaction(emoji, user)
                return
            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                await channel.send("{} response timed out. Try again."
                                   .format(user.mention), delete_after=20.0)
                return

    if message.embeds and check_footer(message, "raid"):
        printr("notifying raid {}: {}".format(loc, user.name))
        await notify_raid(message)
        if isinstance(emoji, str):
            await message.channel.send(
                "{} is bringing +{} to raid {}".format(
                    user.name, emoji, loc))
        return

    if message.embeds and check_footer(message, "ex-raid"):
        printr("notifying exraid {}: {}".format(loc, user.name))
        await notify_exraid(message)
        if isinstance(emoji, str):
            await message.channel.send(
                "{} is bringing +{} to ex-raid *{}*".format(
                    user.name, emoji, loc))
        return


async def on_reaction_remove(message, emoji, user):
    if user == bot.user and not message.embeds:
        return
    loc = get_field_by_name(message.embeds[0].fields, "Location")
    if loc:
        loc = loc.value
    else:
        loc = "Unknown"
    if emoji.name == "❌" or emoji.name == "🖍" or emoji.name == "🔃" or \
            emoji.name not in reaction_list:
        return
    if check_footer(message, "raid"):
        printr("Notifying raid: User {} has left {} with {}"
               .format(user.name, loc, emoji.name))
        await notify_raid(message)
    if check_footer(message, "ex-raid"):
        role_name = message.embeds[0].footer.text.split(":", 1)
        if role_name and len(role_name) > 1:
            role_name = role_name[1].strip()
        else:
            role_name = None
        if role_name and \
                not isinstance(emoji, str):
            for role in user.roles:
                if role.name == role_name:
                    await user.remove_roles(role)
                    await message.channel.send(
                        "{} you have left *{}*".format(user.mention, role_name),
                        delete_after=10)
        printr("Notifying Ex-raid: User {} has left {}".format(user.name, loc))
        await notify_exraid(message)
        await asyncio.sleep(0.1)


@bot.command(pass_context=True)
async def info(ctx):
    embed = discord.Embed(title="PoGo Bot",
                          description="Pokemon Go Discord Bot.",
                          color=0xeee657)
    # give info about you here
    embed.add_field(name="Author", value="D4rKngh7")
    # Shows the number of servers the bot is member of.
    embed.add_field(name="Server count", value="{}".format(len(bot.guilds)))
    # give users a link to invite this bot to their server
    embed.add_field(name="Invite",
                    value="No Invite. This bot must be self-hosted")
    await ctx.send(embed=embed)


@bot.command(aliases=[],
             brief="Send BEAST message",
             pass_context=True)
async def beast(ctx):
    embed = discord.Embed(title=":regional_indicator_b: :regional_indicator_e: "
                                ":regional_indicator_a: :regional_indicator_s: "
                                ":regional_indicator_t:")
    embed.set_author(name=ctx.message.author.name)
    await ctx.send(embed=embed)
    await ctx.message.delete()


@bot.command(aliases=["clr"],
             brief="[MOD] Clear all members from role. !clearrole [role_name]",
             pass_context=True)
async def clearrole(ctx, rolex=None):
    if not await checkmod(ctx, MOD_ROLE_ID):
        return
    if not rolex:
        cname = ctx.message.channel.name
        for role in ctx.message.guild.roles:
            if cname.lower() == role.name.lower():
                rolex = cname
        if not rolex:
            await ctx.send("No role specified!", delete_after=20.0)
            await ctx.message.delete()
            return
    members = bot.get_all_members()
    count = 0
    for member in members:
        for role in member.roles:
            if role.name.lower() == rolex.lower():
                printr("Found member {} with role {}".format(member.name,
                                                             role.name))
                await member.remove_roles(role)
                count += 1

    await ctx.send(
        "Cleared {} members from role {}".format(count, rolex), delete_after=5)
    await asyncio.sleep(0.1)
    await ctx.message.delete()


@bot.command(aliases=[],
             brief="[MOD] Purge messages from channel. !purge [pinned]",
             pass_context=True)
async def purge(ctx, pinned=False, limit=100, after=None):
    def notpinned(message):
        return not message.pinned

    def confirm(m):
        if m.author == ctx.message.author:
            return True
        return False

    if await checkmod(ctx, MOD_ROLE_ID):
        ask = await ctx.send("Are you sure you would like to clear the last 100"
                             " messages? (yes/no)")
        try:
            msg = await bot.wait_for("message", timeout=30.0, check=confirm)
        except asyncio.TimeoutError:
            await ctx.message.delete()
            await ask.delete()
            return

        channel = ctx.message.channel
        if after:
            after = datetime.now() - timedelta(days=int(after))

        try:
            if msg.content.lower().startswith("y"):
                await ask.delete()
                await msg.delete()
                await channel.purge(limit=limit, check=notpinned if not pinned else None, after=after)
                time.sleep(0.01)
                print("Purge Complete")
            else:
                await ctx.send("Purge canceled.", delete_after=10.0)
                await ask.delete()
                await msg.delete()
                await ctx.message.delete()
        except Exception:
            print("Unexpected error:", sys.exc_info()[0])

@bot.command(aliases=[],
             brief="Messages the donation link",
             pass_context=True)
async def donate(ctx):
    await ctx.send("You can donate by Paypal at {}"
                   .format(PAYPAL_DONATION_LINK))
    await ctx.message.delete()


@bot.command(aliases=["sex"],
             brief="[MOD] Manually scan channel for ex-raid posts. !scanex ",
             pass_context=True)
async def scanex(ctx):
    if not await checkmod(ctx, MOD_ROLE_ID):
        return

    await manualexscan(ctx.message.channel)
    await ctx.send("Scan completed", delete_after=10)
    await ctx.message.delete()


@bot.command(aliases=["exu"],
             brief="[MOD] Continuously update ex-raid channel manually. "
                   "!exupdater [minutes]",
             pass_context=True)
async def exupdater(ctx, minutes=5):
    global running_updater
    if not await checkmod(ctx,MOD_ROLE_ID):
        return

    ctx.message.delete()

    if minutes > 0:
        running_updater = True
        await ctx.send("Scanning every {} minutes.".format(minutes),
                       delete_after=10)
    else:
        running_updater = False
        return

    await exupdaterloop(ctx.message.channel, minutes)


@bot.command(aliases=["eo"],
             brief="[MOD] Send message tagging @everyone "
                   "!everyone [message]",
             pass_context=True)
async def everyone(ctx, *, message):
    await ctx.send("@everyone {}".format(message))
    await ctx.message.delete()


async def exupdaterloop(channel, minutes):
    while running_updater:
        await manualexscan(channel)
        await asyncio.sleep(minutes * 60)

    await channel.send("exupdater stopped", delete_after=60)


async def manualexscan(channel):
    try:
        async for msg in channel.history(limit=500):
            if msg.author != bot.user:
                continue
            if msg.embeds and msg.embeds[0].footer and \
                    msg.embeds[0].footer.text.startswith("ex-"):
                await notify_exraid(msg)
    except:
        pass


@bot.command(aliases=[],
             brief="[MOD] Clear raid posts from channel. !clearraids",
             pass_context=True)
async def clearraids(ctx):
    def raid(msg):
        return msg.author == bot.user and check_footer(msg, "raid")

    if not await checkmod(ctx,MOD_ROLE_ID):
        return
    await ctx.message.channel.purge(limit=500, check=raid)
    await ctx.send("Cleared all raid posts", delete_after=10)


@bot.command(aliases=["rg"],
             brief="[MOD] Reload gyms from file. !reloadgyms",
             pass_context=True)
async def reloadgyms(ctx):
    if os.path.exists('gyms.json'):
        try:
            load_gyms('gyms.json')
            await ctx.send("Gyms successfully loaded!", delete_after=30.0)
        except:
            await ctx.send("There was an issue reloading the gyms!",
                           delete_after=30.0)
    else:
        ctx.send("gyms.json does not exist!", delete_after=30.0)
    ctx.message.delete()


@bot.command(aliases=["r"],
             usage="!raid [pokemon] [location] [time]",
             help="Create a new raid posting. Users will also be listed in "
                  "the post by team. Press 1, 2, or 3 to specify other teamless"
                  "guests that will accompany you.",
             brief="Create a new raid post. !raid <pkmn> <location> <time>",
             pass_context=True)
async def raid(ctx, pkmn, *, locationtime):

    if not ANYONE_RAID_POST or not check_roles(ctx.message.author, RAID_ROLE_ID):
        await ctx.send("{}, you are not allowed to post raids."
                       .format(ctx.message.author.mention), delete_after=10.0)
        await ctx.message.delete()
        return

    lt = locationtime.rsplit(" ", 1)
    if len(lt) > 1:
        if re.search(r'[0-9]', str(lt[-1])):
            timer = lt[1].strip()
            location =  lt[0].strip()
        else:
            location = locationtime.strip()
            timer = "Unset"
    else:
        location = locationtime.strip()
        timer = "Unset"

    location = string.capwords(location)

    async for msg in ctx.message.channel.history():
        if msg.author == bot.user and msg.embeds:
            loc = get_field_by_name(msg.embeds[0].fields, "Location")
            if loc and location.lower() == loc.value.lower() and pkmn.lower() \
                    in msg.embeds[0].title.lower():
                if (datetime.utcnow() - msg.created_at) < \
                        timedelta(minutes=30):
                    await ctx.send("Raid at {} already exists, please use "
                                   "previous post".format(loc.value),
                                   delete_after=10.0)
                    await ctx.message.delete()
                    return

    thumb = None
    descrip = ""
    match = pokemon_match(pkmn)
    name = ""
    if match:
        pkmn = match
    pkmn = string.capwords(pkmn, "-")
    pid = get_pokemon_id_from_name(pkmn.lower())
    if pid:
        if IMAGE_URL:
            thumb = IMAGE_URL.format(pid[:-1])
        mincp20, maxcp20 = get_cp_range(pid, 20)
        mincp25, maxcp25 = get_cp_range(pid, 25)
        name = get_name(pid, pkmn)

        descrip = "CP: ({}-{})\nWB: ({}-{})".format(mincp20, maxcp20,
                                                    mincp25, maxcp25)
    else:
        printr("Pokemon id not found for {}".format(pkmn))

    embed = discord.Embed(title="Raid - {}".format(name),
                          description=descrip)
    embed.set_author(name=ctx.message.author.name)
    if thumb:
        embed.set_thumbnail(url=thumb)
    coords = get_gym_coords(location)
    map_image = None
    map_dir = None
    if coords and GMAPS_KEY:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        if map_image is not None:
            embed.set_image(url=map_image)
        map_dir = get_map_dir_url(coords[0], coords[1])

    embed.add_field(name="Location:", value=location, inline=True)
    embed.add_field(name="Proposed Time:", value=timer + "\n", inline=True)
    embed.add_field(name="** **", value="** **", inline=False)
    embed.add_field(name=str(getEmoji("mystic")) + "__Mystic (0)__", value="[]",
                    inline=True)
    embed.add_field(name=str(getEmoji("valor")) + "__Valor (0)__", value="[]",
                    inline=True)
    embed.add_field(name=str(getEmoji("instinct")) + "__Instinct (0)__",
                    value="[]", inline=True)
    embed.add_field(name="**Total:**", value="0", inline=False)

    if map_dir is not None:
        embed.add_field(name="**Directions**", value="[Map Link](" + map_dir + ")", inline=False)

    embed.set_footer(text="raid")
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(0.1)
    await ctx.message.delete()
    await msg.pin()
    await msg.add_reaction(getEmoji("mystic"))
    await asyncio.sleep(0.1)
    await msg.add_reaction(getEmoji("valor"))
    await asyncio.sleep(0.1)
    await msg.add_reaction(getEmoji("instinct"))
    await asyncio.sleep(0.1)
    await msg.add_reaction("✅")
    await asyncio.sleep(0.1)
    await msg.add_reaction("1⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("2⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("3⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("🖍")
    await asyncio.sleep(0.1)
    await msg.add_reaction("🔃")
    await asyncio.sleep(0.1)

    await asyncio.sleep(7200)
    await msg.unpin()


async def editraidlocation(msg, location):
    for i in range(0, len(msg.embeds[0].fields)):
        field2 = msg.embeds[0].fields[i]
        if "Location:" in field2.name:
            location = string.capwords(location)
            msg.embeds[0].set_field_at(i, name=field2.name, value=location,
                                       inline=True)
            coords = get_gym_coords(location)
            if coords and GMAPS_KEY:
                map_image = get_static_map_url(coords[0], coords[1],
                                               api_key=GMAPS_KEY)
                msg.embeds[0].set_image(url=map_image)
            await msg.edit(embed=msg.embeds[0])
            return True
    return False


@bot.command(aliases=["re"],
             usage="!raidegg [level] [location] [hatch_time]",
             help="Create a new raid egg posting. Users will also be listed in "
                  "the post by team. Press 1, 2, or 3 to specify other teammate"
                  " guests that will accompany you.",
             brief="Create a new raid post. !raidegg <pkmn> <location> <time>",
             pass_context=True)
async def raidegg(ctx, level, *, locationtime):
    if not ANYONE_RAID_POST or not check_roles(ctx.message.author, RAID_ROLE_ID):
        await ctx.send("{}, you are not allowed to post raids."
                       .format(ctx.message.author.mention), delete_after=10.0)
        await ctx.message.delete()
        return

    lt = locationtime.rsplit(" ", 1)
    if len(lt) > 1:
        if re.search(r'[0-9]', str(lt[-1])):
            location = lt[0].strip()
            timer = lt[1].strip()
        else:
            location = locationtime.strip()
            timer = "Unset"
    else:
        location = locationtime.strip()
        timer = "Unset"

    location = string.capwords(location)

    async for msg in ctx.message.channel.history():
        if msg.author == bot.user and msg.embeds:
            loc = get_field_by_name(msg.embeds[0].fields, "Location")
            if loc and location.lower() == loc.value.lower() and level.lower() \
                    in msg.embeds[0].title.lower():
                if (datetime.utcnow() - msg.created_at) < \
                        timedelta(minutes=30):
                    await ctx.send("Raid at {} already exists, please use "
                                   "previous post".format(loc.value),
                                   delete_after=10.0)
                    await ctx.message.delete()
                    return

    thumb = None
    descrip = ""
    if EGG_IMAGE_URL:
        thumb = EGG_IMAGE_URL.format(level.upper())
    embed = discord.Embed(title="Raid Egg - Level {}".format(level),
                          description=descrip)
    embed.set_author(name=ctx.message.author.name)
    if thumb:
        embed.set_thumbnail(url=thumb)
    coords = get_gym_coords(location)
    if coords and GMAPS_KEY:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        embed.set_image(url=map_image)
    embed.add_field(name="Location:", value=location, inline=True)
    embed.add_field(name="Hatch Time:", value=timer + "\n", inline=True)
    embed.add_field(name="** **", value="** **", inline=False)
    embed.add_field(name=str(getEmoji("mystic")) + "__Mystic (0)__", value="[]",
                    inline=True)
    embed.add_field(name=str(getEmoji("valor")) + "__Valor (0)__", value="[]",
                    inline=True)
    embed.add_field(name=str(getEmoji("instinct")) + "__Instinct (0)__",
                    value="[]", inline=True)
    embed.add_field(name="**Total:**", value="0", inline=False)
    embed.set_footer(text="raid")
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(0.1)
    await ctx.message.delete()
    await msg.pin()
    await msg.add_reaction(getEmoji("mystic"))
    await asyncio.sleep(0.1)
    await msg.add_reaction(getEmoji("valor"))
    await asyncio.sleep(0.1)
    await msg.add_reaction(getEmoji("instinct"))
    await asyncio.sleep(0.1)
    await msg.add_reaction("✅")
    await asyncio.sleep(0.1)
    await msg.add_reaction("1⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("2⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("3⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("🖍")
    await asyncio.sleep(7200)
    await msg.unpin()

@bot.command(aliases=["rt"],
             usage="!raidtime [location] [time]",
             brief="Edit the time on a previous raid post. "
                   "!raidtime <location> <time>",
             pass_context=True)
async def raidtime(ctx, loc, timer=None):
    async for msg in ctx.message.channel.history():
        if msg.author != bot.user or not msg.embeds:
            continue
        for field in msg.embeds[0].fields:
            if field.name.startswith("Location") and \
                    loc.lower() in field.value.lower():
                if ctx.message.author.name != msg.embeds[
                    0].author.name and not check_roles(ctx.message.author,
                                                       RAID_ROLE_ID):
                    await ctx.send("You cannot edit this raid post. "
                                   "Only the original poster can.",
                                   delete_after=20.0)
                    await ctx.message.delete()
                    return
                if timer:
                    await editraidtime(msg, timer)
                    await ctx.send(
                        "Updated Raid at *{}* to time: **{}**"
                        .format(field.value, timer))
                    await ctx.message.delete()
                    return
                else:
                    total = get_field_by_name(msg.embeds[0].fields, "Total")
                    total = total.value if total else 0
                    time = get_field_by_name(msg.embeds[0].fields, "Time:") or \
                           get_field_by_name(msg.embeds[0].fields, "Date:")
                    await ctx.send(
                        "Raid at **{}** at time: **{}** has  **{} ** "
                        "people registered."
                        .format(field.value, time.value, total))
                    await ctx.message.delete()
                    return
    await ctx.message.delete()
    await ctx.send("Unable to find Raid at {}".format(loc), delete_after=30)


async def editraidtime(msg, timer):
    for i in range(0, len(msg.embeds[0].fields)):
        field2 = msg.embeds[0].fields[i]
        if "Time:" in field2.name or \
                field2.name.startswith("Date:"):
            if timer:
                if "Date:" in field2.name:
                    fname = "Date:"
                else:
                    fname = "Proposed Time:"
                msg.embeds[0].set_field_at(i, name=fname,
                                           value=timer,
                                           inline=True)
                await msg.edit(embed=msg.embeds[0])
                return True
    return False

@bot.command(aliases=["rp"],
             usage="!raidpokemon [location] [pokemon]",
             brief="Edit the pokemon on a previous raid post. "
                   "!raidpokemon <location> <pokemon>",
             pass_context=True)
async def raidpokemon(ctx, loc, pkmn):

    async for msg in ctx.message.channel.history():
        if msg.author != bot.user or not msg.embeds:
            continue
        for field in msg.embeds[0].fields:
            if field.name.startswith("Location") and \
                    loc.lower() in field.value.lower():
                if ctx.message.author.name != msg.embeds[
                    0].author.name and not check_roles(ctx.message.author,
                                                       RAID_ROLE_ID):
                    await ctx.send("You cannot edit this raid post. "
                                   "Only the original poster can.",
                                   delete_after=20.0)
                    await ctx.message.delete()
                    return
                await editraidpokemon(msg, pkmn)
                await ctx.send("Raid at **{}** updated to **{}**"
                               .format(field.value, pkmn))
                await ctx.message.delete()
                return
    await ctx.message.delete()
    await ctx.send("Unable to find Raid at {}".format(loc), delete_after=30)


async def editraidpokemon(msg, pkmn):
    descrip = msg.embeds[0].description
    match = pokemon_match(pkmn)
    if match:
        pkmn = match
    pkmn = string.capwords(pkmn, "-")
    pid = get_pokemon_id_from_name(pkmn.lower())
    if pid:
        if IMAGE_URL:
            thumb = IMAGE_URL.format(pid)
            msg.embeds[0].set_thumbnail(url=thumb)
        mincp20, maxcp20 = get_cp_range(pid, 20)
        mincp25, maxcp25 = get_cp_range(pid, 25)

        descrip = "CP: ({}-{})\nWB: ({}-{})".format(mincp20, maxcp20,
                                                    mincp25, maxcp25)
    else:
        printr("Pokemon id not found for {}".format(pkmn))
        msg.embeds[0].set_thumbnail(None)
    if check_footer(msg, "raid"):
        msg.embeds[0].title = "Raid - {}".format(pkmn)
    elif check_footer(msg, "ex-raid"):
        msg.embeds[0].title = "Ex-Raid - {}".format(pkmn)
    msg.embeds[0].description = descrip
    await msg.edit(embed=msg.embeds[0])
    return True

@bot.command(aliases=["rm"],
             usage="!raidmessage [location] [msg]",
             brief="Message members in raid "
                   "!raidmessage <location> <msg>",
             pass_context=True)
async def raidmessage(ctx, loc, *, message):

    async for msg in ctx.message.channel.history(limit=1000):
        if msg.author != bot.user or not msg.embeds:
            continue
        for field in msg.embeds[0].fields:
            if field.name.startswith("Location") and \
                    loc.lower() in field.value.lower():
                registered = []
                for reaction in msg.reactions:
                    async for user in reaction.users():
                        if user == bot.user:
                            continue
                        if user.mention not in registered:
                            registered.append(user)
                auth = ctx.message.author
                if auth not in registered and \
                        not check_roles(auth, RAID_ROLE_ID) and \
                        msg.embeds[0].author.name != auth.name:
                    await ctx.send("You are not involved with this raid.",
                                   delete_after=10.0)
                    await ctx.msg.delete()
                    return
                await ctx.send("".join(map(lambda u: u.mention, registered)) +
                               " " + message)
                await ctx.message.delete()
                return
        await ctx.send("Cannot find raid *{}*".format(loc), delete_after=10.0)
        await ctx.message.delete()


@bot.command(aliases=["rc"],
             usage="!raidcoords [location] [latitude] [longitude]",
             brief="Set raid coordinates to display map"
                   "!raidcoords <location> <latitude> <longitude>",
             pass_context=True)
async def raidcoords(ctx, loc, *, coords):

    if coords.lower() != "reset":
        coords = coords.replace(",", " ").replace("  ", " ").split(" ")
        if len(coords) > 2 or len(coords) < 2:
            await ctx.send("Unable to process coordinates.", delete_after=10.0)
            await ctx.message.delete()
            return
    async for msg in ctx.message.channel.history():
        if msg.author != bot.user or not msg.embeds:
            continue
        for field in msg.embeds[0].fields:
            if field.name.startswith("Location") and \
                    loc.lower() in field.value.lower():
                if msg.embeds[0].author.name != ctx.message.author.name and \
                        not check_roles(ctx.message.author, RAID_ROLE_ID):
                    await ctx.send("You cannot set coordinates for this raid!",
                                   delete_after=10.0)
                    await ctx.message.delete()
                    return
                if coords == "reset":
                    msg.embeds[0].set_image(url=None)
                    await msg.edit(embed=msg.embeds[0])
                    await ctx.send("Raid {} updated, coords reset."
                                   .format(field.value), delete_after=10.0)
                    await ctx.message.delete()
                    return
                if check_footer(msg, "raid"):
                    await notify_raid(msg, coords)
                    await ctx.send("Raid {} updated to coords: ({},{})"
                                   .format(field.value, coords[0], coords[1]),
                                   delete_after=10.0)
                    await ctx.message.delete()
                    return
                elif check_footer(msg, "ex-raid"):
                    await notify_exraid(msg, coords)
                    await ctx.send("Ex-Raid {} updated to coords: ({},{})"
                                   .format(field.value, coords[0], coords[1]),
                                   delete_after=10.0)
                    await ctx.message.delete()
                    return

    await ctx.send("Cannot find raid *{}*".format(loc), delete_after=10.0)
    await ctx.message.delete()


@bot.command(aliases=["ex"],
             name="exraid",
             brief="Create a new Ex-Raid post. !exraid <pkmn> <location>"
                   " <data> <role>",
             help="Create a new Ex-Raid post. Reactions to the post will add"
                  " the user to the provided role. Users will also be listed in"
                  " the post by team. Press 1, 2, or 3 to specify other "
                  "teamless guests.",
             usage="!exraid [pokemon] [location] [date] [role]",
             pass_context=True)
async def exraid(ctx, pkmn, location, date, role="ex-raid"):

    if not check_roles(ctx.message.author, RAID_ROLE_ID):
        await ctx.send("{}, you are not allowed to post ex-raids."
                       .format(ctx.message.author.mention), delete_after=10.0)
        await ctx.message.delete()
        return

    thumb = None
    descrip = ""

    pkmn = string.capwords(pkmn, '-')
    pid = get_pokemon_id_from_name(pkmn.lower())
    if pid:
        if IMAGE_URL:
            thumb = IMAGE_URL.format(pid)

        mincp20, maxcp20 = get_cp_range(pid, 20)
        mincp25, maxcp25 = get_cp_range(pid, 25)

        descrip = "CP: ({}-{})\nWB: ({}-{})".format(mincp20, maxcp20,
                                                    mincp25, maxcp25)
    else:
        printr("Pokemon id not found for {}".format(pkmn))

    embed = discord.Embed(title="EX-Raid - {}".format(pkmn),
                          description=descrip)
    coords = get_gym_coords(location)
    if coords and GMAPS_KEY:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        embed.set_image(url=map_image)
    if thumb:
        embed.set_thumbnail(url=thumb)
    embed.add_field(name="Location:", value=location, inline=True)
    embed.add_field(name="Date:", value=date + "\n", inline=True)
    embed.add_field(name="** **", value="** **", inline=False)
    embed.add_field(name=str(getEmoji("mystic")) + "__Mystic (0)__",
                    value="[]",
                    inline=True)
    embed.add_field(name=str(getEmoji("valor")) + "__Valor (0)__", value="[]",
                    inline=True)
    embed.add_field(name=str(getEmoji("instinct")) + "__Instinct (0)__",
                    value="[]", inline=True)
    embed.add_field(name="Total:", value="0", inline=False)
    embed.set_footer(text="ex-raid: {}".format(role))
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(0.25)
    await ctx.message.delete()
    await msg.pin()
    await msg.add_reaction(getEmoji("mystic"))
    await asyncio.sleep(0.25)
    await msg.add_reaction(getEmoji("valor"))
    await asyncio.sleep(0.25)
    await msg.add_reaction(getEmoji("instinct"))
    await asyncio.sleep(0.25)
    await msg.add_reaction("1⃣")
    await asyncio.sleep(0.25)
    await msg.add_reaction("2⃣")
    await asyncio.sleep(0.25)
    await msg.add_reaction("3⃣")
    await asyncio.sleep(0.25)
    await msg.add_reaction("🖍")


async def editraidrole(message, role):
    if message.embeds and check_footer(message, "ex-"):
        message.embeds[0].set_footer(text="ex-raid: {}".format(role))
        await message.edit(embed=message.embeds[0])
        printr("Ex-raid role changed to: {}".format(role))
        return True
    return False


@bot.command(aliases=["stats"],
             name="getstats",
             brief="Get Stats for a Pokemon. !getstats [pokemon]",
             help="Responds with the pokemon's stats.",
             usage="!getstats [pokemon]",
             pass_context=True)
async def getstats(ctx, pkmn):
    thumb = None
    descrip = ""
    match = pokemon_match(pkmn)
    if match:
        pkmn = match
    pkmn = string.capwords(pkmn, "-")
    pid = get_pokemon_id_from_name(pkmn.lower())
    if pid:
        if IMAGE_URL:
            thumb = IMAGE_URL.format(pid)

        mincp20, maxcp20 = get_cp_range(pid, 20)
        mincp25, maxcp25 = get_cp_range(pid, 25)

        descrip = "CP: ({}-{})\nWB: ({}-{})".format(mincp20, maxcp20,
                                                    mincp25, maxcp25)
    else:
        printr("Pokemon id not found for {}".format(pkmn))
        await ctx.send("{}, could not find Pokemon with name: {}"
                       .format(ctx.message.user.mention, pkmn))
        return

    embed = discord.Embed(title="#{}. {}".format(pid, pkmn),
                          description=descrip)
    types = get_types(pid)
    fval = types[0] + ("/{}".format(types[1]) if types[1] else "")
    embed.add_field(name="Types:", value=fval, inline=False)
    if thumb:
        embed.set_thumbnail(url=thumb)
    await ctx.send("{}, here you go.".format(ctx.message.author.mention))
    await ctx.send(embed=embed)


async def notify_raid(msg, coords=None):
    mystic = ""
    valor = ""
    instinct = ""
    m_tot = 0
    v_tot = 0
    i_tot = 0
    total = 0
    user_guests = {}
    user_ready = {}
    for reaction in msg.reactions:
        if isinstance(reaction.emoji, str):
            if reaction.emoji == "1⃣":
                total += reaction.count - 1
                users = await reaction.users().flatten()
                for user in users:
                    user_guests[user.name] = user_guests.get(user.name, 0) + 1
            elif reaction.emoji == "2⃣":
                total += 2 * (reaction.count - 1)
                users = await reaction.users().flatten()
                for user in users:
                    user_guests[user.name] = user_guests.get(user.name, 0) + 2
            elif reaction.emoji == "3⃣":
                total += 3 * (reaction.count - 1)
                users = await reaction.users().flatten()
                for user in users:
                    user_guests[user.name] = user_guests.get(user.name, 0) + 3
            elif reaction.emoji == "✅":
                users = await reaction.users().flatten()
                for user in users:
                    user_ready[user.name] = "(✓)"
    for reaction in msg.reactions:
        if isinstance(reaction.emoji, str):
            continue
        if reaction.emoji.name == 'mystic':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                guest = ""
                if user.name in user_guests:
                    guest = "+{}".format(user_guests.get(user.name), "")
                mystic += user.name + guest + user_ready.get(user.name, "") \
                    + ", "
                m_tot += 1
                total += 1
            mystic = mystic.rstrip(", ")
        elif reaction.emoji.name == 'valor':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                guest = ""
                if user.name in user_guests:
                    guest = "+{}".format(user_guests.get(user.name), "")
                valor += user.name + guest + user_ready.get(user.name, "") \
                    + ", "
                v_tot += 1
                total += 1
            valor = valor.rstrip(", ")
        elif reaction.emoji.name == 'instinct':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                guest = ""
                if user.name in user_guests:
                    guest = "+{}".format(user_guests.get(user.name), "")
                instinct += user.name + guest + \
                    user_ready.get(user.name, "") + ", "
                i_tot += 1
                total += 1
            instinct = instinct.rstrip(", ")
    mystic = "[{}]".format(mystic)
    valor = "[{}]".format(valor)
    instinct = "[{}]".format(instinct)

    embed = msg.embeds[0]

    if GMAPS_KEY and coords:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        embed.set_image(url=map_image)

    for i in range(0, len(embed.fields)):
        if "Mystic" in embed.fields[i].name:
            embed.set_field_at(i, name=str(
                getEmoji("mystic")) + "__Mystic ({})__".format(m_tot),
                               value=mystic, inline=True)
        if "Valor" in embed.fields[i].name:
            embed.set_field_at(i, name=str(
                getEmoji("valor")) + "__Valor ({})__".format(v_tot),
                               value=valor, inline=True)
        if "Instinct" in embed.fields[i].name:
            msg.embeds[0].set_field_at(i, name=str(
                getEmoji("instinct")) + "__Instinct ({})__".format(i_tot),
                                       value=instinct, inline=True)
        if "Total" in embed.fields[i].name:
            msg.embeds[0].set_field_at(i, name="**Total:**",
                                       value="**{}**".format(total),
                                       inline=False)

    await msg.edit(embed=embed)


async def notify_exraid(msg, coords=None):
    mystic = ""
    valor = ""
    instinct = ""
    m_tot = 0
    v_tot = 0
    i_tot = 0
    total = 0
    role_name = msg.embeds[0].footer.text.split(":", 1)
    if role_name and len(role_name) > 1:
        role_name = role_name[1].strip()
    else:
        role_name = None
    role = None
    if role_name and role_name != "ex-raid":
        role = await get_role_from_name(msg.guild, role_name, True)
    user_guests = {}
    for reaction in msg.reactions:
        if isinstance(reaction.emoji, str):
            if reaction.emoji == "1⃣":
                total += reaction.count - 1
                users = await reaction.users().flatten()
                for user in users:
                    user_guests[user.name] = user_guests.get(user.name, 0) + 1
            elif reaction.emoji == "2⃣":
                total += 2 * (reaction.count - 1)
                users = await reaction.users().flatten()
                for user in users:
                    user_guests[user.name] = user_guests.get(user.name, 0) + 2
            elif reaction.emoji == "3⃣":
                total += 3 * (reaction.count - 1)
                users = await reaction.users().flatten()
                for user in users:
                    user_guests[user.name] = user_guests.get(user.name, 0) + 3
    for reaction in msg.reactions:
        if isinstance(reaction.emoji, str):
            continue
        if reaction.emoji.name == 'mystic':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                if role and role not in user.roles:
                    await user.add_roles(role, atomic=True)
                    printr("User {} added to role {}".format(user.name,
                                                             role_name))
                    await msg.channel.send("{} you have been added to {}".
                                           format(user.name, role_name),
                                           delete_after=30.0)
                guest = "+{}".format(
                    user_guests.get(user.name), 0) if user.name in user_guests \
                    else ""
                mystic += user.name + guest + ", "
                m_tot += 1
                total += 1
            mystic = mystic.rstrip(", ")
        elif reaction.emoji.name == 'valor':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                if role and role not in user.roles:
                    await user.add_roles(role, atomic=True)
                    printr("User {} added to role {}".format(user.name,
                                                             role_name))
                    await msg.channel.send("{} you have been added to {}".
                                           format(user.name, role_name),
                                           delete_after=30.0)
                guest = "+{}".format(
                    user_guests.get(user.name), 0) if user.name in user_guests \
                    else ""
                valor += user.name + guest + ", "
                v_tot += 1
                total += 1
            valor = valor.rstrip(", ")
        elif reaction.emoji.name == 'instinct':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                if role and role not in user.roles:
                    await user.add_roles(role, atomic=True)
                    printr("User {} added to role {}".format(user.name,
                                                             role_name))
                    await msg.channel.send("{} you have been added to {}".
                                           format(user.name, role_name),
                                           delete_after=30.0)
                guest = "+{}".format(
                    user_guests.get(user.name), 0) if user.name in user_guests \
                    else ""
                instinct += user.name + guest + ", "
                i_tot += 1
                total += 1
            instinct = instinct.rstrip(", ")
    mystic = "[{}]".format(mystic)
    valor = "[{}]".format(valor)
    instinct = "[{}]".format(instinct)

    embed = msg.embeds[0]

    if GMAPS_KEY and coords and len(coords) == 2:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        embed.set_image(url=map_image)

    for i in range(0, len(embed.fields)):
        if "Mystic" in embed.fields[i].name:
            embed.set_field_at(i, name=str(
                getEmoji("mystic")) + "__Mystic ({})__".format(m_tot),
                               value=mystic, inline=True)
        if "Valor" in embed.fields[i].name:
            embed.set_field_at(i, name=str(
                getEmoji("valor")) + "__Valor ({})__".format(v_tot),
                               value=valor, inline=True)
        if "Instinct" in embed.fields[i].name:
            msg.embeds[0].set_field_at(i, name=str(
                getEmoji("instinct")) + "__Instinct ({})__".format(i_tot),
                                       value=instinct, inline=True)
        if "Total" in embed.fields[i].name:
            msg.embeds[0].set_field_at(i, name="**Total:**",
                                       value="**{}**".format(total),
                                       inline=False)

    await msg.edit(embed=embed)


async def checkmod(ctx, role):
    if not check_roles(ctx.message.author, role):
        await ctx.send("You must be a mod in order to use " +
                       "this command!", delete_after=10)
        await ctx.message.delete()
        return False
    return True


def getEmoji(name):
    return discord.utils.get(bot.emojis, name=name)


if __name__ == "__main__":]
    path = '/var/opt/PoGo-Bot/'
    os.chdir(path)
    cfg = configparser.ConfigParser()
    cfg.read(path+'config.ini')
    bot.command_prefix = cfg['PoGoBot']['BotPrefix'] or "!"
    MOD_ROLE_ID = cfg['PoGoBot'].get('ModRoleID') or -1
    RAID_ROLE_ID = cfg['PoGoBot'].get('RaidRoleID') or -1
    BOT_ROLE_ID = cfg['PoGoBot'].get('BotRoleID') or -1
    if ',' in str(RAID_ROLE_ID):
        RAID_ROLE_ID = [x.strip() for x in RAID_ROLE_ID.split(",")]

    RAID_CHANNELS = cfg['PoGoBot'].get('RaidChannels') or 0
    if ',' in str(RAID_CHANNELS):
        RAID_CHANNELS = [x.strip() for x in RAID_CHANNELS.split(",")]

    ANYONE_RAID_POST = cfg['PoGoBot'].get('AnyoneRaidPost') or False
    IMAGE_URL = cfg['PoGoBot'].get('ImageURL') or None
    EGG_IMAGE_URL = cfg['PoGoBot'].get('EggImageURL') or None
    EX_RAID_CHANNEL = cfg['PoGoBot'].get('ExRaidChannel') or 0
    GMAPS_KEY = cfg['PoGoBot'].get('GMapsKey') or None    load_locale(os.path.join('locales', '{}.json'
                             .format(cfg['PoGoBot']['Locale'] or 'en')))
    load_base_stats(os.path.join('data', 'base_stats_revised.json'))
    load_cp_multipliers(os.path.join('data', 'cp_multipliers.json'))

    if os.path.exists(path+'gyms.json'):
        load_gyms(path+'gyms.json')

    bot.run(cfg['PoGoBot']['BotToken'])
