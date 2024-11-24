import os
import random
import asyncio
from collections import defaultdict
from datetime import datetime
import time
from enum import IntEnum
import math

import discord
from discord.ext import commands
from discord.ui import View, Button
from dotenv import load_dotenv

# Load the bot token from the .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

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
    # Set a custom status with the Jack-o'-Lantern emoji 🎃 and the message "Happy Halloween!!!"
    activity = discord.Activity(type=discord.ActivityType.playing, name="Gigantic PUGs")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print(f'{get_timestamp()} - Logged in as {bot.user.name}')

# Constants for settings
map_choices = ["Ghost Reef 🏜️", "Sirens Strand 🧊", "Sanctum Falls 🌊", "Ember Grove 🌲", "Sky City ☁️"]
ready_up_time = 90  # Set the ready-up time to 90 seconds
queue_size_required = 10  # 10 players required for 5v5
reset_queue_votes_required = 4  # Require 4 votes to reset the queue
votes_required = 5  # Require 5 votes to pick maps, matchups, or re-roll
map_total_votes_required = 7  # Require 7 total votes to choose a map
save_file_path = 'stored_pug.txt'  # Stores saved PUG data to load on next startup
msg_fade1 = 8  # very simple ephemeral messages auto-delete after 8 seconds
msg_fade2 = 30  # simple ephemeral messages auto-delete after 30 seconds
vote_pip = '\u25c9 '  # pip to use when displaying votes

# Phase enum
class Phase(IntEnum):
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
game_in_progress = False
queue_message = None

ready_players = set()
bailouts_unc = []  # Players who have clicked bailout once but not confirmed
bailouts = []  # Players who are bailing out
standby = []  # Players on standby to fill for players that do not ready up
ready_start = 0  # for storing the timestamp of the start of the ready up countdown
ready_end = 0  # for storing the timestamp of the end of the ready up countdown
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
votes = defaultdict(int)
voted_users = {}  # Track individual votes for changeable votes
reroll_votes = 0
final_matchup_sent = False  # Track if the final matchup has already been sent
voting_message = None

final_matchup_players = set()  # Players in the final matchup
final_team1_names = None
final_team2_names = None
reset_queue_votes = 0
reset_voted_users = set()
reset_in_progress = False  # Flag to prevent multiple resets
waiting_room_message = None  # For the waiting room message


# Helper function to reset the game state but keep the waiting room intact
def reset_game():
    global phase, queue, game_in_progress, queue_message
    global ready_players, bailouts_unc, bailouts, standby, ready_start, ready_end, ready_up_timed_out, all_ready_sent, ready_message, ready_up_task
    global map_votes, map_voted_users, selected_map, selected_map_sent, map_voting_message
    global matchups, votes, voted_users, reroll_votes, final_matchup_sent, voting_message
    global final_matchup_players, final_team1_names, final_team2_names, reset_queue_votes, reset_voted_users, reset_in_progress
    phase = Phase.QUEUE
    queue = []
    # waiting_room is not reset
    # re_queue is not reset
    game_in_progress = False
    queue_message = None
    
    ready_players = set()
    bailouts_unc = []
    bailouts = []
    standby = []
    ready_start = 0
    ready_end = 0
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
    votes = defaultdict(int)
    voted_users = {}
    reroll_votes = 0
    final_matchup_sent = False
    voting_message = None
    
    final_matchup_players = set()
    final_team1_names = None
    final_team2_names = None
    reset_queue_votes = 0
    reset_voted_users = set()
    reset_in_progress = False
    # waiting_room_message is not reset


# Helper function to get a user's preferred display name
def get_display_name(user):
    return user.nick or user.display_name or user.name
    
# Helper function to get a case insensitve key to sort users
def user_sort_key(user):
    return str.casefold(get_display_name(user))

# Function to make the queue embed
def queue_embed():
    queue_names = ', '.join([get_display_name(user) for user in queue]) or 'No players in queue.'
    if phase < Phase.PLAY:
        embed = discord.Embed(title='PUGs Queue', color=discord.Color.blue())
        embed.add_field(name=f'In Queue ({len(queue)}/{queue_size_required})', value=queue_names, inline=False)
        if waiting_room:
            waiting_names = ', '.join([get_display_name(user) for user in waiting_room])
            embed.add_field(name=f'Waiting Room ({len(waiting_room)})', value=waiting_names, inline=False)
        if re_queue and phase > Phase.READY:
            re_queue_names = ', '.join([get_display_name(user) for user in re_queue])
            embed.add_field(name=f'Re-Queueing ({len(re_queue)})', value=re_queue_names, inline=False)
    else:
        embed = discord.Embed(title='PUGs Match', description=queue_names, color=discord.Color.blue())
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
    global phase, ready_players, bailouts_unc, bailouts, standby, ready_start, ready_end, ready_up_task
    phase = Phase.READY
    ready_players = set()
    bailouts_unc = []
    bailouts = []
    standby = []  

    # Gather all player mentions
    mentions = ' '.join([user.mention for user in queue])

    # Send a message pinging all players that the queue has popped
    await channel.send(f"The queue is full with {len(queue)} players! {mentions} please ready up!")

    # List of random messages to send
    dm_messages = [
        "The queue is full. Go Ready Up!",
        "It's time for server set-up simulator, go ready up!",
        "Go ready up for PUGs or have another 30 minutes of queue time!",
        "The PUGs queue is full. Go to the server and Ready Up!",
        "It's time for Giggin, go ready up!"
    ]

    # Send a DM to each player in the queue with a random message
    for user in queue:
        try:
            random_message = random.choice(dm_messages)  # Select a random message
            await user.send(random_message)
        except discord.Forbidden:
            print(f"Could not DM {user} due to privacy settings.")

    # Get start and end times
    ready_start = int(time.time())
    ready_end = ready_start + ready_up_time

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
        await ready_message.edit(embed=embed, view=ReadyUpView())
    else:
        ready_message = await channel.send(embed=embed, view=ReadyUpView())

# Function to update the ready-up message (players and timer)
async def update_ready_up_message():
    if ready_message:
        embed = ready_up_embed()
        await ready_message.edit(embed=embed)

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
    await channel.send(f"Not all players were ready. Re-queuing {num_ready} ready players.")
    ready_message = await remove_message(ready_message)
    queue_message = await remove_message(queue_message)
    await start_new_queue(channel)  # Post a new queue message with ready players

# Function to make the ready up embed
def ready_up_embed():
    queue_sorted = list(queue)
    queue_sorted.sort(key=user_sort_key)
    queue_names = '\n'.join([f'✅ {get_display_name(user)}' if user in ready_players else 
                             f'❌ {get_display_name(user)}' if user in bailouts else
                             f'⌛ {get_display_name(user)}' for user in queue_sorted])

    embed = discord.Embed(title='Match Found!',
                          description='Please ready up!  Players in the waiting room can standby to fill.',
                          color=discord.Color.green())
    embed.add_field(name=f'Match Players ({len(ready_players)}/{queue_size_required})', value=queue_names, inline=True)
    if standby:
        standby_names = '\n'.join([get_display_name(user) for user in standby]) or '\u200b'
        embed.add_field(name=f'On Standby ({len(standby)}/{queue_size_required - len(ready_players)})', value=standby_names, inline=True)
    embed.add_field(name='\u200b', value=f'-# Expires: <t:{ready_end}:R>', inline=False)
    return embed

# View for the ready up button
class ReadyUpView(View):
    def __init__(self):
        super().__init__(timeout=None)  # No timeout here, handled by countdown

    @discord.ui.button(label='Ready Up', style=discord.ButtonStyle.green)
    async def ready_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        global standby, all_ready_sent
        user = interaction.user
        if user in queue:
            if user in ready_players:
                await interaction.response.send_message('Cannot ready after clicking bail out.', ephemeral=True, delete_after=msg_fade1)
                return
            if user in bailouts:
                await interaction.response.send_message('You are already bailing out.', ephemeral=True, delete_after=msg_fade1)
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
    # if all users in match have readied or bailed
    if (len(ready_players) + len(bailouts) == queue_size_required and
        len(standby) >= queue_size_required - len(ready_players)):
        await end_ready_up(channel)

# New function to proceed to map voting
async def proceed_to_map_voting(channel):
    global phase, re_queue, ready_message, map_votes, map_voted_users, map_voting_message, ready_up_task
    phase = Phase.MAP
    # Cancel the ready-up task to prevent it from running after this point
    if not ready_up_timed_out and ready_up_task is not None:
        ready_up_task.cancel()
        ready_up_task = None

    ready_message = await remove_message(ready_message)
    # set all ready players to requeue by default, but in a random order
    re_queue = list(ready_players)
    random.shuffle(re_queue)

    map_votes.clear()  # Clear votes only at the start of new matchups
    map_voted_users.clear()  # Reset users who voted
    map_voting_message = None

    embed = map_voting_embed()

    # Send the message with the MapVotingView
    map_voting_message = await channel.send(embed=embed, view=MapVotingView())
    await update_queue_message() # single update of queue message for new phase

# Function to make the map voting embed
def map_voting_embed():
    embed = discord.Embed(title='Map Vote', 
                          #description='Vote for the map you want to play on.', 
                          color=discord.Color.green())
    for map_name in map_choices:
        embed.add_field(name=map_name, value=f'\u200b{vote_pip * map_votes[map_name]}', inline=True)
        #embed.add_field(name=map_name, value=f'Votes: {map_votes[map_name]}', inline=True)
    # add extra empty fields so that there are 3 fields per row
    rem = len(map_choices) % 3
    if rem != 0:
        embed.add_field(name='\u200b', value='\u200b', inline=True)
    if rem == 1:
        embed.add_field(name='\u200b', value='\u200b', inline=True)
        
    if selected_map:
        embed.add_field(name='Selected Map', value=selected_map, inline=False)
    return embed

# Class for map voting
class MapVotingView(View):
    def __init__(self):
        super().__init__(timeout=None)
        for map_name in map_choices:
            button = Button(label=map_name, style=discord.ButtonStyle.primary, custom_id=map_name)
            button.callback = self.make_callback(map_name)
            self.add_item(button)

    def make_callback(self, map_name):
        async def callback(interaction: discord.Interaction):
            await self.register_map_vote(interaction, map_name)
        return callback

    async def register_map_vote(self, interaction, map_name):
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
            if map_previous_vote == "map_name":
                await interaction.response.send_message(f'You have already voted for {map_name}.', ephemeral=True, delete_after=msg_fade1)
                return
            else:
                map_votes[map_previous_vote] -= 1  # Remove their previous map vote

        map_votes[map_name] += 1
        map_voted_users[user] = map_name
        await interaction.response.send_message(f'You voted for {map_name}.', ephemeral=True, delete_after=msg_fade2)

        # Update the voting message
        await update_map_voting_message()

        # Check if the map has 5 votes (for 5v5)
        if (map_votes[map_name] >= votes_required) and not selected_map_sent:
            selected_map_sent = True
            selected_map = map_name
            await declare_selected_map(interaction.message.channel, selected_map)
        # Check if 7 votes have been cast
        elif len(map_voted_users) >= map_total_votes_required and not selected_map_sent:
            selected_map_sent = True
            # Determine the map(s) with the most votes (in case of tie)
            max_votes = max(map_votes.values())
            top_maps = [name for name, count in map_votes.items() if count == max_votes]
            selected_map = random.choice(top_maps)  # If tie, select randomly among top maps
            await declare_selected_map(interaction.message.channel, selected_map)
            

# Function to update the map voting message
async def update_map_voting_message():
    if map_voting_message:
        embed = map_voting_embed()
        if phase != Phase.MAP:
            await map_voting_message.edit(embed=embed, view=None)  # remove buttons if not voting
        else:
            await map_voting_message.edit(embed=embed)

# Function to declare the selected map and proceed to matchups
async def declare_selected_map(channel, selected_map):
    #await channel.send(f"The selected map is **{selected_map}**!")
    # Proceed to matchup voting
    await proceed_to_matchups_phase(channel)
    await update_map_voting_message()

# Adjusted function to proceed to matchups
async def proceed_to_matchups_phase(channel):
    global phase, matchups, votes, voted_users, voting_message
    phase = Phase.MATCHUP
    team_size = queue_size_required // 2 # // is integer division, / is float division which gives a float
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

# Function to display the voting embed with votes count and enhanced readability
async def display_matchup_votes(channel):
    global reroll_votes, voting_message
    embed = discord.Embed(title='Matchup Vote', description='Vote for your preferred matchup or vote to re-roll.',
                          color=discord.Color.green())

    for idx, (team1, team2) in enumerate(matchups, 1):
        embed.add_field(name='——————————————————————————',
                        value=f'**Matchup {idx}** {vote_pip * votes[idx]}',
                        inline=False)
        team1_names = '\n'.join([get_display_name(user) for user in team1])
        team2_names = '\n'.join([get_display_name(user) for user in team2])
        embed.add_field(name='Team 1', value=team1_names, inline=True)
        embed.add_field(name='Team 2', value=team2_names, inline=True)

    # Clearer re-roll option with votes
    embed.add_field(name='——————————————————————————',
                    value=f'**Re-roll Matchups** {vote_pip * reroll_votes}\nVote to re-roll all matchups and generate new ones.', 
                    inline=False)

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
        await self.register_reroll_vote(interaction)

    async def register_vote(self, interaction, matchup_number):
        global final_matchup_sent  # To ensure the final matchup is only sent once
        # do nothing if no longer in team voting phase
        if phase != Phase.MATCHUP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True, delete_after=msg_fade1)
            return
        
        user = interaction.user

        if user not in ready_players:
            await interaction.response.send_message('You are not part of the match.', ephemeral=True, delete_after=msg_fade1)
            return

        # Allow user to change their vote
        if user in voted_users:
            previous_vote = voted_users[user]
            if previous_vote == "reroll":
                global reroll_votes
                reroll_votes -= 1  # Remove their previous re-roll vote
            else:
                votes[previous_vote] -= 1  # Remove their previous matchup vote

        votes[matchup_number] += 1
        voted_users[user] = matchup_number

        await interaction.response.send_message(f'You voted for Matchup {matchup_number}.', ephemeral=True, delete_after=msg_fade2)

        # Check if any matchup has 5 votes (for 5v5)
        if votes[matchup_number] >= votes_required and not final_matchup_sent:
            final_matchup_sent = True  # Ensure this block runs only once
            await declare_matchup(interaction.message.channel, matchup_number)

        # Update the voting message
        await display_matchup_votes(interaction.message.channel)
            

    async def register_reroll_vote(self, interaction):
        global reroll_votes, votes, voted_users
        # do nothing if no longer in team voting phase
        if phase != Phase.MATCHUP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True, delete_after=msg_fade1)
            return
        
        user = interaction.user

        if user not in ready_players:
            await interaction.response.send_message('You are not part of the match.', ephemeral=True, delete_after=msg_fade1)
            return

        # Allow user to change vote if they already voted for re-roll
        if user in voted_users:
            previous_vote = voted_users[user]
            if previous_vote == "reroll":
                await interaction.response.send_message('You have already voted to re-roll.', ephemeral=True, delete_after=msg_fade1)
                return
            else:
                votes[previous_vote] -= 1  # Remove their previous matchup vote

        reroll_votes += 1
        voted_users[user] = "reroll"

        await interaction.response.send_message('You voted to re-roll the matchups.', ephemeral=True, delete_after=msg_fade2)

        if reroll_votes >= votes_required:
            await interaction.followup.send('Re-rolling the matchups!', ephemeral=False)
            # Reset votes and users before proceeding
            votes.clear()
            voted_users.clear()
            reroll_votes = 0
            await proceed_to_matchups_phase(interaction.message.channel)
        else:
            await display_matchup_votes(interaction.message.channel)

# Function to declare the chosen matchup
async def declare_matchup(channel, matchup_number):
    global phase, final_matchup_players, final_team1_names, final_team2_names

    phase = Phase.PLAY
    team1, team2 = matchups[matchup_number - 1]
    final_matchup_players = set(team1 + team2)  # Mark players in Final Matchup
    final_team1_names = ', '.join([get_display_name(user) for user in team1])
    final_team2_names = ', '.join([get_display_name(user) for user in team2])

    embed = discord.Embed(title='Final Matchup', color=discord.Color.gold())
    embed.add_field(name='Map', value=selected_map, inline=False)
    embed.add_field(name='Team 1', value=final_team1_names, inline=False)
    embed.add_field(name='Team 2', value=final_team2_names, inline=False)
    embed.set_footer(text='Good luck and have fun!')

    await channel.send(embed=embed, view=ResetQueueView())

    # Create the new waiting room after final matchup
    await create_waiting_room(channel)
    await update_queue_message() # single update of queue message for new phase


# Create a waiting room for players not in the Final Matchup
async def create_waiting_room(channel):
   global waiting_room_message
   embed = waiting_room_embed()
   if waiting_room_message:
       await waiting_room_message.edit(embed=embed)
   else:
       waiting_room_message = await channel.send(embed=embed, view=WaitingRoomView())

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


# Function to update the waiting room message
async def update_waiting_room_message():
   if waiting_room_message:
       embed = waiting_room_embed()
       await waiting_room_message.edit(embed=embed)


# View for resetting the queue with voting
class ResetQueueView(View):
   def __init__(self):
       super().__init__(timeout=None)


   @discord.ui.button(label='Match Complete', style=discord.ButtonStyle.danger)
   async def reset_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
       await self.register_reset_vote(interaction)


   async def register_reset_vote(self, interaction):
       global reset_queue_votes, reset_voted_users, reset_in_progress
       user = interaction.user
       if user in reset_voted_users:
           await interaction.response.send_message('You have already marked the match as complete.', ephemeral=True, delete_after=msg_fade1)
           return


       # Only allow Final Matchup players to reset the queue
       if user not in final_matchup_players:
           await interaction.response.send_message(
               'You are not in the current match and cannot mark the match as complete.', ephemeral=True, delete_after=msg_fade1)
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
           await interaction.message.channel.send('Match marked as complete by vote.  Resetting queue...')
           await self.remove_buttons(interaction)  # Remove buttons after reset
           await restart_queue(interaction.message.channel)  # Reset the queue and send a new queue message


   async def remove_buttons(self, interaction):
       # Disable buttons after the queue is reset
       for child in self.children:
           child.disabled = True
       await interaction.message.edit(view=None)  # Edit the message to remove buttons

# restart queue after match is complete
async def restart_queue(channel):
    global phase
    phase = Phase.RESET
    await update_queue_message()  # final update of old queue message
    # reset queue state
    reset_game()
    add_waiting_room_players_to_queue()  # Now add waiting room players to the empty queue
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
    for id_line in file:
        id_line_strip = id_line.strip()
        if not id_line_strip.isdecimal():
            continue
        user_id = int(id_line_strip)
        user = ctx.message.guild.get_member(user_id)
        #user = await ctx.message.guild.fetch_member(user_id)
        if user:
            if len(queue) < queue_size_required:
                queue.append(user)
            else:
                waiting_room.append(user)
        else:
            print(f'user not found: id={user_id}')

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
       print(f'{get_timestamp()} - PUG saved with {len(queue)} players in queue.')
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
            print(f'{get_timestamp()} - PUG loaded with {len(queue)} players in queue.')
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
    
# Command to show the server join commands for syco.servegame.com port 7778
@bot.command(name='s8')
async def s8(ctx):
    await ctx.send(syco_commands_msg(7778))
    
# Command to show the server join commands for syco.servegame.com port 7779
@bot.command(name='s9')
async def s9(ctx):
    await ctx.send(syco_commands_msg(7779))
    
# Command to show the server join commands for syco.servegame.com port 7780
@bot.command(name='s0')
async def s0(ctx):
    await ctx.send(syco_commands_msg(7780))

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

# Run the bot
bot.run(TOKEN)