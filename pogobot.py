#!/usr/bin/python3
# -*- coding: utf-8 -*-
import re
import string

import discord
import os, sys, traceback
import schedule, time

from discord.ext import commands
from discord.ext.tasks import loop
import asyncio
import configparser
from datetime import datetime, timedelta


from concurrent.futures import CancelledError

from utility import get_field_by_name, check_footer, \
    get_static_map_url, load_locale, load_base_stats, \
    load_cp_multipliers, load_gyms, get_gym_coords, get_cp_range, \
    get_pokemon_id_from_name, printr, pokemon_match, check_roles, get_types, get_name, \
    get_map_dir_url, get_role, checkmod, get_db_stats, parse_weather, write_gyms

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
cease_flag = None

reaction_list = ["mystic", "valor", "instinct", "1⃣", "2⃣", "3⃣", "❌", "✅", "🖍", "🔈", "🥊", '🕹', "🙏", "gauntlet", "biga", "Raid_Emblem",
                 "Mega_Venusaur", "Mega_Blastoise", "Mega_Charizard_X", "Mega_Charizard_Y", "Mega_Pidgeot", "Mega_Houndoom", "Mega_Gengar",
                 "Mega_Abomasnow", "Mega_Ampharos"]
gyms = {}
path = ""


async def raid_purge(channel, after=None):
    try:
        return await channel.purge(after=after)
    except Exception:
        print("Unexpected error:", sys.exc_info()[0])
        traceback.print_exc()


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
    global running_updater, cease_flag

    printr(discord.version_info)
    printr('Logged in as: {}'.format(bot.user.name))
    printr('Bot ID: {}'.format(bot.user.id))
    printr('Raid Role ID: {}'.format(RAID_ROLE_ID))
    printr("Mod Role ID: {}".format(MOD_ROLE_ID))
    printr("Image URL: {}".format(IMAGE_URL))
    printr("Ex-Raid Channel: {}".format(EX_RAID_CHANNEL))
    printr("GMaps Key: {}...".format(GMAPS_KEY[:10]))
    printr('------')

    try:
        scheduler_loop = asyncio.get_event_loop()
        schedule.every().day.at("00:15").do(scheduled_purge, loop=scheduler_loop)

        # Start a new continuous run thread.
        cease_flag = schedule.run_continuously(0)
        # Allow a small time for separate thread to register time stamps.
        time.sleep(0.1)
    except CancelledError:
        print('CancelledError')
        traceback.print_exc()

@bot.event
# Payload( PartialEmoji, Message_id, Channel_id, User_id)
async def on_raw_reaction_add(*payload):
    m_payload = payload[0]
    try:
        emoji = m_payload.emoji
        mid = m_payload.message_id
        channel = bot.get_channel(m_payload.channel_id)
        user = channel.guild.get_member(m_payload.user_id) if channel else bot.get_user(m_payload.user_id)
        if not user:
            user = await channel.guild.fetch_member(m_payload.user_id) if channel else bot.get_user(m_payload.user_id)
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

    if user == bot.user or message.author != bot.user:
        return

    if message.author.bot and emoji.name.find("Mega") > -1:
        return await setup_mega(channel, emoji, message, user)

    if not message.embeds:
        return

    loc = get_field_by_name(message.embeds[0].fields, "**Location")
    loc = loc.value if loc else "Unknown"

    loc = loc.split(" @ ")[0]

    if emoji.name == "❌":
        if check_roles(user, MOD_ROLE_ID) or message.embeds[0].author == user.name:
            ask = await channel.send("{} are you sure you would like to delete raid *{}*? (yes/ignore)".format(user.mention, loc))

            try:
                msg = await bot.wait_for("message", timeout=45.0, check=confirm)
                if msg.content.lower().startswith("y"):
                    printr("Raid {} deleted by user {}".format(loc, user.name))
                    await channel.send("Raid **{}** deleted by {}".format(loc, user.mention),delete_after=20.0)

                    if check_footer(message, "raid-train"):
                        role_name, role = await get_role(message)
                        for member in role.members:
                            await member.remove_roles(role, atomic=True)

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

    elif emoji.name == "🖍":
        if message.embeds[0].author == user.name or check_roles(user, MOD_ROLE_ID) or check_roles(user, RAID_ROLE_ID):

            ask = await channel.send("{}, edit raid at {}? (delete, pokemon, location, time, role, cancel)".format(user.mention, loc), delete_after=60)
            try:
                msg = await bot.wait_for("message", timeout=30.0, check=confirm)
                if msg.content.lower().startswith("del"):    # delete post
                    printr("Raid {} deleted by user {}".format(loc, user.name))
                    await channel.send("Raid **{}** deleted by {}".format(loc, user.mention), delete_after=20.0)
                    await message.delete()
                elif msg.content.lower().startswith("p"):    # change pokemon
                    if " " in msg.content:
                        pkmn = msg.content.split(' ', 1)[1].strip()
                        await editraidpokemon(message, pkmn, user.name)
                        await channel.send("Updated Raid at *{}* to **{}**".format(loc, pkmn))
                    else:
                        await channel.send("{}, unable to process pokemon!".format(user.mention), delete_after=20.0)
                elif msg.content.lower().startswith("l"):  # change location
                    if " " in msg.content:
                        new_loc = msg.content.split(' ', 1)[1].strip()
                        await editraidlocation(message, new_loc)
                        await channel.send("Updated Raid at {} to **{}**".format(loc if loc else "Unknown", new_loc), delete_after=20.0)
                    else:
                        await channel.send("{}, unable to process location!" .format(user.mention), delete_after=20.0)
                elif msg.content.lower().startswith("t"):  # change time
                    if " " in msg.content:
                        timer = msg.content.split(' ', 1)[1]
                        await editraidtime(message, timer)
                        await channel.send("Updated Raid at *{}* to time: **{}**" .format(loc if loc else "Unknown", timer), delete_after=20.0)
                    else:
                        await channel.send("{}, unable to process time!".format(user.mention), delete_after=30.0)
                    await message.remove_reaction(emoji, user)

                elif msg.content.lower().startswith("r"):  # change role
                    printr("Edit role")
                    if not check_footer(message, "ex-"):
                        await channel.send("{}, not an Ex-raid, cannot change role." .format(user.mention), delete_after=20.0)
                    elif " " in msg.content:
                        role = msg.content.split(' ', 1)[1]
                        printr(role)
                        await editraidrole(message, role)
                        # location = get_field_by_name(message.embeds[0].fields, "**Location:")
                        await channel.send("Updated Raid at *{}* to role: **{}**" .format(loc if loc else "Unknown", role), delete_after=20.0)
                    else:
                        await channel.send("{}, unable to process role!" .format(user.mention), delete_after=30.0)
                else:
                    await channel.send("{}, I do not understand that option." .format(user.mention), delete_after=10.0)

                await ask.delete()
                await msg.delete()
                await message.remove_reaction(emoji, user)
                return
            except asyncio.TimeoutError:
                await ask.delete()
                await message.remove_reaction(emoji, user)
                await channel.send("{} response timed out. Try again.".format(user.mention), delete_after=10.0)

                return
    elif emoji.name == "🔈":

        if message.embeds[0].author == user.name or check_roles(user, MOD_ROLE_ID) or check_roles(user, RAID_ROLE_ID):

            ask = await channel.send("{}, message users for {}? (Type message below and hit send.)"
                                     .format(user.mention, loc))
            try:
                msg = await bot.wait_for("message", timeout=30.0, check=confirm)

                await ask.delete()
                await msg.delete()

                await message.remove_reaction(emoji, user)
                await sendraidmessagechannel(loc, channel, msg.content)

                return

            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                await channel.send("{} response timed out. Try again."
                                   .format(user.mention), delete_after=20.0)
                await ask.delete()
                return

    elif emoji.name == 'gauntlet':
        if message.embeds[0].author == user.name or check_roles(user, MOD_ROLE_ID) or check_roles(user, RAID_ROLE_ID):
            try:
                await message.remove_reaction(emoji, user)
                await sendraidmessagechannel(loc, channel, "Hop in at {}".format(loc))
                return
            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                return

    elif emoji.name == 'biga':
        if message.embeds[0].author == user.name or check_roles(user, MOD_ROLE_ID) or check_roles(user, RAID_ROLE_ID):

            try:
                await message.remove_reaction(emoji, user)
                await sendraidmessagechannel(loc, channel, "Hop out at {}".format(loc))
                return
            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                return
    elif emoji.name == 'Raid_Emblem':
        if message.embeds[0].author == user.name or check_roles(user, MOD_ROLE_ID) or check_roles(user, RAID_ROLE_ID):
            try:
                if message.embeds and check_footer(message, "raid"):

                    tloc = get_field_by_name(message.embeds[0].fields, "**Location")

                    await message.remove_reaction(emoji, user)

                    ask = await channel.send("{}, which mega hatched at ({})?".format(user.mention, tloc.value), delete_after=60)
                    # await ask.add_reaction(getEmoji("Mega_Blastoise"))
                    # time.sleep(0.01)
                    # await ask.add_reaction(getEmoji("Mega_Venusaur"))
                    # time.sleep(0.01)
                    await ask.add_reaction(getEmoji("Mega_Charizard_X"))
                    time.sleep(0.01)
                    await ask.add_reaction(getEmoji("Mega_Charizard_Y"))
                    time.sleep(0.01)
                    await ask.add_reaction(getEmoji("Mega_Pidgeot"))
                    time.sleep(0.01)
                    await ask.add_reaction(getEmoji("Mega_Houndoom"))
                    time.sleep(0.01)
                    await ask.add_reaction(getEmoji("Mega_Gengar"))
                    time.sleep(0.01)
                    await ask.add_reaction(getEmoji("Mega_Abomasnow"))
                    time.sleep(0.01)
                    await ask.add_reaction(getEmoji("Mega_Ampharos"))
                    time.sleep(0.01)
                return
            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                return

    if message.embeds and check_footer(message, "raid-train"):
        role_name, role = await get_role(message)

        if role and role not in user.roles:
            await user.add_roles(role, atomic=True)

            if user.dm_channel:
                await user.dm_channel.send("{}, you have been added to {}".format(user.name, role_name))
            else:
                dm = await user.create_dm()
                await dm.send("{}, you have been added to {}".format(user.name, role_name))

        await notify_raid(message)

    if message.embeds and check_footer(message, "raid"):
        await notify_raid(message)


async def on_reaction_remove(message, emoji, user):
    if user == bot.user and not message.embeds:
        return

    if emoji.name == "❌" or emoji.name == "🖍" or emoji.name == "🔈" or emoji.name not in reaction_list:
        return

    if message.embeds and check_footer(message, "raid-train"):
        # printr("notifying exraid {}: {}".format(loc, user.name))
        role_name, role = await get_role(message)

        if role and role in user.roles:
            await user.remove_roles(role, atomic=True)

            if user.dm_channel:
                await user.dm_channel.send("{}, you have been removed from {}".format(user.name, role_name))
            else:
                dm = await user.create_dm()
                await dm.send("{}, you have been removed from {}".format(user.name, role_name))

        await notify_raid(message)

        return

    if check_footer(message, "raid"):
        # printr("Notifying raid: User {} has left {} with {}" .format(user.name, loc, emoji.name))
        await notify_raid(message)

    if check_footer(message, "ex-raid"):
        role_name = message.embeds[0].footer.text.split(":", 1)
        if role_name and len(role_name) > 1:
            role_name = role_name[1].strip()
        else:
            role_name = None
        if role_name and not isinstance(emoji, str):
            for role in user.roles:
                if role.name == role_name:
                    await user.remove_roles(role)
                    await message.channel.send(
                        "{} you have left *{}*".format(user.mention, role_name), delete_after=10)
        # printr("Notifying Ex-raid: User {} has left {}".format(user.name, loc))
        await notify_exraid(message)
        await asyncio.sleep(0.1)


async def setup_raid(ctx, pkmn, loc, timer):

    if not ANYONE_RAID_POST or not check_roles(ctx.message.author, RAID_ROLE_ID):
        await ctx.send("{}, you are not allowed to post raids.".format(ctx.message.author.mention), delete_after=10.0)
        return None

    location = string.capwords(loc)

    async for msg in ctx.message.channel.history(limit=25):
        if msg.author == bot.user and msg.embeds:
            o_loc = get_field_by_name(msg.embeds[0].fields, "**Location")
            if o_loc is None:
                return
            t_loc = o_loc.value.lower().split(" @ ")
            o_old = t_loc[0]
            o_time = t_loc[1]
            if o_loc and location.lower() == o_old and pkmn.lower() in msg.embeds[0].title.lower():
                if o_time == timer:
                    await ctx.send("Raid at {} already exists, please use previous post".format(location), delete_after=10.0)
                    return None

    thumb = None
    descrip = ""
    match = pokemon_match(pkmn)
    name = ""

    if match:
        pkmn = match
    pkmn = string.capwords(pkmn, "-")
    pid = get_pokemon_id_from_name(pkmn.lower())
    weather = []
    if pid:
        stats = await get_db_stats(str(pid)[:-1])
        if stats and stats["weatherInfluences"]:
            for i in range(0, len(stats["weatherInfluences"])):
                emoji = parse_weather(stats["weatherInfluences"][i])
                weather.append(emoji)

        if IMAGE_URL:
            thumb = IMAGE_URL.format(pid)

        mincp20, maxcp20 = get_cp_range(pid, 20)
        mincp25, maxcp25 = get_cp_range(pid, 25)
        name = get_name(pid, pkmn)

        if len(weather) > 1:
            descrip = "**CP**: {}-{} \u200a \u200a {}{}: {}-{}".format(mincp20, maxcp20, weather[0], weather[1], mincp25, maxcp25)
        elif len(weather) > 0:
            descrip = "**CP**: {}-{} \u200a \u200a {}: {}-{}".format(mincp20, maxcp20, weather[0], mincp25, maxcp25)
        else:
            descrip = "**CP**: {}-{} \u200a \u200a WB: {}-{}".format(mincp20, maxcp20, mincp25, maxcp25)

    else:
        printr("Pokemon id not found for {}".format(pkmn))

    embed = discord.Embed(title="Raid - {} ({})".format(name, ctx.message.author.name), description=descrip)

    if thumb:
        embed.set_thumbnail(url=thumb)

    coords = get_gym_coords(location)
    map_dir = None

    if coords and GMAPS_KEY:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        if map_image is not None:
            embed.set_image(url=map_image)
        map_dir = get_map_dir_url(coords[0], coords[1])

    mystic = str(getEmoji("mystic")) + "__Mystic (0)__"
    valor = str(getEmoji("valor")) + "__Valor (0)__"
    instinct = str(getEmoji("instinct")) + "__Instinct (0)__"

    header_space = " ".join(["\u200a" for i in range(0, 20)])
    value_space = " ".join(["\u200a" for i in range(0, 28)])
    total_field = "**Total:**" + header_space + "**Remote:**"
    total_value = "**{}**".format(0) + value_space + "**{}**".format(0)

    location_time_header = "**Location @ Time**"
    location_time_value = "{} @ {}".format(location, timer)

    embed.add_field(name=location_time_header, value=location_time_value, inline=False)
    embed.add_field(name=mystic, value="[]", inline=True)
    embed.add_field(name=valor, value="[]", inline=True)
    embed.add_field(name=instinct, value="[]", inline=True)
    embed.add_field(name=total_field, value=total_value, inline=False)

    if map_dir is not None:
        embed.add_field(name="**Directions**", value="[Map Link](" + map_dir + ")", inline=False)

    return embed


async def setup_reactions(msg):
    await msg.add_reaction(getEmoji("mystic"))
    await asyncio.sleep(0.1)
    await msg.add_reaction(getEmoji("valor"))
    await asyncio.sleep(0.1)
    await msg.add_reaction(getEmoji("instinct"))
    await asyncio.sleep(0.1)
    await msg.add_reaction("🕹")
    await asyncio.sleep(0.1)
    await msg.add_reaction("✅")
    await asyncio.sleep(0.1)
    await msg.add_reaction("1⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("2⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("3⃣")
    await asyncio.sleep(0.1)
    await msg.add_reaction("🙏")
    await asyncio.sleep(0.1)
    await msg.add_reaction("🔈")
    await asyncio.sleep(0.1)
    await msg.add_reaction("🖍")
    await asyncio.sleep(0.1)
    # await msg.add_reaction("🥊")
    # await asyncio.sleep(0.1)


async def setup_mega(channel, emoji, message, user):
    info_start = message.content.find('(')
    info_end = message.content.find(')')

    if info_start < 0 or info_end < 0:
        return

    info = message.content[info_start+1:info_end]
    egg_message = None

    async for msg in channel.history(limit=25):
        if egg_message is None and msg.author == bot.user and msg.embeds:
            o_loc = get_field_by_name(msg.embeds[0].fields, "**Location")
            if o_loc is None:
                return
            if info == o_loc.value:
                egg_message = msg

    await message.delete()

    if egg_message is None:
        return

    await editmegapokemon(egg_message, emoji.name, user)

    return


@bot.command(pass_context=True)
async def info(ctx):
    embed = discord.Embed(title="PoGo Bot", description="Pokemon Go Discord Bot.", color=0xeee657)
    # give info about you here
    embed.add_field(name="Author", value="D4rKngh7, onorinbejasus")
    # Shows the number of servers the bot is member of.
    embed.add_field(name="Server count", value="{}".format(len(bot.guilds)))
    # give users a link to invite this bot to their server
    embed.add_field(name="Invite", value="No Invite. This bot must be self-hosted")
    await ctx.send(embed=embed)


@bot.command(aliases=[],
             brief="Send BEAST message",  pass_context=True)
async def beast(ctx):
    embed = discord.Embed(title=":regional_indicator_b: :regional_indicator_e: "
                                ":regional_indicator_a: :regional_indicator_s: "
                                ":regional_indicator_t:")
    embed.set_author(name=ctx.message.author.name)
    await ctx.send(embed=embed)
    await ctx.message.delete()


@bot.command(aliases=["ag"],
             brief="Add a new gym to the bot. !addgym [latitude] [longitude] [gym_name]", pass_context=True)
async def addgym(ctx, lat, lon, *, desc):
    global gyms

    def confirm(m):
        if m.author == ctx.message.author:
            return True
        return False

    await ctx.message.delete()

    if not await checkmod(ctx, MOD_ROLE_ID):
        ctx.send("{}, you are not allowed to add a new gym.".format(ctx.message.author.mention), delete_after=10.0)
        return
    try:
        lat = float(lat)
        lon = float(lon)
    except ValueError:
        ctx.send("The latitude or longitude you entered was not valid. Make sure to use the format !addgym [latitude] [longitude] [gym_name] ",
                 delete_after=20.0)
        return

    for gym in gyms:
        if gym["name"] == desc:
            await ctx.send("{} is already a gym.".format(desc), delete_after=10.0)
            return

    map_image = get_static_map_url(lat, lon, api_key=GMAPS_KEY)
    map = await ctx.send(map_image)
    name = await ctx.send(desc)
    ask = await ctx.send("Is this information correct? (yes/no)")
    try:
        msg = await bot.wait_for("message", timeout=30.0, check=confirm)
    except asyncio.TimeoutError:
        await ctx.message.delete()
        await ask.delete()
        await map.delete()
        await name.delete()
        return

    try:
        if msg.content.lower().startswith("y"):
            await msg.delete()
            await ask.delete()
            await name.delete()
            await map.delete()

            new_gym = {
                "name": desc,
                "latitude": str(lat),
                "longitude": str(lon),
                "description": "",
                "url": ""
            }
            gyms.append(new_gym)
            write_gyms(path+"gyms.json", gyms)
            load_gyms(path+'gyms.json')

            await ctx.send("{} was successfully added.".format(desc), delete_after=10.0)

        else:
            await ctx.send("Gym not added..", delete_after=10.0)
            await msg.delete()
            await ask.delete()
            await name.delete()
            await map.delete()

    except Exception:
        traceback.print_exc(file=sys.stdout)


@bot.command(aliases=["clr"],
             brief="[MOD] Clear all members from role. !clearrole [role_name]", pass_context=True)
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


@bot.command(aliases=[], brief="[MOD] Purge messages from channel. !purge [pinned]", pass_context=True)
async def purge(ctx, pinned=False, limit=100, after=None):
    def notpinned(message):
        return not message.pinned

    def confirm(m):
        if m.author == ctx.message.author:
            return True
        return False

    if await checkmod(ctx, MOD_ROLE_ID):
        ask = await ctx.send("Are you sure you would like to clear the last 100 messages? (yes/no)")
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


@bot.command(aliases=[], brief="Messages the donation link",  pass_context=True)
async def donate(ctx):
    await ctx.send("You can donate by Paypal at {}".format(PAYPAL_DONATION_LINK))
    await ctx.message.delete()


@bot.command(aliases=["sex"], brief="[MOD] Manually scan channel for ex-raid posts. !scanex ", pass_context=True)
async def scanex(ctx):
    if not await checkmod(ctx, MOD_ROLE_ID):
        return

    await manualexscan(ctx.message.channel)
    await ctx.send("Scan completed", delete_after=10)
    await ctx.message.delete()


@bot.command(aliases=["exu"],
             brief="[MOD] Continuously update ex-raid channel manually. !exupdater [minutes]", pass_context=True)
async def exupdater(ctx, minutes=5):
    global running_updater
    if not await checkmod(ctx,MOD_ROLE_ID):
        return

    ctx.message.delete()

    if minutes > 0:
        running_updater = True
        await ctx.send("Scanning every {} minutes.".format(minutes), delete_after=10)

    else:
        running_updater = False
        return

    await exupdaterloop(ctx.message.channel, minutes)


@bot.command(aliases=["eo"], brief="[MOD] Send message tagging @everyone. !everyone [message]", pass_context=True)
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
        async for msg in channel.history(limit=50):
            if msg.author != bot.user:
                continue
            if msg.embeds and msg.embeds[0].footer and msg.embeds[0].footer.text.startswith("ex-"):
                await notify_exraid(msg)
    except:
        pass


@bot.command(aliases=[], brief="[MOD] Clear raid posts from channel. !clearraids", pass_context=True)
async def clearraids(ctx):
    def raid(msg):
        return msg.author == bot.user and (check_footer(msg, "raid") or check_footer(msg, "raid-train"))

    if not await checkmod(ctx, MOD_ROLE_ID):
        return
    await ctx.message.channel.purge(limit=500, check=raid)
    await ctx.send("Cleared all raid posts", delete_after=10)


@bot.command(aliases=["rg"], brief="[MOD] Reload gyms from file. !reloadgyms", pass_context=True)
async def reloadgyms(ctx):
    global gyms
    if os.path.exists(path+'gyms.json'):
        try:
            gyms = load_gyms(path+'gyms.json')
            await ctx.send("Gyms successfully loaded!", delete_after=30.0)
        except:
            await ctx.send("There was an issue reloading the gyms!", delete_after=30.0)
    else:
        await ctx.send("gyms.json does not exist!", delete_after=30.0)
    await ctx.message.delete()


@bot.command(aliases=["r"],
             usage="!raid [pokemon] [location] [time]",
             help="Create a new raid posting. Users will also be listed in "
                  "the post by team. Press 1, 2, or 3 to specify other teamless"
                  "guests that will accompany you.",
             brief="Create a new raid post. !raid <pkmn> <location> <time>",
             pass_context=True)
async def raid(ctx, pkmn, *, locationtime):
    await ctx.message.delete()

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

    embed = await setup_raid(ctx, pkmn, location, timer)

    if embed is not None:
        embed.set_footer(text="raid")
        msg = await ctx.send(embed=embed)

        await asyncio.sleep(0.1)
        # await msg.pin()

        await setup_reactions(msg)

        # await asyncio.sleep(1)
        # await msg.unpin()


@bot.command(aliases=["train"],
             usage="!train [pokemon] [location] [time] [area]",
             help="Create a new raid train posting for west campus. Users will also be listed in "
                  "the post by team. Press 1, 2, or 3 to specify other teamless"
                  "guests that will accompany you.",
             brief="Create a new raid train post. !raid <pkmn> <location> <time> <area>",
             pass_context=True)
async def raidtrain(ctx, pkmn, *, locationtimearea):

    areas = ['west', 'east', 'north']
    area = None
    location = ""
    timer = ""
    lt = locationtimearea.rsplit(" ", 2)

    if len(lt) > 1 and str(lt[-1]).strip().lower() in areas:
        if re.search(r'[0-9]', str(lt[-2])):
            area = "train" + lt.pop().strip().lower()
            timer = lt.pop().strip()
            location = " ".join([loc.strip().lower() for loc in lt])
        else:
            area = "train" + lt.pop().strip().lower()
            location = " ".join([loc.strip().lower() for loc in lt])
            timer = "6:00pm"

    embed = await setup_raid(ctx, pkmn, location, timer)

    embed.set_footer(text="raid-train: {}".format(area))
    msg = await ctx.send(embed=embed)

    await asyncio.sleep(0.1)
    await ctx.message.delete()
    await msg.pin()

    await setup_reactions(msg)

    await asyncio.sleep(1)
    await msg.unpin()


async def editraidlocation(msg, location):
    map_dir = None
    for i in range(0, len(msg.embeds[0].fields)):
        field2 = msg.embeds[0].fields[i]
        if "**Location" in field2.name:
            timer = field2.value.split(" ")[-1]
            location = string.capwords(location)
            location_time_value = "{} @ {}".format(location, timer)

            msg.embeds[0].set_field_at(i, name=field2.name, value=location_time_value, inline=False)
            coords = get_gym_coords(location)
            map_dir = get_map_dir_url(coords[0], coords[1])

            if coords and GMAPS_KEY:
                map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
                msg.embeds[0].set_image(url=map_image)

        if map_dir and "**Directions" in field2.name:
            msg.embeds[0].set_field_at(i, name="**Directions**", value="[Map Link](" + map_dir + ")", inline=False)
            await msg.edit(embed=msg.embeds[0])
            return True

    if map_dir:
        msg.embeds[0].add_field(name="**Directions**", value="[Map Link](" + map_dir + ")", inline=False)

    await msg.edit(embed=msg.embeds[0])

    return False


@bot.command(aliases=["re"],
             usage="!raidegg [level] [location] [hatch_time]",
             help="Create a new raid egg posting. Users will also be listed in the post by team. Press 1, 2, or 3 to specify other teammate"
                  " guests that will accompany you.",
             brief="Create a new raid post. !raidegg <pkmn> <location> <time>",
             pass_context=True)
async def raidegg(ctx, level, *, locationtime):
    if not ANYONE_RAID_POST or not check_roles(ctx.message.author, RAID_ROLE_ID):
        await ctx.send("{}, you are not allowed to post raids.".format(ctx.message.author.mention), delete_after=10.0)
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

    async for msg in ctx.message.channel.history(limit=25):
        if msg.author == bot.user and msg.embeds:
            o_loc = get_field_by_name(msg.embeds[0].fields, "**Location")
            t_loc = o_loc.value.lower().split(" @ ")
            o_old = t_loc[0]
            o_time = t_loc[1]
            if o_loc and location.lower() == o_old and level.lower() in msg.embeds[0].title.lower():
                if o_time == timer:
                    await ctx.send("Raid at {} already exists, please use previous post".format(location), delete_after=10.0)
                    return None

    thumb = None
    descrip = ""
    if EGG_IMAGE_URL:
        thumb = EGG_IMAGE_URL.format(level.upper())
    embed = discord.Embed(title="Raid Egg - {} ({})".format(level, ctx.message.author.name), description=descrip)
    # embed.set_author(name=ctx.message.author.name)

    if thumb:
        embed.set_thumbnail(url=thumb)
    coords = get_gym_coords(location)
    if coords and GMAPS_KEY:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        embed.set_image(url=map_image)

    header_space = " ".join(["\u200a" for i in range(0, 20)])
    value_space = " ".join(["\u200a" for i in range(0, 28)])
    total_field = "**Total:**" + header_space + "**Remote:**"
    total_value = "**{}**".format(0) + value_space + "**{}**".format(0)

    location_time_header = "**Location @ Time**"
    location_time_value = "{} @ {}".format(location, timer)

    embed.add_field(name=location_time_header, value=location_time_value, inline=False)
    # embed.add_field(name="Proposed Time:", value=timer + "\n", inline=True)
    embed.add_field(name="** **", value="** **", inline=False)
    embed.add_field(name=str(getEmoji("mystic")) + "__Mystic (0)__", value="[]", inline=True)
    embed.add_field(name=str(getEmoji("valor")) + "__Valor (0)__", value="[]", inline=True)
    embed.add_field(name=str(getEmoji("instinct")) + "__Instinct (0)__", value="[]", inline=True)
    embed.add_field(name=total_field, value=total_value, inline=False)
    # embed.add_field(name="**Remote:**", value="0", inline=True)

    embed.set_footer(text="raid")
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(0.1)
    await ctx.message.delete()
    await setup_reactions(msg)


@bot.command(aliases=["me"],
             usage="!mega [location] [hatch_time]",
             help="Create a new mega raid egg posting. Users will also be listed in the post by team. Press 1, 2, or 3 to specify other teammate"
                  " guests that will accompany you.",
             brief="Create a new mega egg post. !mega <location> <time>",
             pass_context=True)
async def mega(ctx, *, locationtime):

    if not ANYONE_RAID_POST or not check_roles(ctx.message.author, RAID_ROLE_ID):
        await ctx.send("{}, you are not allowed to post raids.".format(ctx.message.author.mention), delete_after=10.0)
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

    location = string.capwords(location)

    async for msg in ctx.message.channel.history(limit=25):
        if msg.author == bot.user and msg.embeds:
            o_loc = get_field_by_name(msg.embeds[0].fields, "**Location")
            t_loc = o_loc.value.lower().split(" @ ")
            o_old = t_loc[0]
            o_time = t_loc[1]
            if o_loc and location.lower() == o_old and o_time == timer:
                await ctx.send("Raid at {} already exists, please use previous post".format(location), delete_after=10.0)
                return None

    thumb = None
    descrip = ""
    if EGG_IMAGE_URL:
        thumb = EGG_IMAGE_URL.format('mega_egg')
    embed = discord.Embed(title="Mega Egg - ({})".format(ctx.message.author.name), description=descrip)
    # embed.set_author(name=ctx.message.author.name)

    if thumb:
        embed.set_thumbnail(url=thumb)
    coords = get_gym_coords(location)
    if coords and GMAPS_KEY:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        embed.set_image(url=map_image)

    header_space = " ".join(["\u200a" for i in range(0, 20)])
    value_space = " ".join(["\u200a" for i in range(0, 28)])
    total_field = "**Total:**" + header_space + "**Remote:**"
    total_value = "**{}**".format(0) + value_space + "**{}**".format(0)

    location_time_header = "**Location @ Time**"
    location_time_value = "{} @ {}".format(location, timer)

    embed.add_field(name=location_time_header, value=location_time_value, inline=False)
    # embed.add_field(name="Proposed Time:", value=timer + "\n", inline=True)
    embed.add_field(name="** **", value="** **", inline=False)
    embed.add_field(name=str(getEmoji("mystic")) + "__Mystic (0)__", value="[]", inline=True)
    embed.add_field(name=str(getEmoji("valor")) + "__Valor (0)__", value="[]", inline=True)
    embed.add_field(name=str(getEmoji("instinct")) + "__Instinct (0)__", value="[]", inline=True)
    embed.add_field(name=total_field, value=total_value, inline=False)
    # embed.add_field(name="**Remote:**", value="0", inline=True)

    embed.set_footer(text="raid")
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(0.1)
    await ctx.message.delete()
    await setup_reactions(msg)
    await msg.add_reaction(getEmoji("Raid_Emblem"))
    await asyncio.sleep(0.1)


@bot.command(aliases=["rt"],
             usage="!raidtime [location] [time]",
             brief="Edit the time on a previous raid post. "
                   "!raidtime <location> <time>",
             pass_context=True)
async def raidtime(ctx, loc, timer=None):
    async for msg in ctx.message.channel.history(limit=25):
        if msg.author != bot.user or not msg.embeds:
            continue
        for field in msg.embeds[0].fields:
            if field.name.startswith("**Location") and loc.lower() in field.value.lower():
                if ctx.message.author.name != msg.embeds[0].author.name and not check_roles(ctx.message.author, RAID_ROLE_ID):
                    await ctx.send("You cannot edit this raid post. "
                                   "Only the original poster can.", delete_after=20.0)
                    await ctx.message.delete()
                    return
                if timer:
                    old_timer = field.value.split(" ")[-1]
                    await editraidtime(msg, timer)
                    await ctx.send("Updated Raid at *{}* to time: **{}**".format(old_timer, timer))
                    await ctx.message.delete()
                    return
                else:
                    total = get_field_by_name(msg.embeds[0].fields, "**Location")
                    total = total.value.split(" ")[0] if total else 0
                    time_field = get_field_by_name(msg.embeds[0].fields, "**Location") or get_field_by_name(msg.embeds[0].fields, "Date:")
                    raid_time = time_field.value.split(" ")[-1]
                    raid_loc = time_field.value.split(" ")[0:-1]
                    await ctx.send(
                        "Raid at **{}** at time: **{}** has  **{} ** "
                        "people registered.".format(raid_loc, raid_time, total))
                    await ctx.message.delete()
                    return
    await ctx.message.delete()
    await ctx.send("Unable to find Raid at {}".format(loc), delete_after=30)


async def editraidtime(msg, timer):
    for i in range(0, len(msg.embeds[0].fields)):
        field2 = msg.embeds[0].fields[i]
        if "Time" in field2.name or field2.name.startswith("Date:"):
            if timer:
                loc = field2.value.split(" @ ")[0]
                location_time_value = "{} @ {}".format(loc, timer)

                msg.embeds[0].set_field_at(i, name=field2.name, value=location_time_value, inline=False)
                await msg.edit(embed=msg.embeds[0])
                return True
    return False


@bot.command(aliases=["rp"],
             usage="!raidpokemon [location] [pokemon]",
             brief="Edit the pokemon on a previous raid post. "
                   "!raidpokemon <location> <pokemon>",
             pass_context=True)
async def raidpokemon(ctx, loc, pkmn):

    async for msg in ctx.message.channel.history(limit=25):
        if msg.author != bot.user or not msg.embeds:
            continue
        for field in msg.embeds[0].fields:
            if field.name.startswith("**Location") and loc.lower() in field.value.lower():
                if ctx.message.author.name != msg.embeds[
                    0].author.name and not check_roles(ctx.message.author,
                                                       RAID_ROLE_ID):
                    await ctx.send("You cannot edit this raid post. Only the original poster can.", delete_after=20.0)
                    await ctx.message.delete()
                    return
                await editraidpokemon(msg, pkmn, msg.author.name)
                await ctx.send("Raid at **{}** updated to **{}**"
                               .format(field.value, pkmn))
                await ctx.message.delete()
                return
    await ctx.message.delete()
    await ctx.send("Unable to find Raid at {}".format(loc), delete_after=30)


async def editmegapokemon(msg, pkmn, user):
    descrip = msg.embeds[0].description

    parsed_name = pkmn.split("_")
    name = parsed_name[1]

    match = pokemon_match(name)
    if match:
        pkmn = match
    pkmn = string.capwords(pkmn, "-")
    pid = get_pokemon_id_from_name(pkmn.lower())
    weather = []
    if pid:
        stats = await get_db_stats(str(pid)[:-1])
        if stats["weatherInfluences"]:
            for i in range(0, len(stats["weatherInfluences"])):
                emoji = parse_weather(stats["weatherInfluences"][i])
                weather.append(emoji)

        if IMAGE_URL:
            if len(parsed_name) > 2:
                thumb = IMAGE_URL.format("{}M_{}".format(pid, parsed_name[2]))
                print(thumb)
            else:
                thumb = IMAGE_URL.format("{}M".format(pid))
            msg.embeds[0].set_thumbnail(url=thumb)

        mincp20, maxcp20 = get_cp_range(pid, 20)
        mincp25, maxcp25 = get_cp_range(pid, 25)

        if len(weather) > 1:
            descrip = "**CP**: {}-{} \u200a \u200a {}{}: {}-{}".format(mincp20, maxcp20, weather[0], weather[1], mincp25, maxcp25)
        elif len(weather) > 0:
            descrip = "**CP**: {}-{} \u200a \u200a {}: {}-{}".format(mincp20, maxcp20, weather[0], mincp25, maxcp25)
        else:
            descrip = "**CP**: {}-{} \u200a \u200a WB: {}-{}".format(mincp20, maxcp20, mincp25, maxcp25)
    else:
        printr("Pokemon id not found for {}".format(pkmn))
        msg.embeds[0].set_thumbnail(None)
    if check_footer(msg, "raid") or check_footer(msg, "raid-train"):
        msg.embeds[0].title ="Raid - {} ({})".format(" ".join(parsed_name), user.name)

    elif check_footer(msg, "ex-raid"):
        msg.embeds[0].title ="Raid - {} ({})".format(pkmn, user.name)

    msg.embeds[0].description = descrip
    await msg.edit(embed=msg.embeds[0])
    return True


async def editraidpokemon(msg, pkmn, user):
    descrip = msg.embeds[0].description
    match = pokemon_match(pkmn)
    if match:
        pkmn = match
    pkmn = string.capwords(pkmn, "-")
    pid = get_pokemon_id_from_name(pkmn.lower())
    weather = []
    if pid:

        stats = await get_db_stats(str(pid)[:-1])
        if stats["weatherInfluences"]:
            for i in range(0, len(stats["weatherInfluences"])):
                emoji = parse_weather(stats["weatherInfluences"][i])
                weather.append(emoji)

        if IMAGE_URL:
            thumb = IMAGE_URL.format(pid)
            msg.embeds[0].set_thumbnail(url=thumb)

        mincp20, maxcp20 = get_cp_range(pid, 20)
        mincp25, maxcp25 = get_cp_range(pid, 25)

        if len(weather) > 1:
            descrip = "**CP**: {}-{} \u200a \u200a {}{}: {}-{}".format(mincp20, maxcp20, weather[0], weather[1], mincp25, maxcp25)
        elif len(weather) > 0:
            descrip = "**CP**: {}-{} \u200a \u200a {}: {}-{}".format(mincp20, maxcp20, weather[0], mincp25, maxcp25)
        else:
            descrip = "**CP**: {}-{} \u200a \u200a WB: {}-{}".format(mincp20, maxcp20, mincp25, maxcp25)
    else:
        printr("Pokemon id not found for {}".format(pkmn))
        msg.embeds[0].set_thumbnail(None)
    if check_footer(msg, "raid") or check_footer(msg, "raid-train"):
        msg.embeds[0].title ="Raid - {} ({})".format(pkmn, user)

    elif check_footer(msg, "ex-raid"):
        msg.embeds[0].title ="Raid - {} ({})".format(pkmn, user)

    msg.embeds[0].description = descrip
    await msg.edit(embed=msg.embeds[0])
    return True


async def sendraidmessage(loc, ctx, message):
    async for msg in ctx.message.channel.history(limit=25):
        if msg.author != bot.user or not msg.embeds:
            continue

        for field in msg.embeds[0].fields:
            if field.name.startswith("**Location") and loc.lower() in field.value.lower():
                registered = []

                for reaction in msg.reactions:
                    async for user in reaction.users():
                        if user == bot.user:
                            continue
                        if user not in registered:
                            registered.append(user)

                auth = ctx.message.author

                if auth not in registered and not check_roles(auth, RAID_ROLE_ID) and msg.embeds[0].author.name != auth.name:
                    await ctx.send("You are not involved with this raid.", delete_after=10.0)
                    await ctx.msg.delete()
                    return

                for user in registered:
                    if user.dm_channel:
                        await user.dm_channel.send(message)
                    else:
                        dm = await user.create_dm()
                        await dm.send(message)

                return

        await ctx.send("Cannot find raid *{}*".format(loc), delete_after=10.0)
        await ctx.message.delete()


async def sendraidmessagechannel(loc, channel, message):
    global bot
    async for msg in channel.history(limit=25):

        if msg.author != bot.user or not msg.embeds:
            continue

        for field in msg.embeds[0].fields:

            if field.name.startswith("**Location") and loc.lower() in field.value.lower():
                registered = []

                for reaction in msg.reactions:
                    async for user in reaction.users():
                        if user == bot.user:
                            continue
                        if user not in registered:
                            registered.append(user)

                for user in registered:
                    if user.dm_channel:
                        await user.dm_channel.send(message)
                    else:
                        dm = await user.create_dm()
                        await dm.send(message)

                return


@bot.command(aliases=["rm"],
             usage="!raidmessage [location] [msg]",
             brief="Message members in raid "
                   "!raidmessage <location> <msg>",
             pass_context=True)
async def raidmessage(ctx, loc, *, message):
    channel = ctx.message.channel
    await sendraidmessage(loc, channel, message)


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
    async for msg in ctx.message.channel.history(limit=25):
        if msg.author != bot.user or not msg.embeds:
            continue
        for field in msg.embeds[0].fields:
            if field.name.startswith("**Location") and loc.lower() in field.value.lower():
                if msg.embeds[0].author.name != ctx.message.author.name and not check_roles(ctx.message.author, RAID_ROLE_ID):
                    await ctx.send("You cannot set coordinates for this raid!", delete_after=10.0)
                    await ctx.message.delete()
                    return
                if coords == "reset":
                    msg.embeds[0].set_image(url=None)
                    await msg.edit(embed=msg.embeds[0])
                    await ctx.send("Raid {} updated, coords reset."
                                   .format(field.value), delete_after=10.0)
                    await ctx.message.delete()
                    return
                if check_footer(msg, "raid") or check_footer(msg, "raid-train"):
                    await notify_raid(msg, coords)
                    await ctx.send("Raid {} updated to coords: ({},{})"
                                   .format(field.value, coords[0], coords[1]), delete_after=10.0)
                    await ctx.message.delete()
                    return
                elif check_footer(msg, "ex-raid"):
                    await notify_exraid(msg, coords)
                    await ctx.send("Ex-Raid {} updated to coords: ({},{})"
                                   .format(field.value, coords[0], coords[1]), delete_after=10.0)
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
        await ctx.send("{}, you are not allowed to post ex-raids.".format(ctx.message.author.mention), delete_after=10.0)
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
    embed.add_field(name="**Location", value=location, inline=True)
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


@bot.command(aliases=["ks"], pass_context=True)
async def killscheduler(ctx):
    global cease_flag

    def confirm(m):
        if m.author == ctx.message.author:
            return True
        return False

    if await checkmod(ctx, MOD_ROLE_ID):
        ask = await ctx.send("Are you sure you would like to stop the scheduler? (yes/no) " )
        try:
            msg = await bot.wait_for("message", timeout=30.0, check=confirm)
        except asyncio.TimeoutError:
            await ctx.message.delete()
            await ask.delete()
            return

        try:
            print("killing the scheduler")
            await ask.delete()
            await msg.delete()
            await ctx.message.delete()

            cease_flag.set()

            for task in asyncio.Task.all_tasks():
                task.cancel()

        except Exception:
            traceback.print_exc(file=sys.stdout)

        finally:
            os.system("sudo reboot now")


@bot.command(aliases=["pb"],
             usage="",
             brief=""
                   "!",
             pass_context=True)
async def pokebattler(ctx):
    return


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
    remote = 0
    user_guests = {}
    user_ready = {}
    user_remote = {}
    user_invite = []

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
                    user_ready[user.name] = str(getEmoji("green_check"))
            elif reaction.emoji == "🕹":
                users = await reaction.users().flatten()
                for user in users:
                    user_remote[user.name] = "🕹"
            elif reaction.emoji == "🙏":
                users = await reaction.users().flatten()
                for user in users:
                    if user == bot.user:
                        continue
                    user_invite.append(user.name)

    for reaction in msg.reactions:
        if isinstance(reaction.emoji, str):
            continue

        if reaction.emoji.name == 'mystic':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                if user.name in user_remote:
                    remote += 1
                guest = ""
                if user.name in user_guests:
                    guest = "+{}".format(user_guests.get(user.name), "")
                    if user.name in user_remote:
                        remote += user_guests[user.name]
                mystic += user_remote.get(user.name, "") + user.name.lstrip(" ") + guest + user_ready.get(user.name, "") + ", "
                m_tot += 1
                total += 1
            mystic = mystic.rstrip(", ")

        elif reaction.emoji.name == 'valor':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                if user.name in user_remote:
                    remote += 1
                guest = ""
                if user.name in user_guests:
                    guest = "+{}".format(user_guests.get(user.name), "")
                    if user.name in user_remote:
                        remote += user_guests[user.name]
                valor += user_remote.get(user.name, "") + user.name.lstrip(" ") + guest + user_ready.get(user.name, "") + ", "
                v_tot += 1
                total += 1
            valor = valor.rstrip(", ")

        elif reaction.emoji.name == 'instinct':
            users = await reaction.users().flatten()
            for user in users:
                if user == bot.user:
                    continue
                if user.name in user_remote:
                    remote += 1
                guest = ""
                if user.name in user_guests:
                    guest = "+{}".format(user_guests.get(user.name), "")
                    if user.name in user_remote:
                        remote += user_guests[user.name]
                instinct += user_remote.get(user.name, "") + user.name.lstrip(" ") + guest + user_ready.get(user.name, "") + ", "
                i_tot += 1
                total += 1
            instinct = instinct.rstrip(", ")

    mystic = "[{}]".format(mystic)
    valor = "[{}]".format(valor)
    instinct = "[{}]".format(instinct)
    invite = "[{}]".format(", ".join(user_invite))

    embed = msg.embeds[0]

    header_space = " ".join(["\u200a" for i in range(0, 20)])
    value_space = " ".join(["\u200a" for i in range(0, 28)])
    total_field = "**Total:**" + header_space + "**Remote:**"
    total_value = "**{}**".format(total) + value_space + "**{}**".format(remote)

    # if GMAPS_KEY and coords:
    #     map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
    #     embed.set_image(url=map_image)

    total_idx = -1
    invite_idx = -1

    for i in range(0, len(embed.fields)):
        if "Mystic" in embed.fields[i].name:
            embed.set_field_at(i, name=str(
                getEmoji("mystic")) + "__Mystic ({})__".format(m_tot), value=mystic, inline=True)
        elif "Valor" in embed.fields[i].name:
            embed.set_field_at(i, name=str(getEmoji("valor")) + "__Valor ({})__".format(v_tot), value=valor, inline=True)
        elif "Instinct" in embed.fields[i].name:
            embed.set_field_at(i, name=str(getEmoji("instinct")) + "__Instinct ({})__".format(i_tot), value=instinct, inline=True)
        elif "Total" in embed.fields[i].name:
            total_idx = i
            embed.set_field_at(i, name=total_field, value=total_value.format(total), inline=True)
        elif "Needs Invite" in embed.fields[i].name:
            invite_idx = i
            if len(user_invite) > 0:
                embed.set_field_at(i, name="**🙏Needs Invite🙏**", value=invite, inline=False)

    if invite_idx > 0 and len(user_invite) == 0:
        embed.remove_field(invite_idx)

    elif invite_idx == -1 and len(user_invite) > 0:
        embed.insert_field_at(total_idx, name="**🙏Needs Invite🙏**", value=invite, inline=False)

    await msg.edit(embed=embed)


async def notify_exraid(msg, coords=None):
    mystic = ""
    valor = ""
    instinct = ""
    m_tot = 0
    v_tot = 0
    i_tot = 0
    total = 0

    role_name, role = await get_role(msg)
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
                    printr("User {} added to role {}".format(user.name,role_name))
                    await msg.channel.send("{} you have been added to {}".format(user.name, role_name), delete_after=30.0)

                guest = "+{}".format(
                    user_guests.get(user.name), 0) if user.name in user_guests else ""
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
                    user_guests.get(user.name), 0) if user.name in user_guests else ""
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
                    user_guests.get(user.name), 0) if user.name in user_guests else ""
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


def getEmoji(name):
    return discord.utils.get(bot.emojis, name=name)


if __name__ == "__main__":
    path = '/var/opt/PoGo-Bot/'
    # path = '/Users/tluciani/WebstormProjects/PoGo-Bot/'
    cfg = configparser.ConfigParser()
    cfg.read(path+'config.ini')

    try:
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
        GMAPS_KEY = cfg['PoGoBot'].get('GMapsKey') or None
        load_locale(os.path.join(path+'locales', '{}.json'.format(cfg['PoGoBot']['Locale'] or 'en')))
        load_base_stats(os.path.join(path+'data', 'base_stats_revised.json'))
        load_cp_multipliers(os.path.join(path+'data', 'cp_multipliers.json'))

        if os.path.exists(path+'gyms.json'):
            gyms = load_gyms(path+'gyms.json')

        try:
            bot.run(cfg['PoGoBot']['BotToken'])
        except CancelledError:
            print('CancelledError')

    except NameError:
        print("I tried")