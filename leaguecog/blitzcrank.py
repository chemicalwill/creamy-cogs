import asyncio
import logging
import aiohttp
import discord
from redbot.core import Config

from leaguecog.abc import MixinMeta

log = logging.getLogger("red.creamy.cogs.league")

class Blitzcrank(MixinMeta):
    # "The time of man has come to an end."
    # This class is responsible for:
    #   1) handling the token for Riot API.
    #   2) grabbing and pulling data from Riot API.
    # To-Do:
    #   Move all standard API call logic into one function to call
    #   First install instructions
    #       1) Set API Key
    #       2) Let user decide if they want announcement
    #       2a) If yes, set announcement channel
    #       3) Let user decide if they want betting
    #       4) If yes and economy is turned off, tell them how to turn it on.
    #   Warn user with instructions on how to set API key if it is invalid.
    #   Handle edge case of no-space, 2+ word names, no region inputted.
    #   Check if token is valid before kicking off loop polling
    #   Warning if no alert channel is set
    #   Check to see if economy is turned on, and require it
    #   Let user tell you a match is finished
    #   Register other user's for them.
    #   When registering users, don't allow double register of summoner id.
    #   Move chatter code to a separate class
    #   Instead of looping through registered summoners could we just loop through members with account info?

    async def __unload(self):
        asyncio.get_event_loop().create_task(self._session.close())

    async def get_league_api_key(self):
        """
        Loads the key-value pair 'api_key': <key> for 'league'
        If no key is assigned, returns None

        ex. set API key for league with:
            [p]set api league api_key <key>
        """
        if not self.api:
            db = await self.bot.get_shared_api_tokens("league")
            self.api = db["api_key"]
            return self.api
        else:
            return self.api

    async def apistring(self):
        apikey = await self.get_league_api_key()
        if apikey is None:
            return False
        else:
            return f"?api_key={apikey}"

    # This needs to move out of this class.
    # Possible chatter class? Who talks too much in League?
    # This class should be strictly for hitting Riot API.
    async def build_embed(self, title, msg, _type):
        embed = discord.Embed()

        if title:
            embed.title = title
        else:
            embed.title = "League of Legends Cog"

        # If this is passed an embed, update fields.
        #   Otherwise just insert the string.
        if isinstance(msg, discord.Embed):
            for field in msg.fields:
                embed.add_field(**field.__dict__)
        else:
            embed.description = msg

        # Handle types with various standard colors and messages
        GREEN = 0x00FF00
        RED = 0xFF0000
        GRAY = 0x808080

        if _type == "apiSuccess":
            embed.color = GREEN
        elif _type == "apiFail":
            embed.color = RED
            end = "Sorry, something went wrong!"
            embed.add_field(name="-" * 65, value=end)
        elif _type == "invalidRegion":
            embed.color = RED
        else:
            embed.color = GRAY

        return embed

    async def get(self, url):
        async with self._session.get(url) as response:
            return await response.json()

    async def get_summoner_info(self, ctx, name, member, region):
        message = await ctx.send(
            f"Attempting to register you as '{name}' in {region.upper()}..."
        )
        apiAuth = await self.apistring()

        try:
            region = self.regions[region.lower()]

        except KeyError:
            # raise a KeyError for bad region, pass title, type, and message to build_embed()
            #    and send the author a formatted list of available regions
            currTitle = "Invalid Region"
            currType = "invalidRegion"
            currMsg = (
                f"Region {region.upper()} not found. Available regions:\n"
                + ", ".join([r.upper() for r in self.regions.keys()])
            )

        else:
            async with aiohttp.ClientSession() as session:
                # build the url as an f-string, can double-check 'name' in the console
                url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{name}/{apiAuth}".format()
                log.info(f"url == {url}")

                async with session.get(url) as req:
                    try:
                        data = await req.json()
                    except aiohttp.ContentTypeError:
                        data = {}

                    if req.status == 200:
                        log.debug("200")
                        currTitle = "Registration Success"
                        currType = "apiSuccess"
                        pid, acctId, smnId = (
                            data["puuid"],
                            data["accountId"],
                            data["id"],
                        )
                        currMsg = (
                            f"Summoner now registered.\n"
                            f"**Summoner Name**: {name}\n"
                            f"**PUUID**: {pid}\n"
                            f"**AccountId**: {acctId}\n"
                            f"**SummonerId**: {smnId}"
                        )
                        async with self.config.guild(ctx.guild).registered_summoners() as reg_smn:
                            # Need to check if this summoner Id is already in the list
                            reg_smn.append({"smnId": data["id"], "region": region.lower()})
                        await self.config.member(member).summoner_name.set(name)
                        await self.config.member(member).puuid.set(data["puuid"])
                        await self.config.member(member).account_id.set(data["accountId"])
                        await self.config.member(member).summoner_id.set(data["id"])
                        await self.config.member(member).region.set(region.lower())

                    else:
                        currTitle = "Registration Failure"
                        currType = "apiFail"
                        if req.status == 404:
                            currMsg = f"Summoner '{name}' does not exist in the region {region.upper()}."
                        elif req.status == 401:
                            currMsg = "Your Riot API token is invalid or expired."
                        else:
                            currMsg = (
                                f"Riot API request failed with status code {req.status}"
                            )

        finally:
            embed = await self.build_embed(title=currTitle, msg=currMsg, _type=currType)
            await message.edit(content=ctx.author.mention, embed=embed)

    async def check_games(self):
        # Find alert channel
        # Handle no channel set up.
        channelId = await self.config.alertChannel()
        channel = self.bot.get_channel(channelId)
        log.debug(f"Found channel {channel}")
        # Loop through registered summoners
        async with self.config.guild(channel.guild).registered_summoners() as registered_summoners:
            for summoner in registered_summoners:
                # Skip blank records
                if summoner != {}:
                    smn = summoner["smnId"]
                    region = summoner["region"]
                    log.debug(f"Seeing if summoner: {smn} is in a game in region {region}...")                       
                    apiAuth = await self.apistring()
                    url = f"https://{region}.api.riotgames.com/lol/spectator/v4/active-games/by-summoner/{smn}/{apiAuth}"
                    log.debug(f"url == {url}")
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            url
                        ) as req:
                            try:
                                data = await req.json()
                            except aiohttp.ContentTypeError:
                                data = {}
                            if req.status == 200:
                                # Create a list of combo gameid + smn id to add to current active game list if not in there already.
                                gameIds = []
                                log.debug("GameIds")
                                async with self.config.guild(channel.guild).live_games() as live_games:
                                   #Need to not post twice when someone is in a game.
                                   # for active_game in live_games:
                                     #   if active_game != {}:
                                     #       log.debug("Creating gameIds")
                                     #       gameIds.append(str(active_game["gameId"]) + str(active_game["smnId"]))
                                   # if str(data["gameId"]) + str(data["smnId"]) not in gameIds:
                                    log.debug("Appending new live game")
                                    live_games.append({"gameId": data["gameId"], "smnId": summoner["smnId"], "region": summoner["region"], "startTime": data["gameStartTime"]})
                                    message = await channel.send(
                                            ("Summoner {smnId} started a game!").format(
                                                smnId = summoner["smnId"]
                                            )
                                        )
                            else:
                                if req.status == 404:
                                    log.debug("Summoner is not currently in a game.")
                                else:
                                    # Handle this more graciously
                                    log.warning = ("Riot API request failed with status code {statusCode}").format(
                                        statusCode = req.status
                                    ) 
                else:
                    log.debug("Skipped record")
                    continue