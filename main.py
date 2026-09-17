import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import motor.motor_asyncio
from keep_alive import keep_alive
import os
from datetime import datetime
import random
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
TORN_API_KEY = os.getenv("API_KEY")

WAR_QUOTES = [
    '"The supreme art of war is to subdue the enemy without fighting." ~ Sun Tzu',
    '"In war, there is no substitute for victory." ~ Douglas MacArthur',
    '"To be prepared for war is one of the most effective means of preserving peace." ~ George Washington',
    '"Only the dead have seen the end of war." ~ Plato',
    '"All warfare is based on deception." ~ Sun Tzu',
    '"War is what happens when language fails." ~ Margaret Atwood',
    '"Mankind must put an end to war before war puts an end to mankind." ~ John F. Kennedy',
    '"I know not with what weapons World War III will be fought, but World War IV will be fought with sticks and stones." ~ Albert Einstein',
    '"Let him who desires peace prepare for war." ~ Vegetius',
    '"War does not determine who is right - only who is left." ~ Bertrand Russell',
    '"There is no flag large enough to cover the shame of killing innocent people." ~ Howard Zinn',
    '"A soldier will fight long and hard for a bit of colored ribbon." ~ Napoleon Bonaparte',
    '"In peace, sons bury their fathers. In war, fathers bury their sons." ~ Herodotus',
    '"The true soldier fights not because he hates what is in front of him, but because he loves what is behind him." ~ G.K. Chesterton',
    '"It is well that war is so terrible, otherwise we should grow too fond of it." ~ Robert E. Lee',
    '"Older men declare war. But it is the youth that must fight and die." ~ Herbert Hoover',
    '"If we don\'t end war, war will end us." ~ H.G. Wells',
    '"War is peace. Freedom is slavery. Ignorance is strength." ~ George Orwell',
    '"The object of war is not to die for your country but to make the other bastard die for his." ~ George S. Patton',
    '"Peace cannot be kept by force; it can only be achieved by understanding." ~ Albert Einstein',
    '"Wars may be fought with weapons, but they are won by men." ~ George S. Patton'
]

class WarBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        self.db = self.db_client["TornWarTracker"]
        
        self.war_col = self.db["War"]
        self.profiles_col = self.db["War_Profiles"]
        self.archives_col = self.db["Historical_Wars"]
        self.archived_profiles_col = self.db["Historical_Profiles"]
        
        self.enemy_profiles_col = self.db["Enemy_Profile"]
        self.archived_enemy_stats_col = self.db["Historical_Enemy_Stats"]
        self.factions_col = self.db["Factions"]

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
                        
                        home_member_count = len(factions.get(my_faction_id, {}).get("members", {}))
                        enemy_member_count = len(factions.get(enemy_faction_id, {}).get("members", {}))
                        
                        start_timestamp = war_data.get("war", {}).get("start", 0)
                        start_date = datetime.fromtimestamp(start_timestamp).strftime('%Y_%m_%d')
                        war_stamp = f"{enemy_name}_{start_date}"
                        
                        if not active_war_doc:
                            enemy_leader = "Unknown"
                            enemy_co = "Unknown"
                            enemy_members = {}
                            enemy_url = f"https://api.torn.com/faction/{enemy_faction_id}?selections=basic&key={TORN_API_KEY}"
                            async with session.get(enemy_url) as enemy_response:
                                if enemy_response.status == 200:
                                    enemy_data = await enemy_response.json()
                                    enemy_leader = str(enemy_data.get("leader", "Unknown"))
                                    enemy_co = str(enemy_data.get("co-leader", "Unknown"))
                                    enemy_members = enemy_data.get("members", {})

                            war_memo = {
                                "_id": war_stamp,
                                "status": "active",
                                "enemy_name": enemy_name,
                                "enemy_id": enemy_faction_id,
                                "start_time": start_timestamp,
                                "end_time": None,
                                "home_member_count": home_member_count,
                                "enemy_member_count": enemy_member_count,
                                "rank_and_division": "Unknown",
                                "home_score": 0,
                                "enemy_score": 0,
                                "winner": None,
                                "total_attacks": 0,
                                "mvp": None,
                                "caches_earned": []
                            }
                            await self.war_col.insert_one(war_memo)

                            home_faction_doc = {
                                "_id": f"{war_stamp}_2",
                                "war_stamp": war_stamp,
                                "status": "home",
                                "name": data.get("name", "Unknown"),
                                "count": home_member_count,
                                "leader": str(data.get("leader", "Unknown")), 
                                "co": str(data.get("co-leader", "Unknown"))
                            }
                            
                            for i, (mem_id, mem_info) in enumerate(data.get("members", {}).items(), 1):
                                home_faction_doc[f"member{i}"] = f"{mem_info.get('name')} - {mem_info.get('level')}"

                            enemy_faction_doc = {
                                "_id": f"{war_stamp}_1",
                                "war_stamp": war_stamp,
                                "status": "enemy",
                                "name": enemy_name,
                                "count": enemy_member_count,
                                "leader": enemy_leader,
                                "co": enemy_co
                            }
                            
                            for i, (mem_id, mem_info) in enumerate(enemy_members.items(), 1):
                                enemy_faction_doc[f"member{i}"] = f"{mem_info.get('name')} - {mem_info.get('level')}"

                            await self.factions_col.insert_many([home_faction_doc, enemy_faction_doc])
                            
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
                            home_score = factions.get(my_faction_id, {}).get("score", 0)
                            enemy_score = factions.get(enemy_faction_id, {}).get("score", 0)
                            await self.war_col.update_one(
                                {"_id": active_war_doc["_id"]},
                                {"$set": {"home_score": home_score, "enemy_score": enemy_score}}
                            )

                    elif not ranked_wars and active_war_doc:
                        war_stamp = active_war_doc["_id"]
                        
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

                        enemy_profiles = await self.enemy_profiles_col.find({}).to_list(length=None)
                        if enemy_profiles:
                            total_enemy_hits = sum(ep.get("attack", 0) for ep in enemy_profiles)
                            most_enemy_hits_p = max(enemy_profiles, key=lambda ep: ep.get("attack", 0), default={})
                            most_enemy_rp_p = max(enemy_profiles, key=lambda ep: ep.get("rp", 0), default={})
                            
                            enemy_stat_doc = {
                                "_id": war_stamp,
                                "war_stamp": war_stamp,
                                "total_hits": total_enemy_hits,
                                "most_hits": most_enemy_hits_p.get("name", "N/A"),
                                "most_rp": most_enemy_rp_p.get("name", "N/A")
                            }
                            await self.archived_enemy_stats_col.insert_one(enemy_stat_doc)
                            await self.enemy_profiles_col.delete_many({})

bot = WarBot()

class GenericBackView(discord.ui.View):
    def __init__(self, war_stamp):
        super().__init__(timeout=180)
        self.war_stamp = war_stamp

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"**Details Menu:** {self.war_stamp}", view=ArchiveDetailsMenuView(self.war_stamp))

class FactionChoiceView(discord.ui.View):
    def __init__(self, war_stamp):
        super().__init__(timeout=180)
        self.war_stamp = war_stamp

    @discord.ui.button(label="Home Faction", style=discord.ButtonStyle.primary)
    async def home_fac_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        doc = await bot.factions_col.find_one({"war_stamp": self.war_stamp, "status": "home"})
        if doc:
            content = f"**Home Faction**\nName: {doc.get('name')}\nMembers: {doc.get('count')}\nLeader: {doc.get('leader')}\nCo-Leader: {doc.get('co')}\n\n**Roster:**\n"
            roster = []
            for i in range(1, doc.get('count', 0) + 1):
                mem_key = f"member{i}"
                if mem_key in doc:
                    roster.append(doc[mem_key])
            
            roster_text = ", ".join(roster)
            if len(roster_text) > 1700:
                roster_text = roster_text[:1700] + " ... [Truncated]"
            content += roster_text
        else:
            content = "Data not found."
        await interaction.response.edit_message(content=content, view=GenericBackView(self.war_stamp))

    @discord.ui.button(label="Enemy Faction", style=discord.ButtonStyle.danger)
    async def enemy_fac_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        doc = await bot.factions_col.find_one({"war_stamp": self.war_stamp, "status": "enemy"})
        if doc:
            content = f"**Enemy Faction**\nName: {doc.get('name')}\nMembers: {doc.get('count')}\nLeader: {doc.get('leader')}\nCo-Leader: {doc.get('co')}\n\n**Roster:**\n"
            roster = []
            for i in range(1, doc.get('count', 0) + 1):
                mem_key = f"member{i}"
                if mem_key in doc:
                    roster.append(doc[mem_key])
            
            roster_text = ", ".join(roster)
            if len(roster_text) > 1700:
                roster_text = roster_text[:1700] + " ... [Truncated]"
            content += roster_text
        else:
            content = "Data not found."
        await interaction.response.edit_message(content=content, view=GenericBackView(self.war_stamp))
        
    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"**Details Menu:** {self.war_stamp}", view=ArchiveDetailsMenuView(self.war_stamp))

class ArchiveMemberSelect(discord.ui.Select):
    def __init__(self, profiles, war_stamp):
        self.war_stamp = war_stamp
        self.profiles_map = {p["player_id"]: p for p in profiles}
        options = [
            discord.SelectOption(label=p["name"], value=p["player_id"])
            for p in profiles[:25]
        ]
        super().__init__(placeholder="Select a player...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        player_id = self.values[0]
        p = self.profiles_map[player_id]
        stats_text = (
            f"**Name:** {p.get('name')}\n"
            f"**Level:** {p.get('level')}\n"
            f"**Attacks Won:** {p.get('attacks_won')}\n"
            f"**Defends Won:** {p.get('defends_won')}\n"
            f"**RP Gained (Inside):** {p.get('rp_gained_inside')}\n"
            f"**Outside Hits:** {p.get('outside_hits')}"
        )
        await interaction.response.edit_message(content=stats_text, view=GenericBackView(self.war_stamp))

class ArchiveMemberSelectView(discord.ui.View):
    def __init__(self, profiles, war_stamp):
        super().__init__(timeout=180)
        self.war_stamp = war_stamp
        self.add_item(ArchiveMemberSelect(profiles, war_stamp))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"**Details Menu:** {self.war_stamp}", view=ArchiveDetailsMenuView(self.war_stamp))

class ArchiveDetailsMenuView(discord.ui.View):
    def __init__(self, war_stamp):
        super().__init__(timeout=180)
        self.war_stamp = war_stamp

    @discord.ui.button(label="Members", style=discord.ButtonStyle.primary)
    async def members_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        profiles = await bot.archived_profiles_col.find({"war_stamp": self.war_stamp}).to_list(length=100)
        if not profiles:
            await interaction.response.send_message("No members found.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Select a member:", view=ArchiveMemberSelectView(profiles, self.war_stamp))

    @discord.ui.button(label="Statistics", style=discord.ButtonStyle.primary)
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        profiles = await bot.archived_profiles_col.find({"war_stamp": self.war_stamp}).to_list(length=100)
        war_doc = await bot.archives_col.find_one({"_id": self.war_stamp})
        
        if not profiles:
            await interaction.response.send_message("No data found.", ephemeral=True)
            return
            
        total_hits = sum(p.get("inside_hits", 0) + p.get("outside_hits", 0) for p in profiles)
        most_hits_p = max(profiles, key=lambda p: p.get("inside_hits", 0) + p.get("outside_hits", 0), default={})
        most_rp_p = max(profiles, key=lambda p: p.get("rp_gained_inside", 0) + p.get("rp_gained_outside", 0), default={})
        most_outside_p = max(profiles, key=lambda p: p.get("outside_hits", 0), default={})
        
        ending_score = war_doc.get("ending_score", "Unknown") if war_doc else "Unknown"

        content = (
            f"**Statistics for {self.war_stamp}**\n"
            f"Ending Score: {ending_score}\n"
            f"Total Hits Made: {total_hits}\n"
            f"Most Hits: {most_hits_p.get('name', 'N/A')}\n"
            f"Most RP: {most_rp_p.get('name', 'N/A')}\n"
            f"Most Outside Hits: {most_outside_p.get('name', 'N/A')}"
        )
        await interaction.response.edit_message(content=content, view=GenericBackView(self.war_stamp))

    @discord.ui.button(label="Enemy Statistics", style=discord.ButtonStyle.primary)
    async def enemy_stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        enemy_stat = await bot.archived_enemy_stats_col.find_one({"war_stamp": self.war_stamp})
        if not enemy_stat:
            await interaction.response.send_message("No enemy stats found for this war.", ephemeral=True)
            return
        content = (
            f"**Enemy Statistics**\n"
            f"Total Hits: {enemy_stat.get('total_hits')}\n"
            f"Most Hits: {enemy_stat.get('most_hits')}\n"
            f"Most RP: {enemy_stat.get('most_rp')}"
        )
        await interaction.response.edit_message(content=content, view=GenericBackView(self.war_stamp))

    @discord.ui.button(label="Faction Profiles", style=discord.ButtonStyle.primary)
    async def factions_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Select faction profile to view:", view=FactionChoiceView(self.war_stamp))

    @discord.ui.button(label="Home", style=discord.ButtonStyle.danger)
    async def home_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="**Dashboard**", view=MainDashboardView())

class WarReportView(discord.ui.View):
    def __init__(self, war_stamp, war_doc):
        super().__init__(timeout=180)
        self.war_stamp = war_stamp
        self.war_doc = war_doc

    @discord.ui.button(label="Details", style=discord.ButtonStyle.primary)
    async def details_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"**Details Menu:** {self.war_stamp}", view=ArchiveDetailsMenuView(self.war_stamp))
        
    @discord.ui.button(label="Home", style=discord.ButtonStyle.danger)
    async def home_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="**Dashboard**", view=MainDashboardView())

class ArchiveSelect(discord.ui.Select):
    def __init__(self, archives):
        options = [
            discord.SelectOption(label=str(doc["_id"]), description="Archived War Report", emoji="📜")
            for doc in archives
        ]
        super().__init__(placeholder="Choose a war to review...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_val = self.values[0]
        war_doc = await bot.archives_col.find_one({"_id": selected_val})
        
        report_text = f"**War Report: {selected_val}**\nEnemy: {war_doc.get('enemy_name')}\nWinner: {war_doc.get('victor', 'N/A')}\nMVP: {war_doc.get('mvp', 'N/A')}"
        
        await interaction.response.edit_message(content=report_text, view=WarReportView(selected_val, war_doc))

class ArchiveSelectView(discord.ui.View):
    def __init__(self, archives):
        super().__init__(timeout=180)
        self.add_item(ArchiveSelect(archives))
        
    @discord.ui.button(label="Home", style=discord.ButtonStyle.danger, row=1)
    async def home_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="**Dashboard**", view=MainDashboardView())

class MainDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 

    @discord.ui.button(label="Current War", style=discord.ButtonStyle.primary, custom_id="btn_current", emoji="⚔️")
    async def current_war_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        active_war = await bot.war_col.find_one({"status": "active"})
        if not active_war:
            await interaction.response.send_message("There is no active ranked war currently logged in the database.", ephemeral=True)
            return
            
        await interaction.response.send_message(f"Displaying current war interface for: **{str(active_war['_id'])}**", ephemeral=True)

    @discord.ui.button(label="War Archives", style=discord.ButtonStyle.secondary, custom_id="btn_archives", emoji="📚")
    async def archives_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        archives = await bot.archives_col.find().sort("end_time", -1).limit(25).to_list(length=25)
        if not archives:
            await interaction.response.send_message("The archives are empty. No historical wars found.", ephemeral=True)
            return
            
        view = ArchiveSelectView(archives)
        await interaction.response.edit_message(content="Select a historical war report from the dropdown below:", view=view)

@bot.tree.command(name="call", description="Summon the war tracker dashboard")
async def call_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**Dashboard**\nHello there! How can I help you today?", 
        view=MainDashboardView(),
        ephemeral=True
    )

@bot.tree.command(name="help", description="Learn about the bot's purpose and commands")
async def help_command(interaction: discord.Interaction):
    quote = random.choice(WAR_QUOTES)
    
    response = (
        f"*{quote}*\n\n"
        "**Faction War Archivist**\n"
        "I am an automated ledger designed to silently track, record, and preserve our faction's ranked wars. "
        "I monitor the Torn API and safely log every attack, defense, and respect shift into the database.\n\n"
        "**Available Commands:**\n"
        "**`/call`** - Wakes me up and opens the interactive dashboard to view live wars or pull historical reports.\n"
        "**`/help`** - Displays this informational message."
    )
    
    await interaction.response.send_message(response)

keep_alive()
bot.run(TOKEN)