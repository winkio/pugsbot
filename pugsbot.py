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

class RequeueOrder(IntEnum):  # Re-queue order enum
    QUEUE_ORDER = 1
    RANDOM = 2
    PLAY_TIME = 3
    NUM_GAMES = 4
    NUM_WOUNDS = 5

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
re_queue_order = RequeueOrder.NUM_WOUNDS  # order to use when re-queueing players in a match
recent_time = timedelta(hours=3)  # if ordering by playtime or wounds, only look at games in the last 3 hours
max_matches_in_memory = 10  # Only hold onto the last 10 matches in memory
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
    6: 'Queue-icide',
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
    'ct1': '!ct1 - use with user names to set Team 1 for Custom teams',
    'ct2': '!ct2 - use with user names to set Team 2 for Custom teams',
    'trade': '!trade - trades two players on opposite teams',
    'fill': '!fill - replaces a player in the match with one not in the match',
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
    print(f'{get_timestamp()} - Logged in as {bot.user.name} ({bot.user})')

class Phase(IntEnum):  # Phase enum
    NONE = 1
    QUEUE = 2
    READY = 3
    MAP = 4
    MATCHUP = 5
    PLAY = 6
    RESET = 7

class PugMatch():  # holds data for a single pug match
    def __init__(self, match_number, players):
        self.phase = Phase.MAP
        self.initial_players = list(players)  # Initial players that accepted queue
        self.players = list(players)  # Players in match
        self.re_queue = list(players)  # Players re-queueing after current match
        #random.shuffle(self.re_queue)  # Randomize re-queue order
        self.match_number = match_number  # Match number
        self.setup_start_time = datetime.now(timezone.utc)  # Start time of match setup
        
        self.map_votes = defaultdict(int)
        self.map_voted_users = {}  # Track individual votes for changeable votes
        self.selected_map = None  # To store the selected map
        self.selected_map_sent = False # Track if the selected map has already been sent
        self.map_voting_message = None  # To store the map voting message

        self.matchups = []
        self.custom_team1 = []  # custom team 1 users
        self.custom_team2 = []  # custom team 2 users
        self.votes = defaultdict(int)
        self.voted_users = {}  # Track individual votes for changeable votes
        self.selected_matchup = None  # To store the selected matchup
        self.final_matchup_sent = False  # Track if the final matchup has already been sent
        self.voting_message = None

        self.final_team1 = None
        self.final_team2 = None
        self.final_team1_names = None
        self.final_team2_names = None
        self.start_time = None
        self.end_time = None
        self.scoreboard_filename = None
        self.wound_score = 0
        self.reset_queue_votes = 0
        self.reset_voted_users = set()
        self.reset_in_progress = False  # Flag to prevent multiple resets
        self.final_matchup_message = None  # For the final matchup message
        self.waiting_room_message = None  # For the waiting room message
    
    # Sets the phase of this match
    def set_phase(self, new_phase):
        global phase
        phase = new_phase
        self.phase = new_phase
    
    # updates the re-queue
    def update_re_queue(self):
        self.re_queue = list(players)  # Players re-queueing after current match
        if re_queue_order == RequeueOrder.RANDOM:  # Randomize re-queue order
            random.shuffle(self.re_queue)  
        else:  # sort re-queue order
            self.re_queue.sort(key=re_queue_sort_key)
    
    # Proceed to map voting
    async def proceed_to_map_voting(self, channel):
        embed = self.map_voting_embed()
        # Send the message with the MapVotingView
        self.map_voting_message = await channel.send(embed=embed, view=MapVotingView(self))

    # Gets the vote pip string for a given map
    def map_vote_pips(self, game_map: GameMap):
        if game_map == self.selected_map:
            return f'\u200b{vote_win_pip * self.map_votes[game_map]}'
        return f'\u200b{vote_pip * self.map_votes[game_map]}'

    # Makes the map voting embed
    def map_voting_embed(self):
        embed = discord.Embed(title='Map Vote', color=discord.Color.green())
        for game_map in map_choices:
            embed.add_field(name=str(game_map), value=self.map_vote_pips(game_map), inline=True)
        # add extra empty fields so that there are 3 fields per row
        for _ in range(-len(map_choices) % 3):
            embed.add_field(name='\u200b', value='\u200b', inline=True)
        return embed
                
    # Update the map voting message
    async def update_map_voting_message(self):
        if self.map_voting_message:
            embed = self.map_voting_embed()
            if self.phase != Phase.MAP:
                await self.map_voting_message.edit(embed=embed, view=None)  # remove buttons if not voting
            else:
                await self.map_voting_message.edit(embed=embed)
    
    # handles a user voting for a map
    async def register_map_vote(self, interaction, game_map):
        # do nothing if no longer in map voting phase
        if self.phase != Phase.MAP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True, delete_after=msg_fade1)
            return
        
        user = interaction.user
        if user not in self.players:
            await interaction.response.send_message('You are not part of the match.', ephemeral=True, delete_after=msg_fade1)
            return

        # Allow user to change their vote
        if user in self.map_voted_users:
            map_previous_vote = self.map_voted_users[user]
            if map_previous_vote == game_map:
                await interaction.response.send_message(f'You have already voted for {game_map}.', ephemeral=True, delete_after=msg_fade1)
                return
            else:
                self.map_votes[map_previous_vote] -= 1  # Remove their previous map vote

        self.map_votes[game_map] += 1
        self.map_voted_users[user] = game_map
        await interaction.response.send_message(f'You voted for {game_map}.', ephemeral=True, delete_after=msg_fade2)

        # Update the voting message
        await self.update_map_voting_message()

        # Check if the map has 5 votes (for 5v5)
        if (self.map_votes[game_map] >= votes_required) and not self.selected_map_sent:
            self.selected_map_sent = True
            self.selected_map = game_map
            await self.declare_selected_map(interaction.message.channel)
        # Check if 7 votes have been cast
        elif len(self.map_voted_users) >= map_total_votes_required and not self.selected_map_sent:
            self.selected_map_sent = True
            # Determine the map(s) with the most votes (in case of tie)
            max_votes = max(self.map_votes.values())
            top_maps = [gm for gm, count in self.map_votes.items() if count == max_votes]
            self.selected_map = random.choice(top_maps)  # If tie, select randomly among top maps
            await self.declare_selected_map(interaction.message.channel)

    # Function to declare the selected map and proceed to matchups
    async def declare_selected_map(self, channel):
        await self.proceed_to_matchups_phase(channel)
        await self.update_map_voting_message()  # final update of map vote message

    # Adjusted function to proceed to matchups
    async def proceed_to_matchups_phase(self, channel):
        self.set_phase(Phase.MATCHUP)
        player_pool = list(self.players)
        unique_team_ids = set()
        # if team size is greater than 2, avoid rerolling a team from the last set of matchups
        if team_size > 2 and self.matchups:
            for team1, team2 in self.matchups:
                team1_ids = ' '.join([str(user.id) for user in team1])
                team2_ids = ' '.join([str(user.id) for user in team2])
                unique_team_ids.add(team1_ids)
                unique_team_ids.add(team2_ids)
                
        # clear old matchups and votes
        self.matchups = []
        self.votes.clear()  # Clear votes only at the start of new matchups
        self.voted_users.clear()  # Reset users who voted

        # Generate matchups for 5v5
        while len(self.matchups) < 3:
            random.shuffle(player_pool)
            team1 = player_pool[:team_size]  # 5 players on team 1
            team2 = player_pool[team_size:]  # 5 players on team 2
            team1.sort(key=user_sort_key)
            team2.sort(key=user_sort_key)
            team1_ids = ' '.join([str(user.id) for user in team1])
            team2_ids = ' '.join([str(user.id) for user in team2])
            # check to make sure that generated matchup is unique before adding it
            if team1_ids not in unique_team_ids:
                unique_team_ids.add(team1_ids)
                unique_team_ids.add(team2_ids)
                self.matchups.append((team1.copy(), team2.copy()))
                
        # Display the matchups
        await self.display_matchup_votes(channel)
    
    # gets the vote pip string for a given matchup
    def matchup_vote_pips(self, m):
        if m == self.selected_matchup:
            return f' {vote_win_pip * self.votes[m]}'
        return f' {vote_pip * self.votes[m]}'

    # Function to display the voting embed with votes count and enhanced readability
    async def display_matchup_votes(self, channel):
        if self.phase == Phase.MATCHUP:
            embed = discord.Embed(title='Matchup Vote', description='Vote for your preferred matchup or vote to re-roll.',
                                  color=discord.Color.green())
        else:
            embed = discord.Embed(title='Matchup Vote', color=discord.Color.green())

        for idx, (team1, team2) in enumerate(self.matchups, 1):
            embed.add_field(name=divider,
                            value=f'**Matchup {idx}**{self.matchup_vote_pips(idx)}',
                            inline=False)
            team1_names = '\n'.join([get_display_name(user) for user in team1])
            team2_names = '\n'.join([get_display_name(user) for user in team2])
            embed.add_field(name='Team 1', value=team1_names, inline=True)
            embed.add_field(name='Team 2', value=team2_names, inline=True)

        # Clearer re-roll option with votes
        if self.phase == Phase.MATCHUP:
            reroll_text = f'**Re-roll Matchups**{self.matchup_vote_pips(reroll_key)}\nVote to re-roll all matchups and generate new ones.'
        elif self.votes[reroll_key]:
            reroll_text = f'**Re-roll Matchups**{self.matchup_vote_pips(reroll_key)}'
        else:
            reroll_text = ''
        if reroll_text:
            embed.add_field(name=divider, value=reroll_text, inline=False)

        # Custom teams
        if self.phase == Phase.MATCHUP:
            custom_teams_text = f'**Custom**{self.matchup_vote_pips(custom_teams_key)}\nUse !ct1 and !ct2 to set custom teams.'
        elif self.votes[custom_teams_key] or self.custom_team1 or self.custom_team2:
            custom_teams_text = f'**Custom**{self.matchup_vote_pips(custom_teams_key)}'
        else:
            custom_teams_text = ''
        if custom_teams_text:
            embed.add_field(name=divider, value=custom_teams_text, inline=False)
            if self.custom_team1 or self.custom_team2:
                team1_names = '\n'.join([get_display_name(user) for user in self.custom_team1])
                team2_names = '\n'.join([get_display_name(user) for user in self.custom_team2])
                embed.add_field(name='Team 1', value=team1_names, inline=True)
                embed.add_field(name='Team 2', value=team2_names, inline=True)

        # If the voting message exists, edit it, otherwise send a new one
        if self.voting_message:
            if self.phase != Phase.MATCHUP:
                await self.voting_message.edit(embed=embed, view=None)
            else:
                await self.voting_message.edit(embed=embed)
        else:
            self.voting_message = await channel.send(embed=embed, view=MatchupVotingView(self))
    
    # Gets a string representation of the matchup    
    def get_matchup_str(self, m):
        if m == reroll_key:
            return 'Re-roll Matchups'
        if m == custom_teams_key:
            return 'Custom matchup'
        return f'Matchup {m}'
    
    # handles registering a matchup vote
    async def register_matchup_vote(self, interaction, m):
        # do nothing if no longer in team voting phase
        if self.phase != Phase.MATCHUP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True, delete_after=msg_fade1)
            return
        
        user = interaction.user
        if user not in self.players:
            await interaction.response.send_message('You are not part of the match.', ephemeral=True, delete_after=msg_fade1)
            return
        if user in self.voted_users:  # if already voted
            previous_vote = self.voted_users[user]
            if previous_vote == m:  # check if same vote
                await interaction.response.send_message(f'You have already voted for {self.get_matchup_str(m)}.', ephemeral=True, delete_after=msg_fade1)
                return
            self.votes[previous_vote] -= 1  # remove their previous vote
        self.voted_users[user] = m  # set user vote
        self.votes[m] += 1  # update matchup vote count
        await interaction.response.send_message(f'You voted for {self.get_matchup_str(m)}.', ephemeral=True, delete_after=msg_fade2)

        # Check if any matchup type has enough votes
        if self.votes[m] >= votes_required:
            if m == reroll_key:
                await interaction.message.channel.send('Re-rolling the matchups!')
                await self.proceed_to_matchups_phase(interaction.message.channel)
                return
            elif m == custom_teams_key and not self.final_matchup_sent:
                self.final_matchup_sent = True  # Ensure this block runs only once
                await self.declare_matchup(interaction.message.channel, -1)
            elif not self.final_matchup_sent:
                self.final_matchup_sent = True  # Ensure this block runs only once
                await self.declare_matchup(interaction.message.channel, m)

        # Update the voting message
        await self.display_matchup_votes(interaction.message.channel)
    
    # Declare the chosen matchup
    async def declare_matchup(self, channel, matchup_number):
        global results_match
        self.set_phase(Phase.PLAY)
        results_match = self
        self.start_time = datetime.now(timezone.utc)
        if matchup_number == -1:  # custom teams
            self.selected_matchup = custom_teams_key
            self.final_team1 = self.custom_team1
            self.final_team2 = self.custom_team2
        else:
            self.selected_matchup = matchup_number
            self.final_team1, self.final_team2 = self.matchups[matchup_number - 1]
        self.final_team1_names = ', '.join([get_display_name(user) for user in self.final_team1]) or 'custom'
        self.final_team2_names = ', '.join([get_display_name(user) for user in self.final_team2]) or 'custom'

        embed = self.final_matchup_embed()
        self.final_matchup_message = await channel.send(embed=embed, view=FinalMatchupView(self))

        # Create the new waiting room after final matchup
        await create_waiting_room(channel)
        await update_queue_message() # single update of queue message for new phase
    
    # Updates the final matchup message
    async def update_final_matchup(self):
        embed = self.final_matchup_embed()
        if self.final_matchup_message:
            if self.phase != Phase.PLAY:
                all_mentions = ' '.join([user.mention for user in self.players])
                content = f'-# pug_mh {self.match_number} {self.selected_map.name.casefold()} {all_mentions}'
                await self.final_matchup_message.edit(content=content, embed=embed, view=None)
            else:
                await self.final_matchup_message.edit(embed=embed)

    # gets the matchup length in seconds
    def matchup_length(self):
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    # gets the matchup length string
    def matchup_length_str(self):
        if self.end_time:
            return f'{int(round((self.end_time - self.start_time).total_seconds() / 60))} min - '
        return ''

    # gets the score display string for the given team
    def score_display(self, team_number):
        if ((team_number == 1 and self.wound_score > 0) or
            (team_number == 2 and self.wound_score < 0)):
            return f'🏆 - {"❤️ " * abs(self.wound_score)}'
        return ''

    # Function to make the final matchup embed
    def final_matchup_embed(self):
        time_int = datetime_to_int(self.start_time)
        embed = discord.Embed(title=f'Final Matchup #{self.match_number}', 
                              description=f'**{self.selected_map}** - {self.matchup_length_str()}*<t:{time_int}:d><t:{time_int}:t>*',
                              color=discord.Color.gold())
        embed.add_field(name=f'Team 1 {self.score_display(1)}', value=self.final_team1_names, inline=False)
        embed.add_field(name=f'Team 2 {self.score_display(2)}', value=self.final_team2_names, inline=False)
        if self.wound_score == 0 and self.phase <= Phase.PLAY:
            embed.add_field(name='Remaining Wounds', value='Report result with !wounds x.  + for Team1, - for Team2', inline=False)
        if self.scoreboard_filename:
            embed.set_image(url=f'attachment://{self.scoreboard_filename}')
        elif self.phase <= Phase.PLAY:
            embed.add_field(name='Scoreboard', value='Use the !sb command with an attached image.', inline=False)
        if self.phase <= Phase.PLAY:
            embed.set_footer(text='Good luck and have fun! ')
        return embed
    
    # Handles a match complete vote
    async def register_reset_vote(self, interaction):
        user = interaction.user
        if user in self.reset_voted_users:
            await interaction.response.send_message('You have already marked the match as complete.', ephemeral=True, delete_after=msg_fade1)
            return
        if user not in self.players:
            await interaction.response.send_message('You are not in the current match and cannot mark the match as complete.', ephemeral=True, delete_after=msg_fade1)
            return
        if self.reset_in_progress:  # Prevent triggering multiple resets
            await interaction.response.send_message('Queue reset is already in progress.', ephemeral=True, delete_after=msg_fade1)
            return
           
        self.reset_queue_votes += 1
        self.reset_voted_users.add(user)
        await interaction.response.send_message(
            f'{user.mention} marked the match as complete ({self.reset_queue_votes}/{reset_queue_votes_required} votes).',
            ephemeral=True, delete_after=msg_fade2)
       
        await update_waiting_room_message()  # update reset vote display
        # Check if the required number of votes have been reached
        if self.reset_queue_votes >= reset_queue_votes_required and not self.reset_in_progress:
            self.reset_in_progress = True  # Prevent multiple resets
            await interaction.message.channel.send(f'Match #{self.match_number} marked as complete by vote.  Resetting queue...')
            await restart_queue(interaction.message.channel)  # Reset the queue and send a new queue message

    # replaces a player in the match
    async def replace_player(self, p_out, p_in, channel):
        replace_list_item(self.players, p_out, p_in)
        replace_list_item(self.re_queue, p_out, p_in)
        if self.phase == Phase.MAP:
            if p_out in self.map_voted_users:  # remove map vote
                previous_vote = self.map_voted_users[p_out]
                self.map_votes[previous_vote] -= 1
                del self.map_voted_users[p_out]
            await self.update_map_voting_message()  # update embed
        elif self.phase == Phase.MATCHUP:
            if p_out in self.voted_users:  # remove matchup vote
                previous_vote = self.voted_users[p_out]
                self.votes[previous_vote] -= 1
                del self.voted_users[p_out]
            for team1, team2 in self.matchups:  # replace player in teams
                if p_out in team1:
                    replace_list_item(team1, p_out, p_in)
                    team1.sort(key=user_sort_key)
                elif p_out in team2:
                    replace_list_item(team2, p_out, p_in)
                    team2.sort(key=user_sort_key)
            if self.custom_team1 and p_out in self.custom_team1:  # replace player in custom teams
                replace_list_item(self.custom_team1, p_out, p_in)
                self.custom_team1.sort(key=user_sort_key)
            elif self.custom_team2 and p_out in self.custom_team2:
                replace_list_item(self.custom_team2, p_out, p_in)
                self.custom_team2.sort(key=user_sort_key)
            await self.display_matchup_votes(channel)  # update embed
        elif self.phase == Phase.PLAY:
            if p_out in self.reset_voted_users:  # remove reset vote
                self.reset_queue_votes -= 1
                self.reset_voted_users.remove(p_out)
            if p_out in self.final_team1:  # replace player in teams
                replace_list_item(self.final_team1, p_out, p_in)
                self.final_team1.sort(key=user_sort_key)
                self.final_team1_names = ', '.join([get_display_name(user) for user in self.final_team1]) or 'custom'
            elif p_out in self.final_team2:
                replace_list_item(self.final_team2, p_out, p_in)
                self.final_team2.sort(key=user_sort_key)
                self.final_team2_names = ', '.join([get_display_name(user) for user in self.final_team2]) or 'custom'
            await self.update_final_matchup()  # update embed
            
    
    # updates UI when custom teams are changed
    async def on_custom_teams_changed(self, channel):
        self.custom_team1.sort(key=user_sort_key)
        self.custom_team2.sort(key=user_sort_key)
        if self.phase == Phase.MATCHUP:
            await self.display_matchup_votes(channel)
        elif self.phase == Phase.PLAY:
            self.final_team1 = self.custom_team1
            self.final_team2 = self.custom_team2
            self.final_team1_names = ', '.join([get_display_name(user) for user in self.final_team1]) or 'custom'
            self.final_team2_names = ', '.join([get_display_name(user) for user in self.final_team2]) or 'custom'
            await self.update_final_matchup()
    
    # updates UI when final teams are changed by a trade or fill
    async def on_final_teams_changed(self, channel):
        self.final_team1.sort(key=user_sort_key)
        self.final_team2.sort(key=user_sort_key)
        self.final_team1_names = ', '.join([get_display_name(user) for user in self.final_team1]) or 'custom'
        self.final_team2_names = ', '.join([get_display_name(user) for user in self.final_team2]) or 'custom'
        if self.selected_matchup == custom_teams_key:
            self.custom_team1 = self.final_team1
            self.custom_team2 = self.final_team2
        if self.phase == Phase.MATCHUP:
            await self.display_matchup_votes(channel)
        elif self.phase == Phase.PLAY:
            await self.update_final_matchup()
    
    # updates final matchup start time to the current time
    def update_start_time(self):
        if self.phase == Phase.PLAY and not self.end_time:
            self.start_time = datetime.now(timezone.utc)

    # updates final matchup end time to the current time
    def update_end_time(self):
        if self.phase >= Phase.PLAY and not self.end_time:
            self.end_time = datetime.now(timezone.utc)
    
    # updates the scoreboard for the match
    async def update_scoreboard(self, ctx, scoreboard_img):
        self.scoreboard_filename = scoreboard_img.filename
        await self.final_matchup_message.edit(attachments=[scoreboard_img])
        await self.update_final_matchup()
        await ctx.send(f'Updated scoreboard for Match #{self.match_number}.')
        self.update_end_time()  # update match end time
    
    # updates the number of remaining wounds for the match
    async def update_wounds(self, ctx, score):
        new_score = max(-3, min(3, score))
        if self.wound_score == new_score:
            await ctx.send(f'The remaining wounds of Match #{self.match_number} have already been set to {new_score}.')
            return
        self.wound_score = new_score
        await self.update_final_matchup()
        if self.wound_score == 0:
            await ctx.send(f'The winner and remaining wounds of Match #{self.match_number} have been cleared.')
        else:
            win_team = (-self.wound_score // abs(self.wound_score) + 1) // 2 + 1
            await ctx.send(f'Team {win_team} is the winner of Match #{self.match_number} with {abs(self.wound_score)} wounds remaining.')
    
# Global variables to keep track of the queue and game states
phase = Phase.NONE
queue = []  # Players in queue
waiting_room = []  # Players in waiting room
matches = {}  # dict of matches (int, PugMatch)
match_number = 1  # Match number
current_match = None  # Current match being set up or played
results_match = None  # Most recent match to update results
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

waiting_room_message = None  # For the waiting room message


# Helper function to reset the game state but keep the waiting room intact
def reset_game():
    global phase, queue, game_in_progress, queue_message
    global queue_sorted, ready_players, bailouts_unc, bailouts, standby, ready_start, ready_end, ready_up_timed_out, all_ready_sent, ready_message, ready_up_task
    phase = Phase.QUEUE
    queue = []
    # waiting_room is not reset
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
    
    # waiting_room_message is not reset


# converts a datetime to an integer number of seconds (offset)
def datetime_to_int(dt):
    return int(dt.timestamp())

# replaces the first instance on an item in the list with a different item
def replace_list_item(my_list, old_item, new_item):
    index = my_list.index(old_item)
    my_list[index] = new_item
    
# Get a user's preferred display name
def get_display_name(user):
    return user.nick or user.display_name or user.name
    
# Get a case insensitve key to sort users
def user_sort_key(user):
    return str.casefold(get_display_name(user))

# Get a key to sort users for re-queue
def re_queue_sort_key(user):
    if current_match:
        if re_queue_order == RequeueOrder.QUEUE_ORDER:
            if user in current_match.initial_players:
                return current_match.initial_players.index(user)
            return -1
        # get recent matches that the player was in
        min_end_time = current_match.setup_start_time - recent_time
        recent_matches = [m for n, m in matches if (m.end_time and m.end_time >= min_end_time and 
                                                    user in m.players)]
        match re_queue_order:
            case RequeueOrder.PLAY_TIME:
                return sum([m.matchup_length() for m in recent_matches])
            case RequeueOrder.NUM_GAMES:
                return sum([1 for m in recent_matches])
            case RequeueOrder.NUM_WOUNDS:
                return sum([6 - abs(m.wound_score) for m in recent_matches])
    return 0

# Function to make the queue embed
def queue_embed():
    if phase < Phase.PLAY:
        embed = discord.Embed(title='PUGs Queue', color=discord.Color.blue())
        if current_match:
            match_names = ', '.join([get_display_name(user) for user in current_match.players]) or 'No players in match.'
            embed.add_field(name=f'Setting Up Match #{match_number}', value=match_names, inline=False)
        else:
            queue_names = ', '.join([get_display_name(user) for user in queue]) or '*Empty*.'
            embed.add_field(name=f'In Queue ({len(queue)}/{queue_size_required})', value=queue_names, inline=False)
        
        if waiting_room:
            waiting_names = ', '.join([get_display_name(user) for user in waiting_room])
            embed.add_field(name=f'Waiting Room ({len(waiting_room)})', value=waiting_names, inline=False)
        if current_match and current_match.re_queue and phase > Phase.READY:
            re_queue_names = ', '.join([get_display_name(user) for user in current_match.re_queue])
            embed.add_field(name=f'Re-Queueing ({len(current_match.re_queue)})', value=re_queue_names, inline=False)
    elif current_match:
        match_names = ', '.join([get_display_name(user) for user in current_match.players]) or 'No players in match.'
        embed = discord.Embed(title=f'PUGs Match #{current_match.match_number}', description=match_names, color=discord.Color.blue())
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
    if current_match and user in current_match.re_queue:
        await interaction.response.send_message('You are already set to re-queue.', ephemeral=True, delete_after=msg_fade1)
        return
    if user in waiting_room:
        await interaction.response.send_message('You are already in the waiting room.', ephemeral=True, delete_after=msg_fade1)
        return
    elif user in queue:
        if phase > Phase.READY and current_match: # if past the ready phase, set player to re-queue
            current_match.re_queue.append(user)
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
    if current_match and user in current_match.re_queue:
        current_match.re_queue.remove(user)
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
    if current_match and phase >= Phase.PLAY:
        return len(waiting_room) + len(current_match.re_queue)
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
        await proceed_to_match_setup(channel)
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

# proceeds to match setup
async def proceed_to_match_setup(channel):
    global phase, current_match, queue_message, ready_message, ready_up_task
    phase = Phase.MAP
    # Cancel the ready-up task to prevent it from running after this point
    if not ready_up_timed_out and ready_up_task is not None:
        ready_up_task.cancel()
        ready_up_task = None

    ready_message = await remove_message(ready_message)
    queue_message = await remove_message(queue_message)
    # create match
    new_match = PugMatch(match_number, queue)
    matches[match_number] = new_match
    current_match = new_match
    # remove old matches
    if len(matches) > max_matches_in_memory:
        min_match_number = min(matches)
        del matches[min_match_number]
    # Send a completely new queue message instead of editing the old one
    embed = queue_embed()
    queue_message = await channel.send(embed=embed, view=QueueView())
    
    await new_match.proceed_to_map_voting(channel)

# Class for map voting
class MapVotingView(View):
    def __init__(self, match: PugMatch):
        super().__init__(timeout=None)
        self.match = match
        for game_map in map_choices:
            button = Button(label=str(game_map), style=discord.ButtonStyle.primary, custom_id=game_map.name)
            button.callback = self.make_callback(game_map)
            self.add_item(button)

    def make_callback(self, game_map):
        async def callback(interaction: discord.Interaction):
            await self.match.register_map_vote(interaction, game_map)
        return callback

# View for voting on matchups
class MatchupVotingView(View):
    def __init__(self, match: PugMatch):
        super().__init__(timeout=None)  # No timeout
        self.match = match

    @discord.ui.button(label='Matchup 1', style=discord.ButtonStyle.primary, custom_id='vote_1')
    async def vote_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.match.register_matchup_vote(interaction, 1)

    @discord.ui.button(label='Matchup 2', style=discord.ButtonStyle.primary, custom_id='vote_2')
    async def vote_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.match.register_matchup_vote(interaction, 2)

    @discord.ui.button(label='Matchup 3', style=discord.ButtonStyle.primary, custom_id='vote_3')
    async def vote_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.match.register_matchup_vote(interaction, 3)

    @discord.ui.button(label='Re-roll 🎲', style=discord.ButtonStyle.secondary, custom_id='vote_reroll')
    async def vote_reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.match.register_matchup_vote(interaction, reroll_key)
    
    @discord.ui.button(label='Custom', style=discord.ButtonStyle.secondary, custom_id='vote_custom')
    async def vote_custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.match.register_matchup_vote(interaction, custom_teams_key)




# View for reporting the final result of a match and resetting the queue
class FinalMatchupView(View):
    def __init__(self, match: PugMatch):
        super().__init__(timeout=None)
        self.match = match
 
    @discord.ui.button(label='Match Complete', style=discord.ButtonStyle.red)
    async def complete_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.match.register_reset_vote(interaction)

# Create a waiting room for players not in the Final Matchup
async def create_waiting_room(channel):
   global waiting_room_message
   embed = waiting_room_embed()
   if waiting_room_message:
       await waiting_room_message.edit(embed=embed)
   else:
       waiting_room_message = await channel.send(embed=embed, view=QueueView())

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
    if current_match and current_match.reset_queue_votes > 0:
        votes_str = f' ({current_match.reset_queue_votes}/{reset_queue_votes_required} votes)'
    embed = discord.Embed(
        title="PUGs Queue",
        description=f'Waiting for match to complete.{votes_str}',
        color=discord.Color.purple()
    )
    embed.add_field(name=f'Waiting Room ({len(waiting_room)})', value=waiting_room_names, inline=False)
    if current_match and current_match.re_queue:
        re_queue_names = ', '.join([get_display_name(user) for user in current_match.re_queue])
        embed.add_field(name=f'Re-Queueing ({len(current_match.re_queue)})', value=re_queue_names, inline=False)
    return embed


# restart queue after match is complete
async def restart_queue(channel):
    global phase, match_number, current_match
    phase = Phase.RESET
    results_match.phase = Phase.RESET
    results_match.update_end_time()
    await update_queue_message()  # final update of old queue message
    await results_match.update_final_matchup()  # final update of final matchup message
    # reset queue state
    reset_game()
    add_waiting_room_players_to_queue()  # Now add waiting room players to the empty queue
    match_number += 1  # increment match number
    current_match = None
    await start_new_queue(channel)  # Start a new queue with waiting room players


# Add waiting room players to the new queue
def add_waiting_room_players_to_queue():
    global queue, waiting_room
    if current_match: # Move all players from requeue into waiting room
        waiting_room.extend(current_match.re_queue)
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
    if phase >= Phase.PLAY: # if final matchup has been posted, save the next match number
        file.write(f'{match_number + 1}\n')
    else:
        file.write(f'{match_number}\n')
    if phase < Phase.PLAY and queue:
        file.write('\n'.join(str(user.id) for user in queue))
        file.write('\n')
    if waiting_room:
        file.write('\n'.join(str(user.id) for user in waiting_room))
        file.write('\n')
    if phase >= Phase.PLAY and current_match and current_match.re_queue:
        file.write('\n'.join(str(user.id) for user in current_match.re_queue))
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
    if current_match and current_match.final_team1_names:
        msg_lines.append(current_match.final_team1_names)
        msg_lines.append('')
    msg_lines.append(cmd2)
    if current_match and current_match.final_team2_names:
        msg_lines.append(current_match.final_team2_names)
    return '\n'.join(msg_lines)

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
async def end_pug_cmd(ctx):
   global phase, waiting_room, matches, current_match, results_match, game_in_progress, queue_message
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
       current_match = None
       results_match = None
       matches = {}
       await ctx.send('The current PUG session has been ended. You can start a new queue with `!start_pug`.')
   else:
       await ctx.send('No PUG session is currently active.')


# Command to start the PUG system
@bot.command(name='start_pug')
async def start_pug_cmd(ctx):
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
async def s7_cmd(ctx):
    await ctx.send(syco_commands_msg(7777))
    if current_match:
        current_match.update_start_time()
    
# Command to show the server join commands for syco.servegame.com port 7778
@bot.command(name='s8')
async def s8_cmd(ctx):
    await ctx.send(syco_commands_msg(7778))
    if current_match:
        current_match.update_start_time()
    
# Command to show the server join commands for syco.servegame.com port 7779
@bot.command(name='s9')
async def s9_cmd(ctx):
    await ctx.send(syco_commands_msg(7779))
    if current_match:
        current_match.update_start_time()
    
# Command to show the server join commands for syco.servegame.com port 7780
@bot.command(name='s0')
async def s0_cmd(ctx):
    await ctx.send(syco_commands_msg(7780))
    if current_match:
        current_match.update_start_time()

# Command to manually add users to the queue
@bot.command(name='queue_users')
async def queue_users_cmd(ctx, members: commands.Greedy[discord.Member]):
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
async def ct1_cmd(ctx, members: commands.Greedy[discord.Member]):
    if not current_match:
        await ctx.send('Cannot set custom teams until players are in a match.')
        return
    if current_match.phase > Phase.PLAY:
        await ctx.send('Cannot set custom teams once a match is complete.')
        return
    if current_match.phase == Phase.PLAY and current_match.selected_matchup != custom_teams_key:
        await ctx.send('Cannot set custom teams once a non-custom matchup has won the vote.')
        return
    players_in_match = [p for p in members if p in current_match.players]
    if len(players_in_match) != team_size:
        await ctx.send(f'Must set a custom team of {team_size} players in the current match.')
        return 
    current_match.custom_team1 = list(players_in_match)
    current_match.custom_team2 = list(set(current_match.players) - set(current_match.custom_team1))
    await current_match.on_custom_teams_changed(ctx.message.channel)
    custom_team1_names = ', '.join([get_display_name(user) for user in current_match.custom_team1])
    custom_team2_names = ', '.join([get_display_name(user) for user in current_match.custom_team2])
    await ctx.send(f'Custom Team 1 has been set to: {custom_team1_names}.\nCustom Team 2 has been set to: {custom_team2_names}.')

# Command to set custom team 2
@bot.command(name='ct2')
async def ct2_cmd(ctx, members: commands.Greedy[discord.Member]):
    if not current_match:
        await ctx.send('Cannot set custom teams until players are in a match.')
        return
    if current_match.phase > Phase.PLAY:
        await ctx.send('Cannot set custom teams once a match is complete.')
        return
    if current_match.phase == Phase.PLAY and current_match.selected_matchup != custom_teams_key:
        await ctx.send('Cannot set custom teams once a non-custom matchup has won the vote.')
        return
    players_in_match = [p for p in members if p in current_match.players]
    if len(players_in_match) != team_size:
        await ctx.send(f'Must set a custom team of {team_size} players in the current match.')
        return 
    current_match.custom_team2 = list(players_in_match)
    current_match.custom_team1 = list(set(current_match.players) - set(current_match.custom_team2))
    await current_match.on_custom_teams_changed(ctx.message.channel)
    custom_team1_names = ', '.join([get_display_name(user) for user in current_match.custom_team1])
    custom_team2_names = ', '.join([get_display_name(user) for user in current_match.custom_team2])
    await ctx.send(f'Custom Team 1 has been set to: {custom_team1_names}.\nCustom Team 2 has been set to: {custom_team2_names}.')

# Command to trade two players on opposite teams
@bot.command(name='trade')
async def trade_cmd(ctx, members: commands.Greedy[discord.Member]):
    if not current_match:
        await ctx.send('Cannot trade players until players are in a match.')
        return
    if current_match.phase <= Phase.MATCHUP:
        await ctx.send('Cannot trade players until a final matchup has been set.')
        return
    if current_match.phase > Phase.PLAY:
        await ctx.send('Cannot trade players once a match is complete.')
        return
    # find which players are on which team
    team1_players = [p for p in members if p in current_match.final_team1]
    team2_players = [p for p in members if p in current_match.final_team2]
    if len(team1_players) != 1 or len(team2_players) != 1:
        await ctx.send(f'Must trade two players on opposite teams.')
        return
    p1 = team1_players[0]
    p2 = team2_players[0]
    # perform trade
    replace_list_item(current_match.final_team1, p1, p2)
    replace_list_item(current_match.final_team2, p2, p1)
    await current_match.on_final_teams_changed(ctx.message.channel)
    await ctx.send(f'{get_display_name(p1)} and {get_display_name(p2)} have traded teams.')

# Command to replace a player in the match with one not in the match
@bot.command(name='fill')
async def fill_cmd(ctx, members: commands.Greedy[discord.Member]):
    if not current_match:
        await ctx.send('Cannot fill for a player until players are in a match.')
        return
    if current_match.phase > Phase.PLAY:
        await ctx.send('Cannot fill for a player once a match is complete.')
        return
    # find which players are in the match
    in_players = [p for p in members if p in current_match.players]
    out_players = [p for p in members if p not in current_match.players]
    if len(in_players) != 1 or len(out_players) != 1:
        await ctx.send(f'Must fill a player in the match with one not in the match.')
        return
    p_in = in_players[0]  # player in match
    p_out = out_players[0]  # player not in match
    await current_match.replace_player(p_in, p_out, ctx.message.channel)
    if p_in in queue:
        replace_list_item(queue, p_in, p_out)
    if p_out in waiting_room:
        waiting_room.remove(p_out)
    await ctx.send(f'{get_display_name(p_out)} is filling in for {get_display_name(p_in)}.')
    if phase >= Phase.PLAY:
        await update_waiting_room_message()
    else:
        await update_queue_message()

# Command to set scoreboard
@bot.command(name='sb')
async def sb_cmd(ctx, score_str: str = 'x'):
    if not results_match:
        await ctx.send('Cannot update scoreboard, no match is active.')
        return
    if not ctx.message.attachments:
        await ctx.send('No image attached, must attach an image of the scoreboard.')
        return
    if not ctx.message.attachments[0].content_type.startswith('image'):
        await ctx.send(f'Must attach an image, you attached a {ctx.message.attachments[0].content_type}.')
        return
    
    # convert attached image to a file to attach to our own message
    scoreboard_file = await ctx.message.attachments[0].to_file()
    await results_match.update_scoreboard(ctx, scoreboard_file)
    
    try:
        score = int(score_str)
    except ValueError:
        return
    await results_match.update_wounds(ctx, score)

# Alternate command for capital letters
@bot.command(name='SB')
async def sb_caps_cmd(ctx, score_str: str = 'x'):
    await sb_cmd(ctx, score_str)
    
# Command to set remaining wounds score
@bot.command(name='wounds')
async def wounds_cmd(ctx, score_str: str = 'x'):
    if not results_match:
        await ctx.send('Cannot update wounds, no match is active.')
        return
    try:
        score = int(score_str)
    except ValueError:
        await ctx.send(f'Unable to parse number of wounds from !wounds {score_str}.')
        return
    await results_match.update_wounds(ctx, score) 

# Run the bot
bot.run(TOKEN)