import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import motor.motor_asyncio
from keep_alive import keep_alive
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
TORN_API_KEY = os.getenv("API_KEY")

class WarBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        self.db = self.db_client["TornWarTracker"]
        
        self.war_col = self.db["War"]
        self.profiles_col = self.db["War_Profiles"]
        self.archives_col = self.db["Historical_Wars"]
        self.archived_profiles_col = self.db["Historical_Profiles"]

    async def setup_hook(self):
        await self.tree.sync()
        self.war_manager_loop.start()

    @tasks.loop(seconds=60)
    async def war_manager_loop(self):
        async with aiohttp.ClientSession() as session:
            url = f"https://api.torn.com/faction/?selections=basic,rankedwars,attacks&key={TORN_API_KEY}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    active_war_doc = await self.war_col.find_one({"status": "active"})
                    ranked_wars = data.get("rankedwars", {})
                    
                    if ranked_wars:
                        war_id = list(ranked_wars.keys())[0]
                        war_data = ranked_wars[war_id]
                        factions = war_data.get("factions", {})
                        
                        my_faction_id = str(data.get("ID"))
                        enemy_faction_id = [fid for fid in factions.keys() if fid != my_faction_id][0]
                        enemy_name = factions[enemy_faction_id].get("name", "Unknown").replace(" ", "_")
                        
                        # Grab member counts from the ranked war payload
                        home_member_count = len(factions.get(my_faction_id, {}).get("members", {}))
                        enemy_member_count = len(factions.get(enemy_faction_id, {}).get("members", {}))
                        
                        start_timestamp = war_data.get("war", {}).get("start", 0)
                        start_date = datetime.fromtimestamp(start_timestamp).strftime('%Y_%m_%d')
                        war_stamp = f"{enemy_name}_{start_date}"
                        
                        if not active_war_doc:
                            # The updated War Memo schema with your exact requested fields
                            war_memo = {
                                "_id": war_stamp,
                                "status": "active",
                                "enemy_name": enemy_name,
                                "enemy_id": enemy_faction_id,
                                "start_time": start_timestamp,
                                "end_time": None,
                                "home_member_count": home_member_count,
                                "enemy_member_count": enemy_member_count,
                                "rank_and_division": "Unknown", # Will be updated via faction API
                                "home_score": 0,
                                "enemy_score": 0,
                                "winner": None,
                                "total_attacks": 0,
                                "mvp": None,
                                "caches_earned": []
                            }
                            await self.war_col.insert_one(war_memo)
                            
                            # (Profile generation logic remains completely unchanged here)
                            members = data.get("members", {})
                            for member_id, member_info in members.items():
                                profile = {
                                    "_id": f"{war_stamp}_{member_id}",
                                    "war_stamp": war_stamp,
                                    "player_id": member_id,
                                    "name": member_info.get("name"),
                                    "level": member_info.get("level"),
                                    "attacks_won": 0,
                                    "attacks_lost": 0,
                                    "defends_won": 0,
                                    "defends_lost": 0,
                                    "rp_gained_inside": 0.0,
                                    "rp_lost": 0.0,
                                    "inside_hits": 0,
                                    "outside_hits": 0,
                                    "rp_gained_outside": 0.0
                                }
                                await self.profiles_col.insert_one(profile)
                        
                        else:
                            # Update live scores while the war is active
                            home_score = factions.get(my_faction_id, {}).get("score", 0)
                            enemy_score = factions.get(enemy_faction_id, {}).get("score", 0)
                            await self.war_col.update_one(
                                {"_id": active_war_doc["_id"]},
                                {"$set": {"home_score": home_score, "enemy_score": enemy_score}}
                            )

                    elif not ranked_wars and active_war_doc:
                        war_stamp = active_war_doc["_id"]
                        
                        # When the war ends, update the end_time and status
                        # Winner, caches, and MVP will be calculated/added during this archive phase
                        await self.war_col.update_one(
                            {"_id": war_stamp}, 
                            {"$set": {
                                "status": "archived", 
                                "end_time": datetime.now().timestamp()
                            }}
                        )
                        
                        finished_war = await self.war_col.find_one({"_id": war_stamp})
                        await self.archives_col.insert_one(finished_war)
                        await self.war_col.delete_one({"_id": war_stamp})
                        
                        profiles_cursor = self.profiles_col.find({"war_stamp": war_stamp})
                        async for profile in profiles_cursor:
                            await self.archived_profiles_col.insert_one(profile)
                        await self.profiles_col.delete_many({"war_stamp": war_stamp})

bot = WarBot()

@bot.tree.command(name="current_war", description="View live stats for the ongoing ranked war")
async def current_war(interaction: discord.Interaction):
    active_war = await bot.war_col.find_one({"status": "active"})
    if not active_war:
        await interaction.response.send_message("There is no active ranked war currently logged in the database.", ephemeral=True)
        return
        
    await interaction.response.send_message(f"Displaying current war interface for: **{active_war['_id']}**")

@bot.tree.command(name="archives", description="Search and retrieve historical war reports")
@app_commands.describe(war_stamp="The exact ID of the war (e.g. Faction_Name_2026_10_10)")
async def archives(interaction: discord.Interaction, war_stamp: str):
    historical_war = await bot.archives_col.find_one({"_id": war_stamp})
    if not historical_war:
        await interaction.response.send_message(f"No archived war found with the stamp: `{war_stamp}`", ephemeral=True)
        return
        
    await interaction.response.send_message(f"Displaying historical war data for: **{war_stamp}**")

keep_alive()
bot.run(TOKEN)