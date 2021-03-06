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
cease_flag = None

reaction_list = ["mystic", "valor", "instinct", "1⃣", "2⃣", "3⃣", "❌", "✅", "🖍", "🔈", '🕹', "gauntlet", "biga"]


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

    # loop = asyncio.get_event_loop()
    # schedule.every().day.at("06:01").do(scheduled_purge, loop=loop)
    #
    # # Start a new continuous run thread.
    # cease_flag = schedule.run_continuously(0)
    # # Allow a small time for separate thread to register time stamps.
    # time.sleep(0.001)


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
    if user == bot.user or message.author != bot.user or not message.embeds:
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
    if emoji.name == "🔈":
        if message.embeds[0].author == user.name or \
                check_roles(user, MOD_ROLE_ID) or \
                check_roles(user, RAID_ROLE_ID):

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
    if emoji.name == 'gauntlet':
        if message.embeds[0].author == user.name or \
                check_roles(user, MOD_ROLE_ID) or \
                check_roles(user, RAID_ROLE_ID):

            try:
                await message.remove_reaction(emoji, user)
                await sendraidmessagechannel(loc, channel, "Hop in at {}".format(loc))
                return
            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                return
    if emoji.name == 'biga':
        if message.embeds[0].author == user.name or \
                check_roles(user, MOD_ROLE_ID) or \
                check_roles(user, RAID_ROLE_ID):

            try:
                await message.remove_reaction(emoji, user)
                await sendraidmessagechannel(loc, channel, "Hop out at {}".format(loc))
                return
            except asyncio.TimeoutError:
                await message.remove_reaction(emoji, user)
                return

    if message.embeds and check_footer(message, "raid"):
        # printr("notifying raid {}: {}".format(loc, user.name))
        await notify_raid(message)
        if isinstance(emoji, str):
            await message.channel.send(
                "{} is bringing +{} to raid {}".format(
                    user.name, emoji, loc))
        return

    if message.embeds and check_footer(message, "ex-raid"):
        # printr("notifying exraid {}: {}".format(loc, user.name))
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
    if emoji.name == "❌" or emoji.name == "🖍" or emoji.name == "🔈" or \
            emoji.name not in reaction_list:
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
        if role_name and \
                not isinstance(emoji, str):
            for role in user.roles:
                if role.name == role_name:
                    await user.remove_roles(role)
                    await message.channel.send(
                        "{} you have left *{}*".format(user.mention, role_name), delete_after=10)
        # printr("Notifying Ex-raid: User {} has left {}".format(user.name, loc))
        await notify_exraid(message)
        await asyncio.sleep(0.1)


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

    embed = msg.embeds[0]

    if GMAPS_KEY and coords:
        map_image = get_static_map_url(coords[0], coords[1], api_key=GMAPS_KEY)
        embed.set_image(url=map_image)

    for i in range(0, len(embed.fields)):
        if "Mystic" in embed.fields[i].name:
            embed.set_field_at(i, name=str(
                getEmoji("mystic")) + "__Mystic ({})__".format(m_tot), value=mystic, inline=True)
        if "Valor" in embed.fields[i].name:
            embed.set_field_at(i, name=str(
                getEmoji("valor")) + "__Valor ({})__".format(v_tot), value=valor, inline=True)
        if "Instinct" in embed.fields[i].name:
            msg.embeds[0].set_field_at(i, name=str(
                getEmoji("instinct")) + "__Instinct ({})__".format(i_tot), value=instinct, inline=True)

        if "Total" in embed.fields[i].name:
            msg.embeds[0].set_field_at(i, name="**Total:**", value="**{}**".format(total), inline=True)
        if "Remote" in embed.fields[i].name:
            msg.embeds[0].set_field_at(i, name="**Remote:**", value="**{}**".format(remote), inline=True)

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


async def editraidrole(message, role):
    if message.embeds and check_footer(message, "ex-"):
        message.embeds[0].set_footer(text="ex-raid: {}".format(role))
        await message.edit(embed=message.embeds[0])
        printr("Ex-raid role changed to: {}".format(role))
        return True
    return False


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


async def sendraidmessage(loc, ctx, message):
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
                        if user not in registered:
                            registered.append(user)

                auth = ctx.message.author

                if auth not in registered and \
                        not check_roles(auth, RAID_ROLE_ID) and \
                        msg.embeds[0].author.name != auth.name:
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
    async for msg in channel.history(limit=1000):

        if msg.author != bot.user or not msg.embeds:
            continue

        for field in msg.embeds[0].fields:

            if field.name.startswith("Location") and loc.lower() in field.value.lower():
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



def getEmoji(name):
    return discord.utils.get(bot.emojis, name=name)


if __name__ == "__main__":
    path = '/Users/tluciani/WebstormProjects/PoGo-Bot/'
    cfg = configparser.ConfigParser()
    cfg.read(path+'config_react.ini')

    try:
        bot.command_prefix = cfg['PoGoBot']['BotPrefix'] or "!"
        MOD_ROLE_ID = cfg['PoGoBot'].get('ModRoleID') or -1
        RAID_ROLE_ID = cfg['PoGoBot'].get('RaidRoleID') or -1
        BOT_ROLE_ID = cfg['PoGoBot'].get('BotRoleID') or -1
        RAID_CHANNELS = cfg['PoGoBot'].get('RaidChannels') or 0

        if ',' in str(RAID_ROLE_ID):
            RAID_ROLE_ID = [x.strip() for x in RAID_ROLE_ID.split(",")]

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
            load_gyms(path+'gyms.json')

        bot.run(cfg['PoGoBot']['BotToken'])

    except NameError:
        print("I tried")
