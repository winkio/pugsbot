import os
import random
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from enum import IntEnum
import math

import discord
from discord.ext import commands
from discord.ui import View, Button
from dotenv import load_dotenv

# Load the bot token from the .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class GameMap():
    def __init__(self, name, emoji):
        self.name = name
        self.emoji = emoji
    def __str__(self):
        return f'{self.name} {self.emoji}'

# Constants for settings
bot_activity = discord.Activity(type=discord.ActivityType.playing, name="Gigantic PUGs")
ready_up_time = 90  # Set the ready-up time to 90 seconds
queue_size_required = 10  # 10 players required for 5v5
team_size = queue_size_required // 2 # // is integer division, / is float division which gives a float
reset_queue_votes_required = 4  # Require 4 votes to reset the queue
votes_required = 5  # Require 5 votes to pick maps, matchups, or re-roll
map_total_votes_required = 7  # Require 7 total votes to choose a map
save_file_path = 'stored_pug.txt'  # Stores saved PUG data to load on next startup
msg_fade1 = 8  # very simple ephemeral messages auto-delete after 8 seconds
msg_fade2 = 30  # simple ephemeral messages auto-delete after 30 seconds
vote_pip = '\u25c9 '  # pip to use when displaying votes
vote_win_pip = '✅ '  # pip to use when displaying votes for the winning option
map_choices = [  # List of GameMap objects describing maps
    GameMap('Ghost Reef', '🏜️'), 
    GameMap('Sirens Strand', '🧊'), 
    GameMap('Sanctum Falls', '🌊'), 
    GameMap('Ember Grove', '🌲'), 
    GameMap('Sky City', '☁️')
]
ready_dm_messages = [  # List of random messages to send when ready up begins
    "The queue is full. Go Ready Up!",
    "It's time for server set-up simulator, go ready up!",
    "Go ready up for PUGs or have another 30 minutes of queue time!",
    "The PUGs queue is full. Go to the server and Ready Up!",
    "It's time for Giggin, go ready up!"
]
queue_kill_comments = {
    1: 'Queue-bait',
    2: 'Queue-lapse',
    3: 'Queue-logy',
    4: 'Queue-thanasia',
    5: 'Queue-genics',
    6: 'Queue-splosion',
    7: 'Queue-tastrophy',
    8: 'Queue-lamity',
    9: 'Queue-pocalypse',
    10: 'Queue-termination'
}

# Constants used elsewhere in code
divider = '——————————————————————————'  # divider string for votes
reroll_key = 'reroll'  # key for reroll votes in votes dict
custom_teams_key = 'custom'  # key for custom votes in votes dict
command_help = {  # Help info for commands
    'mh': '!mh - gets a search string to view your match history in discord',
    'ct1': '!ct1 - use with user names to set Team 1 for Custom teams',
    'ct2': '!ct2 - use with user names to set Team 2 for Custom teams',
    's7': '!s7 - show the server join commands for syco.servegame.com port 7777',
    's8': '!s8 - show the server join commands for syco.servegame.com port 7778',
    's9': '!s9 - show the server join commands for syco.servegame.com port 7779',
    's0': '!s0 - show the server join commands for syco.servegame.com port 7780',
    'sb': '''!sb - use with an attached image to set the scoreboard of the current 
     match, can also pass in the remaining wounds to set it at the 
     same time ex. !sb -1''',
    'wounds': '''!wounds - use with a number to indicate which team won the current
         match and how many wounds, + for Team1 win, - for Team2 win:
         !wounds 2    (Team 1 won the match with 2 wounds remaining)
         !wounds -3   (Team 2 won the match with 3 wounds remaining)'''
}

# Set up the bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # To access member information

bot = commands.Bot(command_prefix='!', intents=intents)

# gets a timestamp to use when logging
def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@bot.event
async def on_ready():
    if bot_activity:
        await bot.change_presence(status=discord.Status.online, activity=bot_activity)
    else:
        await bot.change_presence(status=discord.Status.online)
    print(f'{get_timestamp()} - Logged in as {bot.user.name}')

class Phase(IntEnum): # Phase enum
    NONE = 1
    QUEUE = 2
    READY = 3
    MAP = 4
    MATCHUP = 5
    PLAY = 6
    RESET = 7
   
# Global variables to keep track of the queue and game states
phase = Phase.NONE
queue = []  # Players in queue
waiting_room = []  # Players in waiting room
re_queue = []  # Players re-queueing after current match
match_number = 1  # Match number
game_in_progress = False
queue_message = None

queue_sorted = []
ready_players = set()
bailouts_unc = []  # Players who have clicked bailout once but not confirmed
bailouts = []  # Players who are bailing out
standby = []  # Players on standby to fill for players that do not ready up
ready_start = None  # for storing the timestamp of the start of the ready up countdown
ready_end = None  # for storing the timestamp of the end of the ready up countdown
ready_up_timed_out = False  # Track if the ready up timer reached zero
all_ready_sent = False  # Track if the all players ready has been sent
ready_message = None  # To store the ready-up message
ready_up_task = None  # For tracking the countdown task

map_votes = defaultdict(int)
map_voted_users = {}  # Track individual votes for changeable votes
selected_map = None  # To store the selected map
selected_map_sent = False # Track if the selected map has already been sent
map_voting_message = None  # To store the map voting message

matchups = []
custom_team1 = []  # custom team 1 users
custom_team2 = []  # custom team 2 users
votes = defaultdict(int)
voted_users = {}  # Track individual votes for changeable votes
selected_matchup = None  # To store the selected matchup
final_matchup_sent = False  # Track if the final matchup has already been sent
voting_message = None

final_matchup_players = set()  # Players in the final matchup
final_team1_names = None
final_team2_names = None
final_matchup_start = None
final_matchup_end = None
scoreboard_filename = None
final_matchup_score = 0
reset_queue_votes = 0
reset_voted_users = set()
reset_in_progress = False  # Flag to prevent multiple resets
final_matchup_message = None  # For the final matchup message
waiting_room_message = None  # For the waiting room message


# Helper function to reset the game state but keep the waiting room intact
def reset_game():
    global phase, queue, game_in_progress, queue_message
    global queue_sorted, ready_players, bailouts_unc, bailouts, standby, ready_start, ready_end, ready_up_timed_out, all_ready_sent, ready_message, ready_up_task
    global map_votes, map_voted_users, selected_map, selected_map_sent, map_voting_message
    global matchups, custom_team1, custom_team2, votes, voted_users, selected_matchup, final_matchup_sent, voting_message
    global final_matchup_players, final_team1_names, final_team2_names, final_matchup_start, final_matchup_end, scoreboard_filename, final_matchup_score, reset_queue_votes, reset_voted_users, reset_in_progress, final_matchup_message
    phase = Phase.QUEUE
    queue = []
    # waiting_room is not reset
    # re_queue is not reset
    game_in_progress = False
    queue_message = None
    
    queue_sorted = []
    ready_players = set()
    bailouts_unc = []
    bailouts = []
    standby = []
    ready_start = None
    ready_end = None
    ready_up_timed_out = False
    all_ready_sent = False
    ready_message = None
    if ready_up_task is not None:  # Cancel the countdown task if it's running
        ready_up_task.cancel()
        ready_up_task = None
    
    map_votes = defaultdict(int)
    map_voted_users = {}
    selected_map = None
    selected_map_sent = False
    map_voting_message = None
    
    matchups = []
    custom_team1 = []
    custom_team2 = []
    votes = defaultdict(int)
    voted_users = {}
    selected_matchup = None
    final_matchup_sent = False
    voting_message = None
    
    final_matchup_players = set()
    final_team1_names = None
    final_team2_names = None
    final_matchup_start = None
    final_matchup_end = None
    scoreboard_filename = None
    final_matchup_score = 0
    reset_queue_votes = 0
    reset_voted_users = set()
    reset_in_progress = False
    final_matchup_message = None
    # waiting_room_message is not reset


# Helper function to get a user's preferred display name
def get_display_name(user):
    return user.nick or user.display_name or user.name
    
# Helper function to get a case insensitve key to sort users
def user_sort_key(user):
    return str.casefold(get_display_name(user))

# converts a datetime to an integer number of seconds (offset)
def datetime_to_int(dt):
    return int(dt.timestamp())

# Function to make the queue embed
def queue_embed():
    queue_names = ', '.join([get_display_name(user) for user in queue]) or 'No players in queue.'
    if phase < Phase.PLAY:
        embed = discord.Embed(title='PUGs Queue', color=discord.Color.blue())
        if phase <= Phase.READY:
            embed.add_field(name=f'In Queue ({len(queue)}/{queue_size_required})', value=queue_names, inline=False)
        else:
            embed.add_field(name=f'Setting Up Match #{match_number}', value=queue_names, inline=False)
        
        if waiting_room:
            waiting_names = ', '.join([get_display_name(user) for user in waiting_room])
            embed.add_field(name=f'Waiting Room ({len(waiting_room)})', value=waiting_names, inline=False)
        if re_queue and phase > Phase.READY:
            re_queue_names = ', '.join([get_display_name(user) for user in re_queue])
            embed.add_field(name=f'Re-Queueing ({len(re_queue)})', value=re_queue_names, inline=False)
    else:
        embed = discord.Embed(title=f'PUGs Match #{match_number}', description=queue_names, color=discord.Color.blue())
    return embed

# View for the join/leave queue buttons
class QueueView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Join Queue', style=discord.ButtonStyle.green)
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):          
        await handle_queue_join(interaction)

    @discord.ui.button(label='Leave Queue', style=discord.ButtonStyle.red)
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_queue_leave(interaction)
    
    @discord.ui.button(label='Match History', style=discord.ButtonStyle.grey)
    async def match_history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await reply_with_match_history(interaction)
    
    @discord.ui.button(label='Help', style=discord.ButtonStyle.grey)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await reply_with_help(interaction)

# Function to handle when a user clicks a join button for queue or waiting room
async def handle_queue_join(interaction: discord.Interaction):
    user = interaction.user
    if user in re_queue:
        await interaction.response.send_message('You are already set to re-queue.', ephemeral=True, delete_after=msg_fade1)
        return
    if user in waiting_room:
        await interaction.response.send_message('You are already in the waiting room.', ephemeral=True, delete_after=msg_fade1)
        return
    elif user in queue:
        if phase > Phase.READY: # if past the ready phase, set player to re-queue
            re_queue.append(user)
            await interaction.response.send_message(f'{user.mention} is set to re-queue!', ephemeral=True, delete_after=msg_fade2)
        else:
            await interaction.response.send_message('You are already in the queue.', ephemeral=True, delete_after=msg_fade1)
            return
    else:  # user not in queue or waiting room yet
        if len(queue) < queue_size_required:  # if room in the queue add the user
            queue.append(user)
            await interaction.response.send_message(f'{user.mention} joined the queue!', ephemeral=True, delete_after=msg_fade2)
        else:  # otherwise add to waiting room
            waiting_room.append(user)
            await interaction.response.send_message(f'{user.mention} joined the waiting room!', ephemeral=True, delete_after=msg_fade2)
    
    if phase == Phase.PLAY:
        await update_waiting_room_message()
    else:
        await update_queue_message()
    
# Function to handle when a user clicks a leave button for queue or waiting room
async def handle_queue_leave(interaction: discord.Interaction):
    user = interaction.user
    if user in re_queue:
        re_queue.remove(user)
        await interaction.response.send_message(f'{user.mention} will not re-queue!', ephemeral=True, delete_after=msg_fade2)
    elif user in waiting_room:
        if phase == Phase.READY and user in standby:
            await interaction.response.send_message('You cannot leave the queue while on Standby.', ephemeral=True, delete_after=msg_fade1)
            return
        waiting_room.remove(user)
        await interaction.response.send_message(f'{user.mention} left the waiting room!', ephemeral=True, delete_after=msg_fade2)
    elif user in queue:
        if phase > Phase.READY: # if past the ready phase, player is already set to NOT re-queues:
            await interaction.response.send_message('You already will not re-queue.', ephemeral=True, delete_after=msg_fade1)
            return
        if phase == Phase.READY:
            await interaction.response.send_message('You cannot leave the queue during Ready Up.', ephemeral=True, delete_after=msg_fade1)
            return
        queue.remove(user)
        await interaction.response.send_message(f'{user.mention} left the queue.', ephemeral=True, delete_after=msg_fade2)
    else:
        await interaction.response.send_message('You are not in the queue.', ephemeral=True, delete_after=msg_fade1)
        return
    
    if phase >= Phase.PLAY:
        await update_waiting_room_message()
    else:
        await update_queue_message()

# Replies to a user with a match history message
async def reply_with_match_history(interaction: discord.Interaction):
    msg = match_history_block(interaction.user)
    await interaction.response.send_message(msg, ephemeral=True, delete_after=msg_fade2)
   
# Replies to a user with a help message
async def reply_with_help(interaction: discord.Interaction):
    msg = f' Commands\n{command_help_block()}'
    await interaction.response.send_message(msg, ephemeral=True)

# Function to get the total number of players in queue + waiting room
def total_queue_size():
    if phase >= Phase.PLAY:
        return len(waiting_room) + len(re_queue)
    return len(queue) + len(waiting_room)

# Function to update the queue message (editing the original message)
async def update_queue_message():
    global queue_message
    embed = queue_embed()

    if queue_message:
        if phase >= Phase.PLAY:
            await queue_message.edit(embed=embed, view=None)  # Remove the buttons once the match is in progress
        else:
            await queue_message.edit(embed=embed)
    else:
        queue_message = await bot.get_channel(queue_message.channel.id).send(embed=embed, view=QueueView())

    # If we have the required number of players, move to ready check
    if phase == Phase.QUEUE:
        await check_full_queue()

# Function that checks if we have the required number of players, and if so moves to ready check
async def check_full_queue():
    global game_in_progress
    if len(queue) == queue_size_required and not game_in_progress:
        game_in_progress = True
        await start_ready_check(queue_message.channel)

# Function to start the ready check
async def start_ready_check(channel):
    global phase, queue_sorted, ready_players, bailouts_unc, bailouts, standby, ready_start, ready_end, ready_up_task
    phase = Phase.READY
    ready_players = set()
    bailouts_unc = []
    bailouts = []
    standby = []  

    # Gather all player mentions
    mentions = ' '.join([user.mention for user in queue])

    # Send a message pinging all players that the queue has popped
    await channel.send(f"The queue is full with {len(queue)} players! {mentions} please ready up!")

    # Send a DM to each player in the queue with a random message
    for user in queue:
        try:
            random_message = random.choice(ready_dm_messages)  # Select a random message
            await user.send(random_message)
        except discord.Forbidden:
            print(f"Could not DM {user} due to privacy settings.")

    # create sorted queue
    queue_sorted = list(queue)
    queue_sorted.sort(key=user_sort_key)

    # Get start and end times
    ready_start = datetime.now(timezone.utc)
    ready_end = ready_start + timedelta(seconds=ready_up_time)

    # Start the ready-up process and display the message
    await display_ready_up(channel)

    # Start the ready-up timer task
    ready_up_timed_out = False
    ready_up_task = asyncio.create_task(countdown_ready_up(channel))

# Function to display the ready-up message
async def display_ready_up(channel):
    global ready_message
    embed = ready_up_embed()

    # Send the ready-up message and store its reference
    if ready_message:
        await ready_message.edit(embed=embed)
    else:
        ready_message = await channel.send(embed=embed, view=ReadyUpView())

# Function to update the ready-up message (players and timer)
async def update_ready_up_message():
    if ready_message:
        embed = ready_up_embed()
        await ready_message.edit(embed=embed)

# Gets a killstreak string for the number of non-ready players
def queue_killstreak_str(num):
    if num in queue_kill_comments:
        return f'***{queue_kill_comments[num]}*** {"💀" * num}'
    return f'Not all players were ready.'

# Countdown timer for the ready-up phase
async def countdown_ready_up(channel):
    global ready_up_timed_out
    #  Wait the full duration, since we now have a timestamp that counts down automatically
    await asyncio.sleep(ready_up_time)
    # Timeout reached: proceed with ready players or reset queue
    ready_up_timed_out = True
    await end_ready_up(channel)

# Ends a ready up phase, called when either the timer runs out or all players have readied/bailed
async def end_ready_up(channel):
    global phase, queue, waiting_room, game_in_progress, queue_message, ready_players, all_ready_sent, ready_message
    if phase != Phase.READY or all_ready_sent:
        return
    all_ready_sent = True
        
    non_ready_players = [user for user in queue if user not in ready_players]
    num_ready = len(ready_players)
    num_non_ready = len(non_ready_players)
    # remove non-ready players from queue
    queue = [user for user in queue if user in ready_players]
    
    # If enough on standby to fill queue
    if len(standby) >= num_non_ready:
        if num_non_ready > 0:
            fills = standby[:num_non_ready]
            mentions = ' '.join([user.mention for user in fills])
            # move users from standby to queue
            queue.extend(fills)
            ready_players = set(queue)
            # remove queued players from waiting room
            waiting_room = [user for user in waiting_room if user not in queue]
            await channel.send(f"Standby players have joined the match: {mentions}.  Thank you for filling in!")
        await proceed_to_map_voting(channel)
        return
    
    # Ready up failed, move users from waiting room to queue
    queue.extend(waiting_room[:num_non_ready])
    del waiting_room[:num_non_ready]
    ready_players.clear()  # Clear the ready players set for the next ready check
    bailouts_unc.clear()
    bailouts.clear()
    standby.clear()
    # Start new queue to trigger a new ready check
    phase = Phase.QUEUE
    game_in_progress = False
    all_ready_sent = False
    await channel.send(f"{queue_killstreak_str(num_non_ready)} Re-queuing {num_ready} ready players.")
    ready_message = await remove_message(ready_message)
    queue_message = await remove_message(queue_message)
    await start_new_queue(channel)  # Post a new queue message with ready players

# gets a string with the queue icon and display name of a user in the queue
def queue_icon_name(user):
    if user in ready_players:
        return f'✅ {get_display_name(user)}'
    if user in bailouts:
        return f'❌ {get_display_name(user)}'
    return f'⌛ {get_display_name(user)}'

# Function to make the ready up embed
def ready_up_embed():
    queue_names = '\n'.join([queue_icon_name(user) for user in queue_sorted])

    embed = discord.Embed(title='Match Found!',
                          description='Please ready up!  Players in the waiting room can standby to fill.',
                          color=discord.Color.green())
    embed.add_field(name=f'Match Players ({len(ready_players)}/{queue_size_required})', value=queue_names, inline=True)
    if standby:
        standby_names = '\n'.join([get_display_name(user) for user in standby]) or '\u200b'
        embed.add_field(name=f'On Standby ({len(standby)}/{queue_size_required - len(ready_players)})', value=standby_names, inline=True)
    embed.add_field(name='\u200b', value=f'-# Expires: <t:{datetime_to_int(ready_end)}:R>', inline=False)
    return embed

# View for the ready up button
class ReadyUpView(View):
    def __init__(self):
        super().__init__(timeout=None)  # No timeout here, handled by countdown

    @discord.ui.button(label='Ready Up / Standby', style=discord.ButtonStyle.green)
    async def ready_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        global standby, all_ready_sent
        user = interaction.user
        if user in queue:
            if user in ready_players:
                await interaction.response.send_message('You are already ready.', ephemeral=True, delete_after=msg_fade1)
                return
            if user in bailouts:
                await interaction.response.send_message('Cannot ready after clicking bail out.', ephemeral=True, delete_after=msg_fade1)
                return
            
            if user in bailouts_unc:
                bailouts_unc.remove(user)
            ready_players.add(user)
            await interaction.response.send_message(f'{user.mention} is ready!', ephemeral=True, delete_after=ready_up_time)
            await update_ready_up_message()  # Update the ready-up message with new players
            await check_ready_complete(interaction.message.channel)
        else:
            if user in standby:
                await interaction.response.send_message('You are already on standby.', ephemeral=True, delete_after=msg_fade1)
                return
            if user not in waiting_room:
                waiting_room.append(user)
                await update_queue_message()
            # add user to standby list and order standby list by waiting room
            standby.append(user)
            standby = [user for user in waiting_room if user in standby]
            await interaction.response.send_message(f'{user.mention} is on standby!', ephemeral=True, delete_after=ready_up_time)
            await update_ready_up_message()
            await check_ready_complete(interaction.message.channel)
            
    @discord.ui.button(label='Bail Out', style=discord.ButtonStyle.red)
    async def bail_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user in ready_players or user in standby:
            await interaction.response.send_message('Cannot bail out after clicking ready.', ephemeral=True, delete_after=msg_fade1)
        elif user in queue:
            if user not in bailouts_unc:
                bailouts_unc.append(user)
                await interaction.response.send_message('Are you sure you want to bail out?  Click again to confirm.', ephemeral=True, delete_after=ready_up_time)
            else:
                bailouts_unc.remove(user)
                bailouts.append(user)
                await interaction.response.send_message(f'{user.mention} is bailing out!', ephemeral=True, delete_after=ready_up_time)
                await update_ready_up_message()
                await check_ready_complete(interaction.message.channel)
        else:
            await interaction.response.send_message('You are not in the queue.', ephemeral=True, delete_after=msg_fade1)

# checks if enough players have readied for the queue to go through
async def check_ready_complete(channel):
    num_non_ready = queue_size_required - len(ready_players)
    if num_non_ready == 0:  # if all users are ready
        await end_ready_up(channel)
        return
    # if all non-ready are bailing out, make sure that there are enough
    # players on standby and that they are all at the top of the waiting room
    if (num_non_ready == len(bailouts) and
        len(standby) >= num_non_ready and
        standby[:num_non_ready] == waiting_room[:num_non_ready]):  
        await end_ready_up(channel)

# New function to proceed to map voting
async def proceed_to_map_voting(channel):
    global phase, re_queue, queue_message, ready_message, map_votes, map_voted_users, map_voting_message, ready_up_task
    phase = Phase.MAP
    # Cancel the ready-up task to prevent it from running after this point
    if not ready_up_timed_out and ready_up_task is not None:
        ready_up_task.cancel()
        ready_up_task = None

    ready_message = await remove_message(ready_message)
    # Send a completely new queue message instead of editing the old one
    queue_message = await remove_message(queue_message)
    embed = queue_embed()
    queue_message = await channel.send(embed=embed, view=QueueView())
    # set all ready players to requeue by default, but in a random order
    re_queue = list(ready_players)
    random.shuffle(re_queue)

    map_votes.clear()  # Clear votes only at the start of new matchups
    map_voted_users.clear()  # Reset users who voted
    map_voting_message = None

    embed = map_voting_embed()

    # Send the message with the MapVotingView
    map_voting_message = await channel.send(embed=embed, view=MapVotingView())

# gets the vote pip string for a given map
def map_vote_pips(game_map: GameMap):
    if game_map == selected_map:
        return f'\u200b{vote_win_pip * map_votes[game_map]}'
    return f'\u200b{vote_pip * map_votes[game_map]}'

# Function to make the map voting embed
def map_voting_embed():
    embed = discord.Embed(title='Map Vote', 
                          #description='Vote for the map you want to play on.', 
                          color=discord.Color.green())
    for game_map in map_choices:
        embed.add_field(name=str(game_map), value=map_vote_pips(game_map), inline=True)
    # add extra empty fields so that there are 3 fields per row
    for _ in range(-len(map_choices) % 3):
        embed.add_field(name='\u200b', value='\u200b', inline=True)
    
    return embed

# Class for map voting
class MapVotingView(View):
    def __init__(self):
        super().__init__(timeout=None)
        for game_map in map_choices:
            button = Button(label=str(game_map), style=discord.ButtonStyle.primary, custom_id=game_map.name)
            button.callback = self.make_callback(game_map)
            self.add_item(button)

    def make_callback(self, game_map):
        async def callback(interaction: discord.Interaction):
            await self.register_map_vote(interaction, game_map)
        return callback

    async def register_map_vote(self, interaction, game_map):
        global map_votes, map_voted_users, selected_map, selected_map_sent
        # do nothing if no longer in map voting phase
        if phase != Phase.MAP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True, delete_after=msg_fade1)
            return
        
        user = interaction.user

        if user not in ready_players:
            await interaction.response.send_message('You are not part of the match.', ephemeral=True, delete_after=msg_fade1)
            return

        # Allow user to change their vote
        if user in map_voted_users:
            map_previous_vote = map_voted_users[user]
            if map_previous_vote == game_map:
                await interaction.response.send_message(f'You have already voted for {game_map}.', ephemeral=True, delete_after=msg_fade1)
                return
            else:
                map_votes[map_previous_vote] -= 1  # Remove their previous map vote

        map_votes[game_map] += 1
        map_voted_users[user] = game_map
        await interaction.response.send_message(f'You voted for {game_map}.', ephemeral=True, delete_after=msg_fade2)

        # Update the voting message
        await update_map_voting_message()

        # Check if the map has 5 votes (for 5v5)
        if (map_votes[game_map] >= votes_required) and not selected_map_sent:
            selected_map_sent = True
            selected_map = game_map
            await declare_selected_map(interaction.message.channel)
        # Check if 7 votes have been cast
        elif len(map_voted_users) >= map_total_votes_required and not selected_map_sent:
            selected_map_sent = True
            # Determine the map(s) with the most votes (in case of tie)
            max_votes = max(map_votes.values())
            top_maps = [gm for gm, count in map_votes.items() if count == max_votes]
            selected_map = random.choice(top_maps)  # If tie, select randomly among top maps
            await declare_selected_map(interaction.message.channel)
            

# Function to update the map voting message
async def update_map_voting_message():
    if map_voting_message:
        embed = map_voting_embed()
        if phase != Phase.MAP:
            await map_voting_message.edit(embed=embed, view=None)  # remove buttons if not voting
        else:
            await map_voting_message.edit(embed=embed)

# Function to declare the selected map and proceed to matchups
async def declare_selected_map(channel):
    await proceed_to_matchups_phase(channel)
    await update_map_voting_message()  # final update of map vote message

# Adjusted function to proceed to matchups
async def proceed_to_matchups_phase(channel):
    global phase, matchups, votes, voted_users, voting_message
    phase = Phase.MATCHUP
    players = list(ready_players)
    unique_team_ids = set()
    # if team size is greater than 2, avoid rerolling a team from the last set of matchups
    if team_size > 2 and matchups:
        for team1, team2 in matchups:
            team1_ids = ' '.join([str(user.id) for user in team1])
            team2_ids = ' '.join([str(user.id) for user in team2])
            unique_team_ids.add(team1_ids)
            unique_team_ids.add(team2_ids)
            
    # clear old matchups and votes
    matchups = []
    votes.clear()  # Clear votes only at the start of new matchups
    voted_users.clear()  # Reset users who voted

    # Generate matchups for 5v5
    while len(matchups) < 3:
        random.shuffle(players)
        team1 = players[:team_size]  # 5 players on team 1
        team2 = players[team_size:]  # 5 players on team 2
        team1.sort(key=user_sort_key)
        team2.sort(key=user_sort_key)
        team1_ids = ' '.join([str(user.id) for user in team1])
        team2_ids = ' '.join([str(user.id) for user in team2])
        # check to make sure that generated matchup is unique before adding it
        if team1_ids not in unique_team_ids:
            unique_team_ids.add(team1_ids)
            unique_team_ids.add(team2_ids)
            matchups.append((team1.copy(), team2.copy()))
            
    # Display the matchups
    await display_matchup_votes(channel)

# Gets a string representation of the matchup    
def get_matchup_str(m):
    if m == reroll_key:
        return 'Re-roll Matchups'
    if m == custom_teams_key:
        return 'Custom matchup'
    return f'Matchup {m}'

# gets the vote pip string for a given matchup
def matchup_vote_pips(m):
    if m == selected_matchup:
        return f' {vote_win_pip * votes[m]}'
    return f' {vote_pip * votes[m]}'

# Function to display the voting embed with votes count and enhanced readability
async def display_matchup_votes(channel):
    global voting_message
    if phase == Phase.MATCHUP:
        embed = discord.Embed(title='Matchup Vote', description='Vote for your preferred matchup or vote to re-roll.',
                              color=discord.Color.green())
    else:
        embed = discord.Embed(title='Matchup Vote', color=discord.Color.green())

    for idx, (team1, team2) in enumerate(matchups, 1):
        embed.add_field(name=divider,
                        value=f'**Matchup {idx}**{matchup_vote_pips(idx)}',
                        inline=False)
        team1_names = '\n'.join([get_display_name(user) for user in team1])
        team2_names = '\n'.join([get_display_name(user) for user in team2])
        embed.add_field(name='Team 1', value=team1_names, inline=True)
        embed.add_field(name='Team 2', value=team2_names, inline=True)

    # Clearer re-roll option with votes
    if phase == Phase.MATCHUP:
        reroll_text = f'**Re-roll Matchups**{matchup_vote_pips(reroll_key)}\nVote to re-roll all matchups and generate new ones.'
    elif votes[reroll_key]:
        reroll_text = f'**Re-roll Matchups**{matchup_vote_pips(reroll_key)}'
    else:
        reroll_text = ''
    if reroll_text:
        embed.add_field(name=divider, value=reroll_text, inline=False)

    # Custom teams
    if phase == Phase.MATCHUP:
        custom_teams_text = f'**Custom**{matchup_vote_pips(custom_teams_key)}\nUse !ct1 and !ct2 to set custom teams.'
    elif votes[custom_teams_key] or custom_team1 or custom_team2:
        custom_teams_text = f'**Custom**{matchup_vote_pips(custom_teams_key)}'
    else:
        custom_teams_text = ''
    if custom_teams_text:
        embed.add_field(name=divider, value=custom_teams_text, inline=False)
        if custom_team1 or custom_team2:
            team1_names = '\n'.join([get_display_name(user) for user in custom_team1])
            team2_names = '\n'.join([get_display_name(user) for user in custom_team2])
            embed.add_field(name='Team 1', value=team1_names, inline=True)
            embed.add_field(name='Team 2', value=team2_names, inline=True)

    # If the voting message exists, edit it, otherwise send a new one
    if voting_message:
        if phase != Phase.MATCHUP:
            await voting_message.edit(embed=embed, view=None)
        else:
            await voting_message.edit(embed=embed)
    else:
        voting_message = await channel.send(embed=embed, view=VotingView())

# View for voting on matchups
class VotingView(View):
    def __init__(self):
        super().__init__(timeout=None)  # No timeout

    @discord.ui.button(label='Matchup 1', style=discord.ButtonStyle.primary, custom_id='vote_1')
    async def vote_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, 1)

    @discord.ui.button(label='Matchup 2', style=discord.ButtonStyle.primary, custom_id='vote_2')
    async def vote_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, 2)

    @discord.ui.button(label='Matchup 3', style=discord.ButtonStyle.primary, custom_id='vote_3')
    async def vote_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, 3)

    @discord.ui.button(label='Re-roll 🎲', style=discord.ButtonStyle.secondary, custom_id='vote_reroll')
    async def vote_reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, reroll_key)
    
    @discord.ui.button(label='Custom', style=discord.ButtonStyle.secondary, custom_id='vote_custom')
    async def vote_custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, custom_teams_key)

    # handles registering a vote
    async def register_vote(self, interaction, m):
        global final_matchup_sent
        # do nothing if no longer in team voting phase
        if phase != Phase.MATCHUP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True, delete_after=msg_fade1)
            return
        
        user = interaction.user
        if user not in ready_players:
            await interaction.response.send_message('You are not part of the match.', ephemeral=True, delete_after=msg_fade1)
            return
        if user in voted_users:  # if already voted
            previous_vote = voted_users[user]
            if previous_vote == m:  # check if same vote
                await interaction.response.send_message(f'You have already voted for {get_matchup_str(m)}.', ephemeral=True, delete_after=msg_fade1)
                return
            votes[previous_vote] -= 1  # remove their previous vote
        voted_users[user] = m  # set user vote
        votes[m] += 1  # update matchup vote count
        await interaction.response.send_message(f'You voted for {get_matchup_str(m)}.', ephemeral=True, delete_after=msg_fade2)

        # Check if any matchup type has enough votes
        if votes[m] >= votes_required:
            if m == reroll_key:
                await interaction.message.channel.send('Re-rolling the matchups!')
                await proceed_to_matchups_phase(interaction.message.channel)
                return
            elif m == custom_teams_key and not final_matchup_sent:
                final_matchup_sent = True  # Ensure this block runs only once
                await declare_matchup(interaction.message.channel, -1)
            elif not final_matchup_sent:
                final_matchup_sent = True  # Ensure this block runs only once
                await declare_matchup(interaction.message.channel, m)

        # Update the voting message
        await display_matchup_votes(interaction.message.channel)

# Function to declare the chosen matchup
async def declare_matchup(channel, matchup_number):
    global phase, selected_matchup, final_matchup_players, final_team1_names, final_team2_names, final_matchup_start, final_matchup_score, final_matchup_message
    phase = Phase.PLAY
    final_matchup_score = 0
    final_matchup_start = datetime.now(timezone.utc)
    if matchup_number == -1:  # custom teams
        selected_matchup = custom_teams_key
        final_matchup_players = set(queue + custom_team1 + custom_team2)
        final_team1_names = ', '.join([get_display_name(user) for user in custom_team1]) or 'custom'
        final_team2_names = ', '.join([get_display_name(user) for user in custom_team2]) or 'custom'
    else:
        selected_matchup = matchup_number
        team1, team2 = matchups[matchup_number - 1]
        final_matchup_players = set(team1 + team2)
        final_team1_names = ', '.join([get_display_name(user) for user in team1])
        final_team2_names = ', '.join([get_display_name(user) for user in team2])

    embed = final_matchup_embed()
    final_matchup_message = await channel.send(embed=embed, view=FinalMatchupView())

    # Create the new waiting room after final matchup
    await create_waiting_room(channel)
    await update_queue_message() # single update of queue message for new phase

# Updates the final matchup message
async def update_final_matchup():
    embed = final_matchup_embed()
    if final_matchup_message:
        if phase != Phase.PLAY:
            all_mentions = ' '.join([user.mention for user in final_matchup_players])
            content = f'-# pug_mh {match_number} {selected_map.name.casefold()} {all_mentions}'
            await final_matchup_message.edit(content=content, embed=embed, view=None)
        else:
            await final_matchup_message.edit(embed=embed)

# gets the matchup length string
def matchup_length_str():
    if final_matchup_end:
        return f'{int(round((final_matchup_end - ready_end).total_seconds() / 60))} min - '
    return ''

# gets the score display string for the given team
def score_display(team_number):
    if ((team_number == 1 and final_matchup_score > 0) or
        (team_number == 2 and final_matchup_score < 0)):
        return f'🏆 - {"❤️ " * abs(final_matchup_score)}'
    return ''

# Function to make the final matchup embed
def final_matchup_embed():
    time_int = datetime_to_int(ready_end)
    embed = discord.Embed(title=f'Final Matchup #{match_number}', 
                          description=f'**{selected_map}** - {matchup_length_str()}*<t:{time_int}:d><t:{time_int}:t>*',
                          color=discord.Color.gold())
    embed.add_field(name=f'Team 1 {score_display(1)}', value=final_team1_names, inline=False)
    embed.add_field(name=f'Team 2 {score_display(2)}', value=final_team2_names, inline=False)
    if final_matchup_score == 0 and phase <= Phase.PLAY:
        embed.add_field(name='Remaining Wounds', value='Report result with !wounds x.  + for Team1, - for Team2', inline=False)
    if scoreboard_filename:
        embed.set_image(url=f'attachment://{scoreboard_filename}')
    elif phase <= Phase.PLAY:
        embed.add_field(name='Scoreboard', value='Use the !sb command with an attached image.', inline=False)
    if phase <= Phase.PLAY:
        embed.set_footer(text='Good luck and have fun! ')
    return embed

# View for reporting the final result of a match and resetting the queue
class FinalMatchupView(View):
   def __init__(self):
       super().__init__(timeout=None)

 
   @discord.ui.button(label='Match Complete', style=discord.ButtonStyle.red)
   async def complete_match(self, interaction: discord.Interaction, button: discord.ui.Button):
       await register_reset_vote(interaction)


# Handles a match complete vote
async def register_reset_vote(interaction):
   global reset_queue_votes, reset_voted_users, reset_in_progress
   user = interaction.user
   if user in reset_voted_users:
       await interaction.response.send_message('You have already marked the match as complete.', ephemeral=True, delete_after=msg_fade1)
       return
   if user not in final_matchup_players:
       await interaction.response.send_message('You are not in the current match and cannot mark the match as complete.', ephemeral=True, delete_after=msg_fade1)
       return
   if reset_in_progress:  # Prevent triggering multiple resets
       await interaction.response.send_message('Queue reset is already in progress.', ephemeral=True, delete_after=msg_fade1)
       return
       
   reset_queue_votes += 1
   reset_voted_users.add(user)
   await interaction.response.send_message(
       f'{user.mention} marked the match as complete ({reset_queue_votes}/{reset_queue_votes_required} votes).',
       ephemeral=True, delete_after=msg_fade2)
   
   await update_waiting_room_message()  # update reset vote display
   # Check if the required number of votes have been reached
   if reset_queue_votes >= reset_queue_votes_required and not reset_in_progress:
       reset_in_progress = True  # Prevent multiple resets
       await interaction.message.channel.send(f'Match #{match_number} marked as complete by vote.  Resetting queue...')
       await restart_queue(interaction.message.channel)  # Reset the queue and send a new queue message

# Create a waiting room for players not in the Final Matchup
async def create_waiting_room(channel):
   global waiting_room_message
   embed = waiting_room_embed()
   if waiting_room_message:
       await waiting_room_message.edit(embed=embed)
   else:
       waiting_room_message = await channel.send(embed=embed, view=WaitingRoomView())

# Function to update the waiting room message
async def update_waiting_room_message():
   if waiting_room_message:
       embed = waiting_room_embed()
       await waiting_room_message.edit(embed=embed)

# Function to make the waiting room embed
def waiting_room_embed():
    waiting_room_names = ', '.join(
        [get_display_name(user) for user in waiting_room]) or 'No players in waiting room.'
    votes_str = ''
    if reset_queue_votes > 0:
        votes_str = f' ({reset_queue_votes}/{reset_queue_votes_required} votes)'
    embed = discord.Embed(
        title="PUGs Queue",
        description=f'Waiting for match to complete.{votes_str}',
        color=discord.Color.purple()
    )
    embed.add_field(name=f'Waiting Room ({len(waiting_room)})', value=waiting_room_names, inline=False)
    if re_queue:
        re_queue_names = ', '.join([get_display_name(user) for user in re_queue])
        embed.add_field(name=f'Re-Queueing ({len(re_queue)})', value=re_queue_names, inline=False)
    return embed

# View for the waiting room buttons
class WaitingRoomView(View):
    def __init__(self):
        super().__init__(timeout=None)


    @discord.ui.button(label='Join Queue', style=discord.ButtonStyle.green)
    async def join_waiting_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_queue_join(interaction)
    
    @discord.ui.button(label='Leave Queue', style=discord.ButtonStyle.red)
    async def leave_waiting_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_queue_leave(interaction)
    
    @discord.ui.button(label='Match History', style=discord.ButtonStyle.grey)
    async def match_history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await reply_with_match_history(interaction)
    
    @discord.ui.button(label='Help', style=discord.ButtonStyle.grey)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await reply_with_help(interaction)


# restart queue after match is complete
async def restart_queue(channel):
    global phase, match_number
    phase = Phase.RESET
    update_final_matchup_end()
    await update_queue_message()  # final update of old queue message
    await update_final_matchup()  # final update of final matchup message
    # reset queue state
    reset_game()
    add_waiting_room_players_to_queue()  # Now add waiting room players to the empty queue
    match_number += 1  # increment match number
    await start_new_queue(channel)  # Start a new queue with waiting room players


# Add waiting room players to the new queue
def add_waiting_room_players_to_queue():
   global queue, waiting_room, re_queue
   # Move all players from requeue into waiting room
   waiting_room.extend(re_queue)
   re_queue = []
   # Move players out of the waiting room until queue is full or waiting room is empty
   queue[:] = waiting_room[:queue_size_required]  
   waiting_room[:] = waiting_room[queue_size_required:]

# Start a new queue programmatically without needing the command context
async def start_new_queue(channel):
   global phase, queue_message, waiting_room_message
   phase = Phase.QUEUE
   # Send a completely new queue message instead of editing the old one
   embed = queue_embed()
   queue_message = await channel.send(embed=embed, view=QueueView())
   waiting_room_message = await remove_message(waiting_room_message)
   await check_full_queue()

     
# Function to remove the given message (message = await remove_message(message))
async def remove_message(message: discord.Message):
   if message:
       try:
           await message.delete()
       except discord.NotFound:
           print("Message was already deleted.")
   return None

# function to save the current PUG state to a file    
def save_pug(file):
    if phase > Phase.READY: # if past ready phase, save the next match number
        file.write(f'{match_number + 1}\n')
    else:
        file.write(f'{match_number}\n')
    if phase < Phase.PLAY and queue:
        file.write('\n'.join(str(user.id) for user in queue))
        file.write('\n')
    if waiting_room:
        file.write('\n'.join(str(user.id) for user in waiting_room))
        file.write('\n')
    if phase >= Phase.PLAY and re_queue:
        file.write('\n'.join(str(user.id) for user in re_queue))
        file.write('\n')
        
# function to save the PUG state from a file    
def load_pug(ctx, file):
    global match_number
    for id_line in file:
        id_line_strip = id_line.strip()
        if not id_line_strip.isdecimal():
            continue
        num = int(id_line_strip)
        if 0 < num and num < 999999999: # num is match number
            match_number = num
            continue
        user = ctx.message.guild.get_member(num)  # num is user id
        #user = await ctx.message.guild.fetch_member(num)
        if user:
            if len(queue) < queue_size_required:
                queue.append(user)
            else:
                waiting_room.append(user)
        else:
            print(f'user not found: id={num}')

# function to get a message with commands to join a syco server game
def syco_commands_msg(port):
    cmd1 = f'`open syco.servegame.com:{port}?team=0` (TEAM 1)'
    cmd2 = f'`open syco.servegame.com:{port}?team=1` (TEAM 2)'
    msg_lines = [cmd1]
    if final_team1_names:
        msg_lines.append(final_team1_names)
        msg_lines.append('')
    msg_lines.append(cmd2)
    if final_team2_names:
        msg_lines.append(final_team2_names)
    return '\n'.join(msg_lines)

# updates final matchup start time to the current time
def update_final_matchup_start():
    global final_matchup_start
    if phase == Phase.PLAY and not final_matchup_end:
        final_matchup_start = datetime.now(timezone.utc)

# updates final matchup end time to the current time
def update_final_matchup_end():
    global final_matchup_end
    if phase >= Phase.PLAY and not final_matchup_end:
        final_matchup_end = datetime.now(timezone.utc)

# updates the number of remaining wounds for the current match
async def update_wounds(ctx, score):
    global final_matchup_score
    new_score = max(-3, min(3, score))
    if final_matchup_score == new_score:
        await ctx.send(f'The remaining wounds of Match #{match_number} have already been set to {new_score}.')
        return
    final_matchup_score = new_score
    await update_final_matchup()
    if final_matchup_score == 0:
        await ctx.send(f'The winner and remaining wounds of Match #{match_number} have been cleared.')
    else:
        win_team = (-final_matchup_score // abs(final_matchup_score) + 1) // 2 + 1
        await ctx.send(f'Team {win_team} is the winner of Match #{match_number} with {abs(final_matchup_score)} wounds remaining.')

# gets a block of text to explain how to search a user's match history
def match_history_block(user):
    username = user.name
    botname = str(bot.user)
    return f'''Copy this into the search bar to view your match history:
`pug_mh from: {botname} mentions: {username}`
- this tracks your discord account, so changing your nickname or in-game name is still ok
- add a map name to the search string to only view games on that map
- add `before:` `during:` or `after:` to search a sepcific date range
- add a match number to the search string to view that exact match number'''

# gets the code block of command help
def command_help_block():
    lines = '\n'.join([chelp for cname, chelp in command_help.items()])
    return f'```{lines}```'

# Command to end the PUG system
@bot.command(name='end_pug')
async def end_pug(ctx):
   global phase, waiting_room, re_queue, game_in_progress, queue_message
   if game_in_progress or queue_message:
       print(f'{get_timestamp()} - ending PUGs')
       try:
          with open(save_file_path, 'w') as save_file:
             save_pug(save_file)
       except:
          print(f'{get_timestamp()} - Error saving PUG data.')
       print(f'{get_timestamp()} - PUG saved on match #{match_number} with {total_queue_size()} players in queue.')
       # Reset the game state
       reset_game()
       phase = Phase.NONE
       waiting_room = []
       re_queue = []
       await ctx.send('The current PUG session has been ended. You can start a new queue with `!start_pug`.')
   else:
       await ctx.send('No PUG session is currently active.')


# Command to start the PUG system
@bot.command(name='start_pug')
async def start_pug(ctx):
   global phase, queue, queue_message, game_in_progress
   if not game_in_progress and not queue_message:
      print(f'{get_timestamp()} - starting PUGs')
      phase = Phase.QUEUE
      # load data if it exists
      if os.path.isfile(save_file_path):
         queue = []
         try:
            with open(save_file_path, 'r') as save_file:
               load_pug(ctx, save_file)
            print(f'{get_timestamp()} - PUG loaded on match #{match_number} with {total_queue_size()} players in queue.')
            os.remove(save_file_path)
         except:
            print(f'{get_timestamp()} - Failed to load saved PUG: {save_file_path}')
            queue = []   
            
      # send queue message
      embed = queue_embed()
      queue_message = await ctx.send(embed=embed, view=QueueView())
      # If we have the required number of players, move to ready check
      await check_full_queue()
   else:
       await ctx.send('A match is already in progress or the queue is active.')

# Command to show the server join commands for syco.servegame.com port 7777
@bot.command(name='s7')
async def s7(ctx):
    await ctx.send(syco_commands_msg(7777))
    update_final_matchup_start()
    
# Command to show the server join commands for syco.servegame.com port 7778
@bot.command(name='s8')
async def s8(ctx):
    await ctx.send(syco_commands_msg(7778))
    update_final_matchup_start()
    
# Command to show the server join commands for syco.servegame.com port 7779
@bot.command(name='s9')
async def s9(ctx):
    await ctx.send(syco_commands_msg(7779))
    update_final_matchup_start()
    
# Command to show the server join commands for syco.servegame.com port 7780
@bot.command(name='s0')
async def s0(ctx):
    await ctx.send(syco_commands_msg(7780))
    update_final_matchup_start()

# Command to manually add users to the queue
@bot.command(name='queue_users')
async def queue_users(ctx, members: commands.Greedy[discord.Member]):
    if queue_message:
        total_added = 0
        for member in members:
            if len(queue) < queue_size_required:
                if member not in queue:
                    queue.append(member)
                    total_added += 1
            else:
                if member not in queue and member not in waiting_room:
                    waiting_room.append(member)
                    total_added += 1
        await ctx.send(f'Added {total_added} players to queue.')
        if phase >= Phase.PLAY:
            await update_waiting_room_message()
        else:
            await update_queue_message()
    else:
        await ctx.send('Cannot queue players, queue message not found.')

# Command to set custom team 1
@bot.command(name='ct1')
async def ct1(ctx, members: commands.Greedy[discord.Member]):
    global custom_team1
    if phase <= Phase.READY:
        await ctx.send(f'Cannot set custom teams until players are in a match.')
        return
    if phase >= Phase.PLAY:
        await ctx.send(f'Cannot set custom teams once a final matchup has been decided.')
        return
    
    custom_team1 = list(members[:team_size])
    custom_team1.sort(key=user_sort_key)
    custom_team1_names = ', '.join([get_display_name(user) for user in custom_team1])
    await ctx.send(f'Custom Team 1 has been set to: {custom_team1_names}.')
    # if team 1 is the size of a full team and all players are from the queue,
    # set team 2 to the leftover players
    if len(custom_team1) == team_size and set(custom_team1) <= set(queue):
        custom_team2 = list(set(queue) - set(custom_team1))
        custom_team2.sort(key=user_sort_key)
        custom_team2_names = ', '.join([get_display_name(user) for user in custom_team2])
        await ctx.send(f'Custom Team 2 has been set to: {custom_team2_names}.')
    if phase == Phase.MATCHUP:
        await display_matchup_votes(ctx.message.channel)

# Command to set custom team 2
@bot.command(name='ct2')
async def ct2(ctx, members: commands.Greedy[discord.Member]):
    global custom_team2
    if phase <= Phase.READY:
        await ctx.send(f'Cannot set custom teams until players are in a match.')
        return
    if phase >= Phase.PLAY:
        await ctx.send(f'Cannot set custom teams once a final matchup has been decided.')
        return
    
    custom_team2 = list(members[:team_size])
    custom_team2.sort(key=user_sort_key)
    custom_team2_names = ', '.join([get_display_name(user) for user in custom_team2])
    await ctx.send(f'Custom Team 2 has been set to: {custom_team2_names}.')
    if phase == Phase.MATCHUP:
        await display_matchup_votes(ctx.message.channel)

# Command to set scoreboard
@bot.command(name='sb')
async def sb(ctx, score_str: str = 'x'):
    global scoreboard_filename, final_matchup_score
    if phase != Phase.PLAY:
        await ctx.send(f'Cannot update scoreboard, no match is active.')
        return
    if not ctx.message.attachments:
        await ctx.send(f'No image attached, must attach an image of the scoreboard.')
        return
    if not ctx.message.attachments[0].content_type.startswith('image'):
        await ctx.send(f'Must attach an image, you attached a {ctx.message.attachments[0].content_type}.')
        return
    
    # convert attached image to a file to attach to our own message
    scoreboard_file = await ctx.message.attachments[0].to_file()
    scoreboard_filename = scoreboard_file.filename
    await final_matchup_message.edit(attachments=[scoreboard_file])
    await update_final_matchup()
    await ctx.send(f'Updated scoreboard for Match #{match_number}.')
    update_final_matchup_end()  # update match end time
    
    try:
        score = int(score_str)
    except ValueError:
        return
    await update_wounds(ctx, score) 
    
# Command to set remaining wounds score
@bot.command(name='wounds')
async def wounds(ctx, score_str: str = 'x'):
    global final_matchup_score
    if phase != Phase.PLAY:
        await ctx.send(f'Cannot update wounds, no match is active.')
        return
    try:
        score = int(score_str)
    except ValueError:
        await ctx.send(f'Unable to parse number of wounds from !wounds {score_str}.')
        return
    await update_wounds(ctx, score) 

# Command to get match history search string
@bot.command(name='mh')
async def mh(ctx):
    msg = match_history_block(ctx.message.author)
    await ctx.send(msg)

# Run the bot
bot.run(TOKEN)