import os
import random
import asyncio
from collections import defaultdict
from enum import Enum

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

@bot.event
async def on_ready():
    # Set a custom status with the Jack-o'-Lantern emoji 🎃 and the message "Happy Halloween!!!"
    activity = discord.Activity(type=discord.ActivityType.playing, name="Gigantic PUGs")
    await bot.change_presence(status=discord.Status.online, activity=activity)
    print(f'Logged in as {bot.user.name}')

# Phase enum
class Phase(Enum):
    NONE = 1
    QUEUE = 2
    READY = 3
    MAP = 4
    MATCHUP = 5
    PLAY = 6
    
# Global variables to keep track of the queue and game states
phase = Phase.QUEUE
queue = []
waiting_room = []
ready_players = set()
decline_ready_players = set()
matchups = []
votes = defaultdict(int)
voted_users = {}  # Track individual votes for changeable votes
reroll_votes = 0
reset_queue_votes = 0
reset_voted_users = set()
game_in_progress = False
queue_message = None
voting_message = None
waiting_room_message = None  # For the waiting room message
ready_message = None  # To store the ready-up message
final_matchup_sent = False  # Track if the final matchup has already been sent
ready_up_task = None  # For tracking the countdown task
reset_in_progress = False  # Flag to prevent multiple resets
final_matchup_players = set()  # Players in the final matchup

# New global variables for map voting
map_votes = defaultdict(int)
map_voted_users = {}  # Track individual votes for changeable votes
map_voting_message = None  # To store the map voting message
selected_map = None  # To store the selected map
selected_map_sent = False # Track if the selected map has already been sent

# Constants for settings
map_choices = ["Ghost Reef 🏜️", "Sirens Strand 🧊", "Sanctum Falls 🌊", "Ember Grove 🌲", "Sky City ☁️"]
ready_up_time = 90  # Set the ready-up time to 90 seconds
queue_size_required = 10  # 10 players required for 5v5
reset_queue_votes_required = 4  # Require 4 votes to reset the queue
votes_required = 5  # Require 5 votes to pick maps, matchups, or re-roll
map_total_votes_required = 7  # Require 7 total votes to choose a map
queue_file_path = 'stored_queue.txt'

# Helper function to reset the game state but keep the waiting room intact
def reset_game():
    global phase, queue, ready_players, decline_ready_players, matchups, votes, voted_users, reroll_votes, reset_queue_votes, reset_voted_users
    global game_in_progress, queue_message, voting_message, final_matchup_sent, ready_message, ready_up_task, reset_in_progress, final_matchup_players
    global map_votes, map_voted_users, map_voting_message, selected_map, selected_map_sent
    phase = Phase.QUEUE
    queue = []
    ready_players = set()
    decline_ready_players = set()
    matchups = []
    votes = defaultdict(int)
    voted_users = {}  # Reset individual vote tracking
    reroll_votes = 0
    reset_queue_votes = 0
    reset_voted_users = set()
    game_in_progress = False
    queue_message = None
    voting_message = None
    ready_message = None
    
    final_matchup_sent = False
    final_matchup_players = set()
    reset_in_progress = False  # Reset the flag
    map_votes = defaultdict(int)
    map_voted_users = {}
    map_voting_message = None
    selected_map = None
    selected_map_sent = False

    # Cancel the countdown task if it's running
    if ready_up_task is not None:
        ready_up_task.cancel()
        ready_up_task = None

# Helper function to get a user's preferred display name
def get_display_name(user):
    return user.nick or user.display_name or user.name

# View for the join/leave queue buttons
class QueueView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Join Queue', style=discord.ButtonStyle.green)
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        # do nothing if no longer in queue phase
        if phase != Phase.QUEUE:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True)
            return
            
        user = interaction.user
        if len(queue) >= queue_size_required:
            await interaction.response.send_message(f'{user.mention}, the queue is full!', ephemeral=True)
        elif user not in queue:
            if user in final_matchup_players:
                await interaction.response.send_message(
                    f'{user.mention}, you are in the last matchup and can only join after others.', ephemeral=True)
                return
            queue.append(user)
            await interaction.response.send_message(f'{user.mention} joined the queue!', ephemeral=True)
        else:
            await interaction.response.send_message('You are already in the queue.', ephemeral=True)
        await update_queue_message()

    @discord.ui.button(label='Leave Queue', style=discord.ButtonStyle.red)
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        # do nothing if no longer in queue phase
        if phase != Phase.QUEUE:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True)
            return
        
        user = interaction.user
        if user in queue:
            queue.remove(user)
            await interaction.response.send_message(f'{user.mention} left the queue.', ephemeral=True)
        else:
            await interaction.response.send_message('You are not in the queue.', ephemeral=True)
        await update_queue_message()

# Function to update the queue message (editing the original message)
async def update_queue_message():
    global queue_message, game_in_progress
    queue_names = ', '.join([get_display_name(user) for user in queue]) or 'No players in queue.'
    embed = discord.Embed(title='PUGs Queue',
                          description=f'Players in queue ({len(queue)}/{queue_size_required}): {queue_names}',
                          color=discord.Color.blue())

    # Remove buttons if the ready check has started
    if game_in_progress:
        if queue_message:
            await queue_message.edit(embed=embed, view=None)  # Remove the buttons once the ready check starts
    else:
        if queue_message:
            await queue_message.edit(embed=embed, view=QueueView())
        else:
            queue_message = await bot.get_channel(queue_message.channel.id).send(embed=embed, view=QueueView())

    # If we have the required number of players, move to ready check
    if len(queue) == queue_size_required and not game_in_progress:
        game_in_progress = True
        await start_ready_check(queue_message.channel)

# Function to start the ready check
async def start_ready_check(channel):
    global phase, ready_players, decline_ready_players, ready_up_task
    phase = Phase.READY
    ready_players = set()
    decline_ready_players = set()

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

    # Start the ready-up process and display the message
    await display_ready_up(channel)

    # Start the ready-up timer task
    ready_up_task = asyncio.create_task(countdown_ready_up(channel))

# Function to display the ready-up message
async def display_ready_up(channel):
    global ready_message
    ready_list = ', '.join([get_display_name(user) for user in ready_players]) or 'No players ready yet.'
    not_ready_players = set(queue) - ready_players
    not_ready_list = ', '.join([get_display_name(user) for user in not_ready_players]) or 'All players are ready.'

    embed = discord.Embed(title='Ready Up Phase',
                          description='The queue is full! Please ready up by clicking the "Ready Up" button.',
                          color=discord.Color.green())
    embed.add_field(name='Players Ready', value=f'{ready_list}', inline=False)
    embed.add_field(name='Players Not Ready', value=f'{not_ready_list}', inline=False)
    embed.set_footer(text=f'Time left: {ready_up_time} seconds')

    # Send the ready-up message and store its reference
    if ready_message:
        await ready_message.edit(embed=embed, view=ReadyUpView())
    else:
        ready_message = await channel.send(embed=embed, view=ReadyUpView())

# Function to update the ready-up message (players and timer)
async def update_ready_up_message(time_left):
    global ready_message
    ready_list = ', '.join([get_display_name(user) for user in ready_players]) or 'No players ready yet.'
    not_ready_players = set(queue) - ready_players
    not_ready_list = ', '.join([get_display_name(user) for user in not_ready_players]) or 'All players are ready.'

    embed = discord.Embed(title='Ready Up Phase', color=discord.Color.green())
    embed.add_field(name='Players Ready', value=f'{ready_list}', inline=False)
    embed.add_field(name='Players Not Ready', value=f'{not_ready_list}', inline=False)
    embed.set_footer(text=f'Time left: {time_left} seconds')

    # Edit the ready-up message with updated players and time
    if ready_message:
        await ready_message.edit(embed=embed)

# Countdown timer for the ready-up phase
async def countdown_ready_up(channel):
    global ready_up_time

    # Loop through each second and update the message every second
    for remaining in range(ready_up_time, 0, -1):  # Update every 1 second
        await update_ready_up_message(remaining)
        await asyncio.sleep(1)  # Wait 1 second between each update

    # Timeout reached: proceed with ready players or reset queue
    await ready_up_timeout(channel)

# Timeout action if not all players are ready
async def ready_up_timeout(channel):
    global game_in_progress
    non_ready_players = set(queue) - ready_players

    # Remove non-ready players from queue
    for user in non_ready_players:
        queue.remove(user)

    # If some players were ready but not all, re-add the ready players back into the queue
    if len(ready_players) > 0:
        await channel.send(f"Not all players were ready. Re-queuing {len(ready_players)} ready players.")
        await remove_ready_message()  # Remove the ready check message and buttons
        queue[:] = list(ready_players)  # Re-add the players who were ready back to the queue
        ready_players.clear()  # Clear the ready players set for the next ready check
        game_in_progress = False  # Reset game_in_progress to trigger a new ready check
        await remove_old_queue_message()  # Remove the old queue message
        await start_new_queue(channel)  # Post a new queue message with ready players
    else:
        # If no one is ready, fully reset the queue
        await channel.send('Not enough players ready. Resetting queue completely.')
        reset_game()
        await remove_ready_message()  # Remove the ready check message and buttons
        await remove_old_queue_message()  # Remove the old queue message
        await start_new_queue(channel)

# View for the ready up button
class ReadyUpView(View):
    def __init__(self):
        super().__init__(timeout=None)  # No timeout here, handled by countdown

    @discord.ui.button(label='Ready Up', style=discord.ButtonStyle.green)
    async def ready_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user in queue and user not in ready_players:
            if user in decline_ready_players:
                decline_ready_players.remove(user)
            ready_players.add(user)
            await interaction.response.send_message(f'{user.mention} is ready!', ephemeral=True)
            await update_ready_up_message(time_left=ready_up_time)  # Update the ready-up message with new players
            # Proceed immediately if all players are ready
            if len(ready_players) == queue_size_required:
                await proceed_to_map_voting(interaction.message.channel)
        else:
            await interaction.response.send_message('You are not in the queue or already ready.', ephemeral=True)
            
    @discord.ui.button(label='Decline Queue', style=discord.ButtonStyle.red)
    async def decline_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        global game_in_progress
        user = interaction.user
        if user in queue:
            if user in ready_players:
                await interaction.response.send_message('Cannot decline queue after clicking ready.', ephemeral=True)
            elif user in decline_ready_players:
                if game_in_progress:
                    game_in_progress = False
                    await decline_and_requeue(user, interaction.message.channel)
            else:
                decline_ready_players.add(user)
                await interaction.response.send_message('Are you sure you want to decline the queue?  Click again to confirm.', ephemeral=True)
        else:
            await interaction.response.send_message('You are not in the queue.', ephemeral=True)

# New function to decline ready and go back to queue
async def decline_and_requeue(user, channel):
    global phase, ready_up_task
    phase = Phase.READY
    # Cancel the ready-up task to prevent it from running after this point
    if ready_up_task is not None:
        ready_up_task.cancel()
        ready_up_task = None
        
    await channel.send(f"{user} declined the queue. Re-queuing {len(queue) - 1} other players.")
    await remove_ready_message()  # Remove the ready check message and buttons
    queue.remove(user)    # Remove the player who declined from the queue
    ready_players.clear()  # Clear the ready players set for the next ready check
    decline_ready_players.clear()  # Clear the unconfirmed declined players set for the next ready check
    await remove_old_queue_message()  # Remove the old queue message
    await start_new_queue(channel)  # Post a new queue message with ready players

# New function to proceed to map voting
async def proceed_to_map_voting(channel):
    global phase, map_votes, map_voted_users, map_voting_message, ready_up_task
    phase = Phase.MAP
    # Cancel the ready-up task to prevent it from running after this point
    if ready_up_task is not None:
        ready_up_task.cancel()
        ready_up_task = None

    await remove_ready_message()  # Remove the ready check message and buttons

    map_votes.clear()  # Clear votes only at the start of new matchups
    map_voted_users.clear()  # Reset users who voted
    map_voting_message = None

    # Create the embed message
    embed = discord.Embed(title='Map Voting', description='Vote for the map you want to play on.', color=discord.Color.green())
    for map_name in map_choices:
        embed.add_field(name=map_name, value=f'Votes: {map_votes[map_name]}', inline=False)

    # Send the message with the MapVotingView
    map_voting_message = await channel.send(embed=embed, view=MapVotingView())

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
            await interaction.response.send_message('This button is no longer active.', ephemeral=True)
            return
        
        user = interaction.user

        if user not in ready_players:
            await interaction.response.send_message('You are not part of the game.', ephemeral=True)
            return

        # Allow user to change their vote
        if user in map_voted_users:
            map_previous_vote = map_voted_users[user]
            if map_previous_vote == "map_name":
                await interaction.response.send_message(f'You have already voted for {map_name}.', ephemeral=True)
                return
            else:
                map_votes[map_previous_vote] -= 1  # Remove their previous map vote

        map_votes[map_name] += 1
        map_voted_users[user] = map_name
        await interaction.response.send_message(f'You voted for {map_name}.', ephemeral=True)

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
    global map_voting_message
    if map_voting_message:
        embed = discord.Embed(title='Map Voting', description='Vote for the map you want to play on.', color=discord.Color.green())
        for map_name in map_choices:
            embed.add_field(name=map_name, value=f'Votes: {map_votes[map_name]}', inline=False)
        await map_voting_message.edit(embed=embed)

# Function to declare the selected map and proceed to matchups
async def declare_selected_map(channel, selected_map):
    await channel.send(f"The selected map is **{selected_map}**!")
    # Proceed to matchup voting
    await proceed_to_matchups_phase(channel)   

# Adjusted function to proceed to matchups
async def proceed_to_matchups_phase(channel):
    global phase, matchups, votes, voted_users, voting_message
    phase = Phase.MATCHUP
    players = list(ready_players)
    matchups = []
    votes.clear()  # Clear votes only at the start of new matchups
    voted_users.clear()  # Reset users who voted

    # Generate matchups for 5v5
    for _ in range(3):
        random.shuffle(players)
        team1 = players[:5]  # 5 players on team 1
        team2 = players[5:]  # 5 players on team 2
        team1.sort(key=get_display_name)
        team2.sort(key=get_display_name)
        matchups.append((team1.copy(), team2.copy()))

    # Display the matchups
    await display_matchup_votes(channel)

# Function to display the voting embed with votes count and enhanced readability
async def display_matchup_votes(channel):
    global reroll_votes, voting_message
    embed = discord.Embed(title='Matchup Voting', description='Vote for your preferred matchup or vote to re-roll.\n——————————————————————',
                          color=discord.Color.green())

    for idx, (team1, team2) in enumerate(matchups, 1):
        team1_names = '\n'.join([get_display_name(user) for user in team1])
        team2_names = '\n'.join([get_display_name(user) for user in team2])
        embed.add_field(name='Team 1', value=team1_names, inline=True)
        embed.add_field(name='Team 2', value=team2_names, inline=True)
        embed.add_field(name=f'Matchup {idx} ({votes[idx]} votes)',
                        value='——————————————————————',
                        inline=False)

    # Clearer re-roll option with votes
    embed.add_field(name=f'Re-roll Matchups ({reroll_votes} votes)',
                    value='Vote to re-roll all matchups and generate new ones.', 
                    inline=False)

    # If the voting message exists, edit it, otherwise send a new one
    if voting_message:
        await voting_message.edit(embed=embed)
    else:
        voting_message = await channel.send(embed=embed, view=VotingView())

# View for voting on matchups
class VotingView(View):
    def __init__(self):
        super().__init__(timeout=None)  # No timeout

    @discord.ui.button(label='Vote Matchup 1', style=discord.ButtonStyle.primary, custom_id='vote_1')
    async def vote_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, 1)

    @discord.ui.button(label='Vote Matchup 2', style=discord.ButtonStyle.primary, custom_id='vote_2')
    async def vote_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, 2)

    @discord.ui.button(label='Vote Matchup 3', style=discord.ButtonStyle.primary, custom_id='vote_3')
    async def vote_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, 3)

    @discord.ui.button(label='Vote Re-roll', style=discord.ButtonStyle.secondary, custom_id='vote_reroll')
    async def vote_reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_reroll_vote(interaction)

    async def register_vote(self, interaction, matchup_number):
        global final_matchup_sent  # To ensure the final matchup is only sent once
        # do nothing if no longer in team voting phase
        if phase != Phase.MATCHUP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True)
            return
        
        user = interaction.user

        if user not in ready_players:
            await interaction.response.send_message('You are not part of the game.', ephemeral=True)
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

        await interaction.response.send_message(f'You voted for Matchup {matchup_number}.', ephemeral=True)

        # Check if any matchup has 5 votes (for 5v5)
        if votes[matchup_number] >= votes_required and not final_matchup_sent:
            final_matchup_sent = True  # Ensure this block runs only once
            await declare_matchup(interaction.message.channel, matchup_number)
        else:
            await display_matchup_votes(interaction.message.channel)

    async def register_reroll_vote(self, interaction):
        global reroll_votes, votes, voted_users
        # do nothing if no longer in team voting phase
        if phase != Phase.MATCHUP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True)
            return
        
        user = interaction.user

        if user not in ready_players:
            await interaction.response.send_message('You are not part of the game.', ephemeral=True)
            return

        # Allow user to change vote if they already voted for re-roll
        if user in voted_users:
            previous_vote = voted_users[user]
            if previous_vote == "reroll":
                await interaction.response.send_message('You have already voted to re-roll.', ephemeral=True)
                return
            else:
                votes[previous_vote] -= 1  # Remove their previous matchup vote

        reroll_votes += 1
        voted_users[user] = "reroll"

        await interaction.response.send_message('You voted to re-roll the matchups.', ephemeral=True)

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
    global phase, waiting_room_message, final_matchup_players

    phase = Phase.PLAY
    team1, team2 = matchups[matchup_number - 1]
    final_matchup_players = set(team1 + team2)  # Mark players in Final Matchup
    team1_names = ', '.join([get_display_name(user) for user in team1])
    team2_names = ', '.join([get_display_name(user) for user in team2])

    embed = discord.Embed(title='Final Matchup', color=discord.Color.gold())
    embed.add_field(name='Map', value=selected_map, inline=False)
    embed.add_field(name='Team 1', value=team1_names, inline=False)
    embed.add_field(name='Team 2', value=team2_names, inline=False)
    embed.set_footer(text='Good luck and have fun!')

    await channel.send(embed=embed, view=ResetQueueView())

    # Create the new waiting room after final matchup
    await create_waiting_room(channel)


# Create a waiting room for players not in the Final Matchup
async def create_waiting_room(channel):
   global waiting_room, waiting_room_message


   # Populate the waiting room with players not in the final matchup
   waiting_room = [user for user in queue if user not in final_matchup_players]


   embed = discord.Embed(
       title="Waiting Room",
       description="Players not in the Current Matchup can join the waiting room.",
       color=discord.Color.purple()
   )


   waiting_room_names = ', '.join([get_display_name(user) for user in waiting_room]) or 'No players in waiting room.'
   embed.add_field(name='Players in Waiting Room', value=waiting_room_names, inline=False)


   if waiting_room_message:
       await waiting_room_message.edit(embed=embed, view=WaitingRoomView())
   else:
       waiting_room_message = await channel.send(embed=embed, view=WaitingRoomView())


# View for the waiting room buttons
class WaitingRoomView(View):
   def __init__(self):
       super().__init__(timeout=None)


   @discord.ui.button(label='Join Waiting Room', style=discord.ButtonStyle.green)
   async def join_waiting_room(self, interaction: discord.Interaction, button: discord.ui.Button):
       user = interaction.user
       if len(waiting_room) >= 9:
           await interaction.response.send_message(
               'The waiting room is full (10/10 players). Please wait for the next game.', ephemeral=True)
           return
       if user in final_matchup_players:
           await interaction.response.send_message('You are in the current matchup and cannot join the waiting room.',
                                                   ephemeral=True)
       elif user in waiting_room:
           await interaction.response.send_message('You are already in the waiting room.', ephemeral=True)
       else:
           waiting_room.append(user)
           await interaction.response.send_message(f'{user.mention} joined the waiting room.', ephemeral=True)
           await update_waiting_room_message()


   # New button to leave the waiting room
   @discord.ui.button(label='Leave Waiting Room', style=discord.ButtonStyle.red)
   async def leave_waiting_room(self, interaction: discord.Interaction, button: discord.ui.Button):
       user = interaction.user
       if user in waiting_room:
           waiting_room.remove(user)
           await interaction.response.send_message(f'{user.mention} left the waiting room.', ephemeral=True)
           await update_waiting_room_message()
       else:
           await interaction.response.send_message('You are not in the waiting room.', ephemeral=True)


# Function to update the waiting room message
async def update_waiting_room_message():
   global waiting_room_message
   if waiting_room_message:
       waiting_room_names = ', '.join(
           [get_display_name(user) for user in waiting_room]) or 'No players in waiting room.'
       embed = discord.Embed(
           title="Waiting Room",
           description="Players not in the Current Matchup can join the waiting room.",
           color=discord.Color.purple()
       )
       embed.add_field(name='Players in Waiting Room', value=waiting_room_names, inline=False)
       await waiting_room_message.edit(embed=embed, view=WaitingRoomView())


# View for resetting the queue with voting
class ResetQueueView(View):
   def __init__(self):
       super().__init__(timeout=None)


   @discord.ui.button(label='Vote to Reset Queue', style=discord.ButtonStyle.danger)
   async def reset_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
       await self.register_reset_vote(interaction)


   async def register_reset_vote(self, interaction):
       global reset_queue_votes, reset_voted_users, reset_in_progress
       user = interaction.user
       if user in reset_voted_users:
           await interaction.response.send_message('You have already voted to reset the queue.', ephemeral=True)
           return


       # Only allow Final Matchup players to reset the queue
       if user not in final_matchup_players:
           await interaction.response.send_message(
               'You are not in the Current Matchup and cannot vote to reset the queue.', ephemeral=True)
           return


       if reset_in_progress:  # Prevent triggering multiple resets
           await interaction.response.send_message('Queue reset is already in progress.', ephemeral=True)
           return


       reset_queue_votes += 1
       reset_voted_users.add(user)
       await interaction.response.send_message(
           f'{user.mention} voted to reset the queue ({reset_queue_votes}/{reset_queue_votes_required} votes).',
           ephemeral=True)


       # Display votes and check if the required number of votes have been reached
       if reset_queue_votes >= reset_queue_votes_required and not reset_in_progress:
           reset_in_progress = True  # Prevent multiple resets
           await interaction.message.channel.send('Queue has been reset by vote.')
           await self.remove_buttons(interaction)  # Remove buttons after reset
           await self.restart_queue(interaction.message.channel)  # Reset the queue and send a new queue message
       elif not reset_in_progress:
           await interaction.message.channel.send(
               f'Reset queue votes: {reset_queue_votes}/{reset_queue_votes_required}.')


   async def remove_buttons(self, interaction):
       # Disable buttons after the queue is reset
       for child in self.children:
           child.disabled = True
       await interaction.message.edit(view=None)  # Edit the message to remove buttons


   async def restart_queue(self, channel):
       reset_game()  # Reset the game state first
       await add_waiting_room_to_queue(channel)  # Now add waiting room players to the empty queue
       await remove_old_queue_message()  # Remove the old queue message
       await start_new_queue(channel)  # Start a new queue with waiting room players


# Add waiting room players to the new queue
async def add_waiting_room_to_queue(channel):
   global waiting_room, queue


   queue[:] = waiting_room  # Move waiting room players to queue
   waiting_room.clear()  # Clear the waiting room


   if queue_message:
       await update_queue_message()  # Update the queue message


# Start a new queue programmatically without needing the command context
async def start_new_queue(channel):
   global phase, queue_message, waiting_room_message
   phase = Phase.QUEUE
   # Send a completely new queue message instead of editing the old one
   queue_names = ', '.join([get_display_name(user) for user in queue]) or 'No players in queue.'
   embed = discord.Embed(title='PUGs Queue',
                         description=f'Players in queue ({len(queue)}/{queue_size_required}): {queue_names}',
                         color=discord.Color.blue())
   queue_message = await channel.send(embed=embed, view=QueueView())


   # Remove the old waiting room message
   if waiting_room_message:
       try:
           await waiting_room_message.delete()
       except discord.NotFound:
           print("Waiting room message was already deleted.")
       waiting_room_message = None


# Function to remove the old queue message
async def remove_old_queue_message():
   global queue_message
   if queue_message:
       try:
           await queue_message.delete()
       except discord.NotFound:
           print("Queue message was already deleted.")
       queue_message = None


# Function to remove the ready message and buttons
async def remove_ready_message():
   global ready_message
   if ready_message:
       try:
           await ready_message.delete()
       except discord.NotFound:
           print("Ready message was already deleted.")
       ready_message = None


# Command to end the PUG system
@bot.command(name='end_pug')
async def end_pug(ctx):
   global game_in_progress, queue_message


   if game_in_progress or queue:
       reset_game()  # Reset the game state
       await ctx.send('The current PUG session has been ended. You can start a new queue with `!start_pug`.')
       if queue_message:
           await queue_message.edit(embed=discord.Embed(title="PUGs Queue", description="The PUG has been canceled.",
                                                        color=discord.Color.red()), view=None)
   else:
       await ctx.send('No PUG session is currently active.')


# Command to start the PUG system
@bot.command(name='start_pug')
async def start_pug(ctx):
   global phase, queue_message
   if not game_in_progress and not queue:
       phase = Phase.QUEUE
       queue_message = await ctx.send(
           embed=discord.Embed(title="PUGs Queue", description="No players in queue.", color=discord.Color.blue()),
           view=QueueView())
   else:
       await ctx.send('A game is already in progress or the queue is active.')
       
# Command to start the PUG system in the gig esports #pugs-queue channel
@bot.command(name='start_pug_gigesports')
async def start_pug(ctx):
   global phase, queue_message
   if not game_in_progress and not queue:
       phase = Phase.QUEUE
       queue_channel = ctx.guild.get_channel(1293818329118539847)
       queue_message = await queue_channel.send(
           embed=discord.Embed(title="PUGs Queue", description="No players in queue.", color=discord.Color.blue()),
           view=QueueView())
   else:
       await ctx.send('A game is already in progress or the queue is active.')
       
# Command to manually add users to the queue
@bot.command(name='queue_users')
async def queue_users(ctx, members: commands.Greedy[discord.Member], *):
    if not game_in_progress and queue:
        for member in members:
            queue.add(member.user)
      await ctx.send(f'Added {len(members)} players to queue.')
    else:
      await ctx.send('Cannot queue players, a game is already in progress.')
      
# Command to store the current queue to a file
@bot.command(name='store_queue')
async def store_queue(ctx):
   if not game_in_progress and queue:
      with open(queue_file_path, 'w') as queue_file:
         queue_file.write('\n'.join(str(user.id) for user in queue))
      await ctx.send(f'Queue stored with {len(queue)} players.')
   else:
      await ctx.send('Cannot store queue, a game is already in progress.')
      
# Command to restore the saved queue from a file
@bot.command(name='restore_queue')
async def restore_queue(ctx):
   global queue
   if not game_in_progress:
      if os.path.isfile(queue_file_path):
          queue = []
          with open(queue_file_path, 'r') as queue_file:
              for id_line in queue_file:
                try:
                    user_id = int(id_line.strip())
                    user = await ctx.bot.fetch_user(user_id)
                    queue.add(user)
                except ValueError:
                    
          os.remove(queue_file_path)
          await ctx.send(f'Queue restored with {len(queue)} players.')
      else:
          await ctx.send('No saved queue found.')
   else:
      await ctx.send('Cannot restore queue, a game is already in progress.')


# Run the bot
bot.run(TOKEN)