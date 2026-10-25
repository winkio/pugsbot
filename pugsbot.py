import os
import random
import re
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from enum import IntEnum
import ipaddress
import itertools
import json
import math
import socket
import tomllib
import traceback
from urllib.parse import urlsplit

import discord
from discord.ext import commands
from discord.ui import View, Button
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

# TODO
# v4
# DONE sort names ignoring case
# DONE remove bail out button
# DONE reroll should avoid giving previous matchups
# v5
# DONE fix double map vote
# DONE move matchup titles above each matchup
# DONE queue permanently joinable, automatic waiting room
# DONE automatically requeue players after a game ends unless they click a button
# v6
# DONE code cleanup
# DONE de-clutter messages
#   DONE make unimportant bot messages delete after a few seconds
#   DONE show reset votes on waiting room instead of in message
# DONE save/load waiting room and requeue
# DONE randomize order of players put into re-queue
# DONE re-add bailout button during ready phase with fill functionality
#   DONE waiting room players can ready up to be 'on standby', taking open spots without a requeue
# v7
# DONE custom teams button
# DONE command to set custom teams
# v8
# DONE sort custom teams alphabetically
# DONE recreate queue message after ready up phase completes
# DONE green checkmark on winning votes after votes complete
# DONE keep reference to final matchup message
# DONE Match number, increments with each match, saves and loads
# DONE rename !customt1 and 2 to !ct1 and 2
# DONE !ct1 sets team2 to leftover players
# DONE !sb command to update scoreboard
# DONE add mentions to final matchup for searchable match history
# DONE !mh command to get a search string for your discord user
# DONE !pughelp command to get a list of public commands
# DONE !wounds commands to report winner and wound score
# DONE timestamps and total match length on final match embed
# DONE config activity name, move config above bot init
# v9
# DONE match history button
# DONE help button
# DONE queue kill comments
# v10
# DONE fix bug with !ct1 command not actually setting team 2
# DONE add !SB command that does same as !sb
# DONE more accurate match time
# DONE rewrite match handling to be contained in a class that can be instanced per-match
# DONE store recent matches in memory
# DONE update match scoreboard and wounds after marked complete
# DONE requeue order sorted by recent play time, number of games, or number of wounds
# DONE !trade command to trade players between teams in final matchup
# DONE !fill command to replace a player in the match with one not in the match
# v11
# DONE prevent loading duplicate users into queue when starting pug
# DONE added custom server commands so that if servers change we don't need a new build
# DONE fixed requeue sort order
# DONE added logging levels
# DONE configure admin users and reserve certain commands for them
# DONE automatically save pug state when phase changes
# DONE shell scripts that can be ran by cron job to automatically check if bot is running and restart if needed
# DONE keep track of queue channel
# DONE automatically restart pugs on startup
# DONE added support for custom ports for custom servers
# v12
# DONE split saved files into config and players
# DONE set creature commands
# DONE set server commands (for server setup)
# automatically send request to server to start map
# update scoredboard image to reupload full file
# allow multiple matches
# votes for match balance when resetting queue

# Load the bot token from the .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class LogLevel(IntEnum):  # Log level order enum
    NONE = 1
    ERROR = 2
    WARNING = 3
    INFO = 4
    VERBOSE = 5
    ASYNC_CALLSTACK = 6

class GameMap():
    All = [] # List of GameMap objects describing each map (initialized below)
    def __init__(self, codename, name, emoji):
        self.codename = codename
        self.name = name
        self.emoji = emoji
        self.is_reef = 'canyon' in codename
    def __str__(self):
        return f'{self.name} {self.emoji}'
    # tries to get a map from the given string
    @staticmethod
    def from_string(name):
        for gamemap in GameMap.All:
            if gamemap.codename == name or gamemap.name == name or gamemap.emoji == name:
                return gamemap
        return None
GameMap.All = [
    GameMap('lv_canyon', 'Ghost Reef', '🏜️'), 
    GameMap('lv_valley', 'Sirens Strand', '🧊'), 
    GameMap('lv_mistforge', 'Sanctum Falls', '🌊'), 
    GameMap('lv_wizardwoods', 'Ember Grove', '🌲'), 
    GameMap('lv_skycityv2', 'Sky City', '☁️'),
    GameMap('lv_canyonnight', 'Night Reef', '🌙')
]

class GameCreature():
    All = [] # List of GameCreature objects describing each creature (initialized below)
    def __init__(self, codename, name, blocked_message = None):
        self.codename = codename
        self.name = name
        self.blocked_message = blocked_message  # if set, the creature cannot be selected and this is what to tell the user
    def __str__(self):
        return f'{self.name}'
    # tries to get a creature from the given string
    @staticmethod
    def from_string(name):
        for creature in GameCreature.All:
            if creature.codename == name or creature.name == name:
                return creature
        return None
GameCreature.All = [
    GameCreature('bloomer', 'Summer Bloomer'),
    GameCreature('bloomer_winter', 'Winter Bloomer'),
    GameCreature('bloomer_spring', 'Spring Bloomer', 'spring bloomers are bugged in core, please set a different creature'),
    GameCreature('bloomer_autumn', 'Autumn Bloomer'),
    GameCreature('cerb', 'Cerberus Majoris'),
    GameCreature('cerb_shadow', 'Shadow Cerberus'),
    GameCreature('cerb_stone', 'Stone Cerberus'),
    GameCreature('cyclops', 'Mountain Cyclops'),
    GameCreature('cyclops_yeti', 'Yeti Cyclops'),
    GameCreature('cyclops_riftborn', 'Riftborn Cyclops'),
    GameCreature('dragon', 'Fire Drake'),
    GameCreature('dragon_storm', 'Storm Drake'),
    GameCreature('infernal', 'Crimson Infernal'),
    GameCreature('infernal_void', 'Void Infernal'),
    GameCreature('infernal_savage', 'Savage Infernal'),
    GameCreature('obelisk', 'Ancient Obelisk')
]

class RequeueOrder(IntEnum):  # Re-queue order enum
    QUEUE_ORDER = 1
    RANDOM = 2
    PLAY_TIME = 3
    NUM_GAMES = 4
    NUM_WOUNDS = 5

# Settings that differ between bots are read from config.toml, which is next to this file
# a setting that is not in the file uses the default given where it is read below
config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.toml')
config_keys_read = set() # the settings that have been read, used to warn about unknown ones

# prints a warning line in the log format
def print_config_warning(message):
    print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} - WARNING: {message}')

# prints an error line in the log format and stops the bot because its settings are not usable
def stop_for_config_error(message):
    print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} - ERROR: {message}')
    raise SystemExit(1)

# loads the settings from config.toml
def load_config():
    try:
        with open(config_file_path, 'rb') as file:
            return tomllib.load(file)
    except FileNotFoundError:
        stop_for_config_error(f'Config file not found: {config_file_path}')
    except tomllib.TOMLDecodeError as e:
        stop_for_config_error(f'Config file {config_file_path} is not valid TOML: {e}')

# gets a setting from the config, which must be the same type as its default
# whole number settings must also be at least 1
def config_value(key, default):
    config_keys_read.add(key)
    value = config.get(key, default)
    if type(value) is not type(default):
        stop_for_config_error(f'Config setting {key} must be a {type(default).__name__}, not {value!r}')
    if type(value) is int and value < 1:
        stop_for_config_error(f'Config setting {key} must be at least 1, not {value}')
    return value

# gets a list setting from the config, where every item must be the given type
def config_list(key, default, item_type, min_items = 0):
    config_keys_read.add(key)
    value = config.get(key, default)
    if type(value) is not list:
        stop_for_config_error(f'Config setting {key} must be a list, not {value!r}')
    for item in value:
        if type(item) is not item_type:
            stop_for_config_error(f'Config setting {key} must only contain {item_type.__name__} values, not {item!r}')
    if len(value) < min_items:
        stop_for_config_error(f'Config setting {key} must have at least {min_items} item(s)')
    return list(value)

# gets a setting that is the name of one of the members of an enum
def config_enum(key, enum_class, default_name):
    name = config_value(key, default_name)
    try:
        return enum_class[name.upper()]
    except KeyError:
        stop_for_config_error(f'Config setting {key} must be one of {", ".join(enum_class.__members__)}, not {name!r}')

# gets a setting that is the code name of a creature, see GameCreature.All
def config_creature(key, default_code_name):
    creature = GameCreature.from_string(config_value(key, default_code_name))
    if not creature:
        stop_for_config_error(f'Config setting {key} is not the code name of a creature')
    if creature.blocked_message:
        stop_for_config_error(f'Config setting {key} cannot be {creature.name}: {creature.blocked_message}')
    return creature

config = load_config()
# Constants for settings
has_initialized_after_first_login = False
queue_channel_id = 0
log_level = config_enum('log_level', LogLevel, 'VERBOSE')  # how much is written to the log, one of the LogLevel names
activity_name = config_value('activity_name', '')  # the bot shows as playing this, nothing is shown if it is empty
bot_activity = discord.Activity(type=discord.ActivityType.playing, name=activity_name) if activity_name else None
ready_up_time = config_value('ready_up_time', 90)  # seconds to ready up
queue_size_required = config_value('queue_size_required', 10)  # number of players required for a match
team_size = config_value('team_size', queue_size_required // 2)  # number of players on each team
reset_queue_votes_required = config_value('reset_queue_votes_required', 4)  # votes required to reset the queue
votes_required = config_value('votes_required', 5)  # votes required to pick maps, matchups, or re-roll
map_total_votes_required = config_value('map_total_votes_required', 7)  # total votes required to choose a map
save_file_path = config_value('save_file_path', 'stored_pug.json')  # Stores saved PUG state data
save_players_file_path = config_value('save_players_file_path', 'stored_pug_players.json')  # Stores saved PUG player data
user_settings_file_path = config_value('user_settings_file_path', 'stored_pug_user_settings.json')  # Stores the settings users have changed for themselves
legacy_save_file_path = 'stored_pug.txt'  # Older text format of the saved state, only read if there is no json file
legacy_save_players_file_path = 'stored_pug_players.txt'  # Older text format of the saved players, only read if there is no json file
# settings that each user can change for themselves with commands, with their default values
user_setting_defaults = {
    'dms': True,  # the bot sends this user direct messages at all, changed with !pugdms
    'dms_vote': False,  # the bot sends this user a direct message when the map vote starts, changed with !pugdms_vote
    'dms_join': False  # the bot sends this user a direct message when the final matchup is posted, changed with !pugdms_join
}
user_settings = {}  # user id -> {setting name: value} with only the settings that user has changed, saved in user_settings_file_path
msg_fade1 = config_value('msg_fade1', 8)  # very simple ephemeral messages auto-delete after this many seconds
msg_fade2 = config_value('msg_fade2', 30)  # simple ephemeral messages auto-delete after this many seconds
help_url = config_value('help_url', 'https://csharpgamedev.com/bots/help/')  # web page that lists the commands
ready_alarm_image_url = config_value('ready_alarm_image_url', 'https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExYzZiN3dyOGZkYjA3Z2sxM3FsNjBpOGJuaGdjN2x6NDNhNDk3Yng2aCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/KxBFk4ksGxJ2W8N6jg/giphy.gif')  # image for !readyalarm
re_queue_order = config_enum('re_queue_order', RequeueOrder, 'NUM_WOUNDS')  # order to use when re-queueing players in a match, one of the RequeueOrder names
recent_time = timedelta(hours=config_value('recent_time_hours', 3))  # if ordering by playtime or wounds, only look at games in this many hours
max_matches_in_memory = config_value('max_matches_in_memory', 10)  # Only hold onto this many matches in memory
vote_pip = config_value('vote_pip', '\u25c9 ')  # pip to use when displaying votes
vote_win_pip = config_value('vote_win_pip', '\u2705 ')  # pip to use when displaying votes for the winning option
server_setup_address = 'not set'  # web address of server setup page, changed with !setup and saved
server_request_timeout = config_value('server_request_timeout', 30)  # seconds to wait for each web request to the server setup page
# the max players and creatures below are changed with commands and saved, and a saved value is used instead of these
default_max_players = config_value('default_max_players', 20)  # max players on game server
default_creature1 = config_creature('default_creature1', 'bloomer_winter')
default_creature2 = config_creature('default_creature2', 'cerb_shadow')
default_creature3 = config_creature('default_creature3', 'dragon_storm')
default_creature3r = config_creature('default_creature3r', 'bloomer_autumn')
ready_dm_messages = config_list('ready_dm_messages', [  # List of random messages to send when ready up begins, a link to the ready-up message follows each one
    "The queue is full. Go Ready Up!",
    "It's time for server set-up simulator, go ready up!",
    "Go ready up for PUGs or have another 30 minutes of queue time!",
    "The PUGs queue is full. Go to the server and Ready Up!",
    "It's time for Giggin, go ready up!"
], str, min_items=1)
map_vote_dm_message = config_value('map_vote_dm_message', 'The map vote has started. Go vote!')  # message to send to players who asked for it with !pugdms_vote, a link to the vote follows it
join_dm_message = config_value('join_dm_message', 'The final matchup is set. Go join the game!')  # message to send to players who asked for it with !pugdms_join, a link to the final matchup follows it
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
admin_ids = config_list('admin_ids', [], int)  # ids of admin users, nobody is an admin unless the config lists them
# warn about anything in the config file that is not a setting, which is likely a typo
for config_key in config:
    if config_key not in config_keys_read:
        print_config_warning(f'Unknown setting in {config_file_path}: {config_key}')
if team_size * 2 != queue_size_required:
    print_config_warning(f'team_size ({team_size}) is not half of queue_size_required ({queue_size_required})')
# Constants used elsewhere in code
divider = '——————————————————————————'  # divider string for votes
reroll_key = 'reroll'  # key for reroll votes in votes dict
custom_teams_key = 'custom'  # key for custom votes in votes dict
open_server_prefix_str = ': open '  # substring before game server address in server webform
# what a game server address from the server webform must look like: host or host:port
server_address_pattern = re.compile(r'(?:[A-Za-z0-9._-]+|\[[0-9A-Fa-f:.]+\])(?::[0-9]{1,5})?')
# The help text for each command is in command_help.json, which the web help pages are written from

# Set up the bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # To access member information

bot = commands.Bot(command_prefix='!', intents=intents, case_insensitive=True) # !SB, !Sb and !sb all run the same command

# gets a timestamp to use when logging
def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# gets a prefix for the given log level
def get_log_level_prefix(level: LogLevel):
    match level:
        case LogLevel.ERROR:
            return 'ERROR: '
        case LogLevel.WARNING:
            return 'WARNING: '
    return ''

# logs a message
def log_msg(level: LogLevel, msg: str):
    if level <= log_level:
        print(f'{get_timestamp()} - {get_log_level_prefix(level)}{msg}')

# logs the start of an async call
def log_async_start(name):
    log_msg(LogLevel.ASYNC_CALLSTACK, f'▼ async {name}() ▼')

# logs the end of an async call
def log_async_end(name):
    log_msg(LogLevel.ASYNC_CALLSTACK, f'▲ async {name}() ▲')

# checks that a server setup address is a public http(s) address
# returns None if the address is allowed, or a short reason if it is rejected
# this looks up the host name, so it is blocking: call it with asyncio.to_thread
def check_server_address(address):
    try:
        parts = urlsplit(address)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == 'https' else 80)
    except ValueError:
        return 'not a valid web address'
    if parts.scheme not in ('http', 'https'):
        return 'the address must start with http:// or https://'
    if not host:
        return 'the address has no host name'
    if parts.username is not None or parts.password is not None:
        return 'the address must not contain a user name or password'
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return f'could not look up {host}'
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split('%')[0]) # drop any IPv6 zone id
        ip = getattr(ip, 'ipv4_mapped', None) or ip # treat ::ffff:a.b.c.d as a.b.c.d
        if not ip.is_global:
            return f'{host} is an internal address'
    return None

# a web session that checks every address it connects to, including redirects
class SafeSession(requests.Session):
    def send(self, request, **kwargs):
        reason = check_server_address(request.url)
        if reason:
            raise ValueError(f'blocked web request to {request.url}: {reason}')
        return super().send(request, **kwargs)

# form fields (besides the token) that the server setup page must have
server_form_fields = ['map', 'maxPlayers', 'creature0', 'creature1', 'creature2']

# checks that a form has all of the fields we post
# if a field is a list of choices, the value we post must be one of the choices
# returns None if the form looks right, or a short reason if it does not
def check_form_fields(form, post_data):
    for name in server_form_fields:
        fields = form.find_all(attrs={'name': name})
        if not fields:
            return f'the form has no {name} field'
        choices = []
        for field in fields:
            if field.name == 'select':
                choices.extend(option.get('value', option.get_text(strip=True)) for option in field.find_all('option'))
            elif field.name == 'input' and field.get('type') in ('radio', 'checkbox'):
                choices.append(field.get('value', 'on'))
        if choices and post_data[name] not in choices:
            return f'the {name} field does not offer {post_data[name]}'
    return None

# looks through the forms on the setup page for one with the token and the fields we post
# returns (token, None) if one is found, or (None, reason) if the page is not what we expect
def find_server_form(soup, post_data):
    reason = 'the page has no form with a __RequestVerificationToken field'
    for form in soup.find_all('form'):
        token_input = form.find('input', {'name': '__RequestVerificationToken'})
        if not token_input:
            continue
        reason = check_form_fields(form, post_data)
        if reason is None:
            return token_input.get('value'), None
    return None, reason

# asks the game server setup page to start a server for a match
# returns the server address and port, or None if the server could not be started
# this uses blocking web requests, so it must be called with asyncio.to_thread
def request_server_start(setup_address, map_codename, max_players, creature1, creature2, creature3):
    session = SafeSession() # start a session to manage cookies, only connects to public addresses
    session.max_redirects = 3
    log_msg(LogLevel.INFO, f'Connecting to server setup page: {setup_address}')
    try:
        # GET the form page
        response = session.get(setup_address, timeout=server_request_timeout)
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        log_msg(LogLevel.ERROR, f'Unable to get server setup page from {setup_address}: {e}')
        traceback.print_exc()
        return None

    # Step 2: Check that the page has the form we expect, only post if it does
    post_data = {
        'map': map_codename,
        'maxPlayers': str(max_players),
        'creature0': creature1,
        'creature1': creature2,
        'creature2': creature3
    }
    log_msg(LogLevel.INFO, f'Checking server setup form')
    token, problem = find_server_form(soup, post_data)
    if problem:
        log_msg(LogLevel.ERROR, f'Server setup page does not have the expected form: {problem}')
        return None

    # Step 3: Check the CSRF token
    if not token:
        log_msg(LogLevel.ERROR, f'No token found from server setup page')
        return None
    post_data['__RequestVerificationToken'] = token

    # Step 4: Send the POST request
    post_url = f'{setup_address}?handler=view'
    log_msg(LogLevel.INFO, f'Posting response to: {post_url}')
    try:
        post_response = session.post(post_url, data=post_data, timeout=server_request_timeout)
    except Exception as e:
        log_msg(LogLevel.ERROR, f'Unable to post to server setup page {post_url}: {e}')
        traceback.print_exc()
        return None

    # Parse the HTML
    log_msg(LogLevel.INFO, f'Parsing POST result')
    soup_response = BeautifulSoup(post_response.text, 'html.parser')

    # Find the success message with server join command
    green_span = soup_response.find('span', class_='green')
    if not green_span: # if no success message found
        log_msg(LogLevel.ERROR, f'Server failed to start')
        return None

    # Get the text content
    log_msg(LogLevel.INFO, f'Server has been started')
    open_index = green_span.text.find(open_server_prefix_str)
    if open_index == -1: # if no server join command found
        log_msg(LogLevel.ERROR, f'Unable to parse server connection string')
        return None

    # get the game server address, which is the first word after the prefix
    # it is shown in discord messages, so it must look like host or host:port
    words = green_span.text[open_index + len(open_server_prefix_str):].split()
    address_and_port = words[0] if words else ''
    if not server_address_pattern.fullmatch(address_and_port):
        log_msg(LogLevel.ERROR, f'Unable to parse server connection string: {address_and_port[:60]!r}')
        return None
    log_msg(LogLevel.INFO, f'server address has been parsed: {address_and_port}')
    return address_and_port

@bot.event
async def on_ready():
    log_async_start('on_ready')
    global has_initialized_after_first_login
    if bot_activity:
        await bot.change_presence(status=discord.Status.online, activity=bot_activity)
    else:
        await bot.change_presence(status=discord.Status.online)
    log_msg(LogLevel.NONE, f'Logged in as {bot.user.name} ({bot.user})')
    if not has_initialized_after_first_login:
        has_initialized_after_first_login = True
        await init_on_first_login()
    log_async_end('on_ready')

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
        
        self.server_max_players = default_max_players
        self.selected_creature1 = default_creature1
        self.selected_creature2 = default_creature2
        self.selected_creature3 = default_creature3
        self.server_address_and_port = None

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
        self.re_queue = list(self.players)  # Players re-queueing after current match
        random.shuffle(self.re_queue)  # Randomize re-queue order
        if re_queue_order != RequeueOrder.RANDOM:  # sort re-queue order
            self.re_queue.sort(key=re_queue_sort_key)
            for user in self.re_queue:
                log_msg(LogLevel.VERBOSE, f'sort key: {user} => {re_queue_sort_key(user)}')
    
    # Proceed to map voting
    async def proceed_to_map_voting(self, channel):
        log_async_start('proceed_to_map_voting')
        embed = self.map_voting_embed()
        # Send the message with the MapVotingView
        self.map_voting_message = await channel.send(embed=embed, view=MapVotingView(self))
        # Send a DM to each player in the match who asked for one when the map vote starts
        for user in self.players:
            if get_user_setting(user, 'dms_vote'):
                await send_dm(user, f'{map_vote_dm_message} {self.map_voting_message.jump_url}')
        log_async_end('proceed_to_map_voting')

    # Gets the vote pip string for a given map
    def map_vote_pips(self, game_map: GameMap):
        if game_map == self.selected_map:
            return f'\u200b{vote_win_pip * self.map_votes[game_map]}'
        return f'\u200b{vote_pip * self.map_votes[game_map]}'

    # Makes the map voting embed
    def map_voting_embed(self):
        embed = discord.Embed(title='Map Vote', color=discord.Color.green())
        for game_map in GameMap.All:
            embed.add_field(name=str(game_map), value=self.map_vote_pips(game_map), inline=True)
        # add extra empty fields so that there are 3 fields per row
        for _ in range(-len(GameMap.All) % 3):
            embed.add_field(name='\u200b', value='\u200b', inline=True)
        return embed
                
    # Update the map voting message
    async def update_map_voting_message(self):
        log_async_start('update_map_voting_message')
        if self.map_voting_message:
            embed = self.map_voting_embed()
            if self.phase != Phase.MAP:
                await self.map_voting_message.edit(embed=embed, view=None)  # remove buttons if not voting
            else:
                await self.map_voting_message.edit(embed=embed)
        log_async_end('update_map_voting_message')
    
    # handles a user voting for a map
    async def register_map_vote(self, interaction, game_map):
        log_async_start('register_map_vote')
        # do nothing if no longer in map voting phase
        if self.phase != Phase.MAP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('register_map_vote')
            return
        
        user = interaction.user
        if user not in self.players:
            await interaction.response.send_message('You are not part of the match.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('register_map_vote')
            return

        # Allow user to change their vote
        if user in self.map_voted_users:
            map_previous_vote = self.map_voted_users[user]
            if map_previous_vote == game_map:
                await interaction.response.send_message(f'You have already voted for {game_map}.', ephemeral=True, delete_after=msg_fade1)
                log_async_end('register_map_vote')
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
        log_async_end('register_map_vote')

    # Function to declare the selected map and proceed to matchups
    async def declare_selected_map(self, channel):
        log_async_start('declare_selected_map')
        if self.selected_map.is_reef:
            self.selected_creature3 = default_creature3r
        await self.proceed_to_matchups_phase(channel)
        await self.update_map_voting_message()  # final update of map vote message
        log_async_end('declare_selected_map')

    # Adjusted function to proceed to matchups
    async def proceed_to_matchups_phase(self, channel):
        log_async_start('proceed_to_matchups_phase')
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
        log_async_end('proceed_to_matchups_phase')
    
    # gets the vote pip string for a given matchup
    def matchup_vote_pips(self, m):
        if m == self.selected_matchup:
            return f' {vote_win_pip * self.votes[m]}'
        return f' {vote_pip * self.votes[m]}'

    # Function to display the voting embed with votes count and enhanced readability
    async def display_matchup_votes(self, channel):
        log_async_start('display_matchup_votes')
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
            custom_teams_text = f'**Custom**{self.matchup_vote_pips(custom_teams_key)}\nUse !ct1 or !ct2 to set custom teams.'
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
        log_async_end('display_matchup_votes')
    
    # Gets a string representation of the matchup    
    def get_matchup_str(self, m):
        if m == reroll_key:
            return 'Re-roll Matchups'
        if m == custom_teams_key:
            return 'Custom matchup'
        return f'Matchup {m}'
    
    # handles registering a matchup vote
    async def register_matchup_vote(self, interaction, m):
        log_async_start('register_matchup_vote')
        # do nothing if no longer in team voting phase
        if self.phase != Phase.MATCHUP:
            await interaction.response.send_message('This button is no longer active.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('register_matchup_vote')
            return
        
        user = interaction.user
        if user not in self.players:
            await interaction.response.send_message('You are not part of the match.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('register_matchup_vote')
            return
        if user in self.voted_users:  # if already voted
            previous_vote = self.voted_users[user]
            if previous_vote == m:  # check if same vote
                await interaction.response.send_message(f'You have already voted for {self.get_matchup_str(m)}.', ephemeral=True, delete_after=msg_fade1)
                log_async_end('register_matchup_vote')
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
                log_async_end('register_matchup_vote')
                return
            elif m == custom_teams_key and not self.final_matchup_sent:
                self.final_matchup_sent = True  # Ensure this block runs only once
                await self.declare_matchup(interaction.message.channel, -1)
            elif not self.final_matchup_sent:
                self.final_matchup_sent = True  # Ensure this block runs only once
                await self.declare_matchup(interaction.message.channel, m)

        # Update the voting message
        await self.display_matchup_votes(interaction.message.channel)
        log_async_end('register_matchup_vote')
    
    # Declare the chosen matchup
    async def declare_matchup(self, channel, matchup_number):
        log_async_start('declare_matchup')
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

        await self.start_server()

        embed = self.final_matchup_embed()
        self.final_matchup_message = await channel.send(embed=embed, view=FinalMatchupView(self))

        # Create the new waiting room after final matchup
        await create_waiting_room(channel)
        await update_queue_message() # single update of queue message for new phase

        # Send a DM to each player in the match who asked for one when the final matchup is posted
        for user in self.players:
            if get_user_setting(user, 'dms_join'):
                await send_dm(user, f'{join_dm_message} {self.final_matchup_message.jump_url}')
        log_async_end('declare_matchup')

    # Starts the game server using the server setup page
    # the web requests are blocking, so they run in a worker thread to keep the bot responsive
    async def start_server(self):
        # the address is 'not set' until !setup is used, so anything that is not a web address means no server
        if not server_setup_address.lower().startswith(('http://', 'https://')):
            log_msg(LogLevel.INFO, f'No server setup page has been set, so no server will be started')
            return

        try:
            address_and_port = await asyncio.to_thread(
                request_server_start,
                server_setup_address,
                self.selected_map.codename,
                self.server_max_players,
                self.selected_creature1.codename,
                self.selected_creature2.codename,
                self.selected_creature3.codename)
        except Exception as e:
            log_msg(LogLevel.ERROR, f'Unexpected error while starting the server: {e}')
            traceback.print_exc()
            return

        if address_and_port: # set game server address
            self.server_address_and_port = address_and_port
    
    # Updates the final matchup message
    async def update_final_matchup(self):
        log_async_start('update_final_matchup')
        embed = self.final_matchup_embed()
        if self.final_matchup_message:
            if self.phase != Phase.PLAY:
                all_mentions = ' '.join([user.mention for user in self.players])
                content = f'-# pug_mh {self.match_number} {self.selected_map.name.casefold()} {all_mentions}'
                await self.final_matchup_message.edit(content=content, embed=embed, view=None)
            else:
                await self.final_matchup_message.edit(embed=embed)
        log_async_end('update_final_matchup')

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
        team1_text = self.final_team1_names
        team2_text = self.final_team2_names
        # if server has been set and game is not complete, show the server join commands
        if self.server_address_and_port and (self.phase <= Phase.PLAY):
            team1_text = f'`open {self.server_address_and_port}?team=0`\n{team1_text}'
            team2_text = f'`open {self.server_address_and_port}?team=1`\n{team2_text}'
        
        embed.add_field(name=f'Team 1 {self.score_display(1)}', value=team1_text, inline=False)
        embed.add_field(name=f'Team 2 {self.score_display(2)}', value=team2_text, inline=False)
        if self.wound_score == 0 and self.phase <= Phase.PLAY:
            embed.add_field(name='Remaining Wounds', value='Report result with !wounds x.  + for Team1, - for Team2', inline=False)
        if self.scoreboard_filename:
            embed.set_image(url=f'attachment://{self.scoreboard_filename}')
        elif self.phase <= Phase.PLAY:
            embed.add_field(name='Scoreboard', value='Use the !sb command with an attached image.', inline=False)
        if self.phase <= Phase.PLAY:
            embed.set_footer(text='Good luck and have fun!')
        return embed
    
    # Handles a match complete vote
    async def register_reset_vote(self, interaction):
        log_async_start('register_reset_vote')
        user = interaction.user
        if user in self.reset_voted_users:
            await interaction.response.send_message('You have already marked the match as complete.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('register_reset_vote')
            return
        if user not in self.players:
            await interaction.response.send_message('You are not in the current match and cannot mark the match as complete.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('register_reset_vote')
            return
        if self.reset_in_progress:  # Prevent triggering multiple resets
            await interaction.response.send_message('Queue reset is already in progress.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('register_reset_vote')
            return
           
        self.reset_queue_votes += 1
        self.reset_voted_users.add(user)
        await interaction.response.send_message(
            f'{get_display_name(user)} marked the match as complete ({self.reset_queue_votes}/{reset_queue_votes_required} votes).',
            ephemeral=True, delete_after=msg_fade2)
       
        await update_waiting_room_message()  # update reset vote display
        # Check if the required number of votes have been reached
        if self.reset_queue_votes >= reset_queue_votes_required and not self.reset_in_progress:
            self.reset_in_progress = True  # Prevent multiple resets
            await interaction.message.channel.send(f'Match #{self.match_number} marked as complete by vote.  Resetting queue...')
            await restart_queue(interaction.message.channel)  # Reset the queue and send a new queue message
        log_async_end('register_reset_vote')

    # replaces a player in the match
    async def replace_player(self, p_out, p_in, channel):
        log_async_start('replace_player')
        if p_out in self.players:
            replace_list_item(self.players, p_out, p_in)
        if p_out in self.re_queue:
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
        log_async_end('replace_player')

    # trades two players on opposite teams of one of the matchups being voted on
    # votes already cast stay as they are
    async def trade_in_matchup(self, matchup_number, p1, p2, channel):
        log_async_start('trade_in_matchup')
        team1, team2 = self.matchups[matchup_number - 1]
        replace_list_item(team1, p1, p2)
        replace_list_item(team2, p2, p1)
        team1.sort(key=user_sort_key)
        team2.sort(key=user_sort_key)
        await self.display_matchup_votes(channel)  # update embed
        log_async_end('trade_in_matchup')

    # updates UI when custom teams are changed
    async def on_custom_teams_changed(self, channel):
        log_async_start('on_custom_teams_changed')
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
        log_async_end('on_custom_teams_changed')
    
    # updates UI when final teams are changed by a trade or fill
    async def on_final_teams_changed(self, channel):
        log_async_start('on_final_teams_changed')
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
        log_async_end('on_final_teams_changed')
    
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
        log_async_start('update_scoreboard')
        self.scoreboard_filename = scoreboard_img.filename
        await self.final_matchup_message.edit(attachments=[scoreboard_img])
        await self.update_final_matchup()
        await ctx.send(f'Updated scoreboard for Match #{self.match_number}.')
        self.update_end_time()  # update match end time
        log_async_end('update_scoreboard')
    
    # updates the number of remaining wounds for the match
    async def update_wounds(self, ctx, score):
        log_async_start('update_wounds')
        new_score = max(-3, min(3, score))
        if self.wound_score == new_score:
            await ctx.send(f'The remaining wounds of Match #{self.match_number} have already been set to {new_score}.')
            log_async_end('update_wounds')
            return
        self.wound_score = new_score
        await self.update_final_matchup()
        if self.wound_score == 0:
            await ctx.send(f'The winner and remaining wounds of Match #{self.match_number} have been cleared.')
        else:
            win_team = (-self.wound_score // abs(self.wound_score) + 1) // 2 + 1
            await ctx.send(f'Team {win_team} is the winner of Match #{self.match_number} with {abs(self.wound_score)} wounds remaining.')
        log_async_end('update_wounds')
    
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
        recent_matches = [m for n, m in matches.items() if (m.end_time and m.end_time >= min_end_time and 
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
            queue_names = ', '.join([get_display_name(user) for user in queue]) or '*Empty*'
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
        log_async_start('join_queue')
        await handle_queue_join(interaction)
        log_async_end('join_queue')

    @discord.ui.button(label='Leave Queue', style=discord.ButtonStyle.red)
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('leave_queue')
        await handle_queue_leave(interaction)
        log_async_end('leave_queue')
    
    @discord.ui.button(label='Match History', style=discord.ButtonStyle.grey)
    async def match_history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('match_history_button')
        await reply_with_match_history(interaction)
        log_async_end('match_history_button')
    
    @discord.ui.button(label='Help', style=discord.ButtonStyle.grey)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('help_button')
        await reply_with_help(interaction)
        log_async_end('help_button')

# Function to handle when a user clicks a join button for queue or waiting room
async def handle_queue_join(interaction: discord.Interaction):
    log_async_start('handle_queue_join')
    user = interaction.user
    if current_match and user in current_match.re_queue:
        await interaction.response.send_message('You are already set to re-queue.', ephemeral=True, delete_after=msg_fade1)
        log_async_end('handle_queue_join')
        return
    if user in waiting_room:
        await interaction.response.send_message('You are already in the waiting room.', ephemeral=True, delete_after=msg_fade1)
        log_async_end('handle_queue_join')
        return
    elif user in queue:
        if phase > Phase.READY and current_match: # if past the ready phase, set player to re-queue
            current_match.re_queue.append(user)
            await interaction.response.send_message(f'{get_display_name(user)} is set to re-queue!', ephemeral=True, delete_after=msg_fade2)
        else:
            await interaction.response.send_message('You are already in the queue.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('handle_queue_join')
            return
    else:  # user not in queue or waiting room yet
        if len(queue) < queue_size_required:  # if room in the queue add the user
            queue.append(user)
            await interaction.response.send_message(f'{get_display_name(user)} joined the queue!', ephemeral=True, delete_after=msg_fade2)
        else:  # otherwise add to waiting room
            waiting_room.append(user)
            await interaction.response.send_message(f'{get_display_name(user)} joined the waiting room!', ephemeral=True, delete_after=msg_fade2)
    
    if phase == Phase.PLAY:
        await update_waiting_room_message()
    else:
        await update_queue_message()
    try_save_pug(save_state=False) # save players automatically
    log_async_end('handle_queue_join')
    
# Function to handle when a user clicks a leave button for queue or waiting room
async def handle_queue_leave(interaction: discord.Interaction):
    log_async_start('handle_queue_leave')
    user = interaction.user
    if current_match and user in current_match.re_queue:
        current_match.re_queue.remove(user)
        await interaction.response.send_message(f'{get_display_name(user)} will not re-queue!', ephemeral=True, delete_after=msg_fade2)
    elif user in waiting_room:
        if phase == Phase.READY and user in standby:
            await interaction.response.send_message('You cannot leave the queue while on Standby.', ephemeral=True, delete_after=msg_fade1)
            log_async_end('handle_queue_leave')
            return
        waiting_room.remove(user)
        await interaction.response.send_message(f'{get_display_name(user)} left the waiting room!', ephemeral=True, delete_after=msg_fade2)
    elif user in queue:
        if phase > Phase.READY: # if past the ready phase, player is already set to NOT re-queues:
            await interaction.response.send_message('You already will not re-queue.', ephemeral=True, delete_after=msg_fade1)
            return
        if phase == Phase.READY:
            await interaction.response.send_message('You cannot leave the queue during Ready Up.', ephemeral=True, delete_after=msg_fade1)
            return
        queue.remove(user)
        await interaction.response.send_message(f'{get_display_name(user)} left the queue.', ephemeral=True, delete_after=msg_fade2)
    else:
        await interaction.response.send_message('You are not in the queue.', ephemeral=True, delete_after=msg_fade1)
        log_async_end('handle_queue_leave')
        return
    
    if phase >= Phase.PLAY:
        await update_waiting_room_message()
    else:
        await update_queue_message()
    try_save_pug(save_state=False) # save players automatically
    log_async_end('handle_queue_leave')

# Replies to a user with a match history message
async def reply_with_match_history(interaction: discord.Interaction):
    log_async_start('reply_with_match_history')
    msg = match_history_block(interaction.user)
    await interaction.response.send_message(msg, ephemeral=True, delete_after=msg_fade2)
    log_async_end('reply_with_match_history')
   
# Replies to a user with a link to the help page
# the link is wrapped in <> so that discord does not add a link preview
async def reply_with_help(interaction: discord.Interaction):
    log_async_start('reply_with_help')
    msg = f'Commands and help for this bot: <{help_url}>'
    await interaction.response.send_message(msg, ephemeral=True)
    log_async_end('reply_with_help')

# Function to get the total number of players in queue + waiting room
def total_queue_size():
    if current_match and phase >= Phase.PLAY:
        return len(waiting_room) + len(current_match.re_queue)
    return len(queue) + len(waiting_room)

# Function to update the queue message (editing the original message)
async def update_queue_message():
    log_async_start('update_queue_message')
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
    log_async_end('update_queue_message')

# Function that checks if we have the required number of players, and if so moves to ready check
async def check_full_queue():
    log_async_start('check_full_queue')
    global game_in_progress
    if len(queue) == queue_size_required and not game_in_progress:
        game_in_progress = True
        await start_ready_check(queue_message.channel)
    log_async_end('check_full_queue')

# Sends a direct message to a user, unless they turned the bot's direct messages off with !pugdms
# every direct message the bot sends goes through here
async def send_dm(user, message):
    if not get_user_setting(user, 'dms'):
        log_msg(LogLevel.VERBOSE, f'Not sending a DM to {user} because they turned DMs off.')
        return
    try:
        await user.send(message)
    except discord.Forbidden:
        log_msg(LogLevel.WARNING, f'Could not DM {user} due to privacy settings.')
    except discord.HTTPException as e:  # a DM that fails must not stop the match from going on
        log_msg(LogLevel.WARNING, f'Could not DM {user}: {e}')

# Function to start the ready check
async def start_ready_check(channel):
    log_async_start('start_ready_check')
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

    # Send a DM to each player in the queue with a random message and a link to the ready-up message
    # this is last so that the DMs do not delay the ready-up, and it uses copies since the ready-up can end while they are sent
    # players who have already clicked ready or bail out do not need a DM, and none are sent once the ready-up is over
    ready_up_url = ready_message.jump_url
    for user in list(queue_sorted):
        if phase != Phase.READY:
            break
        if user in ready_players or user in bailouts:
            continue
        random_message = random.choice(ready_dm_messages)  # Select a random message
        await send_dm(user, f'{random_message} {ready_up_url}')
    log_async_end('start_ready_check')

# Function to display the ready-up message
async def display_ready_up(channel):
    log_async_start('display_ready_up')
    global ready_message
    embed = ready_up_embed()

    # Send the ready-up message and store its reference
    if ready_message:
        await ready_message.edit(embed=embed)
    else:
        ready_message = await channel.send(embed=embed, view=ReadyUpView())
    log_async_end('display_ready_up')

# Function to update the ready-up message (players and timer)
async def update_ready_up_message():
    log_async_start('update_ready_up_message')
    if ready_message:
        embed = ready_up_embed()
        await ready_message.edit(embed=embed)
    log_async_end('update_ready_up_message')

# Gets a killstreak string for the number of non-ready players
def queue_killstreak_str(num):
    if num in queue_kill_comments:
        return f'***{queue_kill_comments[num]}*** {"💀" * num}'
    return f'Not all players were ready.'

# Countdown timer for the ready-up phase
async def countdown_ready_up(channel):
    log_async_start('countdown_ready_up')
    global ready_up_timed_out
    #  Wait the full duration, since we now have a timestamp that counts down automatically
    await asyncio.sleep(ready_up_time)
    # Timeout reached: proceed with ready players or reset queue
    ready_up_timed_out = True
    await end_ready_up(channel)
    log_async_end('countdown_ready_up')

# Ends a ready up phase, called when either the timer runs out or all players have readied/bailed
async def end_ready_up(channel):
    log_async_start('end_ready_up')
    global phase, queue, waiting_room, game_in_progress, queue_message, ready_players, all_ready_sent, ready_message
    if phase != Phase.READY or all_ready_sent:
        log_async_end('end_ready_up')
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
        log_async_end('end_ready_up')
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
    log_async_end('end_ready_up')

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
        log_async_start('ready_up')
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
            await interaction.response.send_message(f'{get_display_name(user)} is ready!', ephemeral=True, delete_after=ready_up_time)
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
            await interaction.response.send_message(f'{get_display_name(user)} is on standby!', ephemeral=True, delete_after=ready_up_time)
            await update_ready_up_message()
            await check_ready_complete(interaction.message.channel)
        log_async_end('ready_up')
            
    @discord.ui.button(label='Bail Out', style=discord.ButtonStyle.red)
    async def bail_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('bail_out')
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
                await interaction.response.send_message(f'{get_display_name(user)} is bailing out!', ephemeral=True, delete_after=ready_up_time)
                await update_ready_up_message()
                await check_ready_complete(interaction.message.channel)
        else:
            await interaction.response.send_message('You are not in the queue.', ephemeral=True, delete_after=msg_fade1)
        log_async_end('bail_out')

# checks if enough players have readied for the queue to go through
async def check_ready_complete(channel):
    log_async_start('check_ready_complete')
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
    log_async_end('check_ready_complete')

# proceeds to match setup
async def proceed_to_match_setup(channel):
    log_async_start('proceed_to_match_setup')
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
    new_match.update_re_queue() # update requeue order
    # remove old matches
    if len(matches) > max_matches_in_memory:
        min_match_number = min(matches)
        del matches[min_match_number]
    # Send a completely new queue message instead of editing the old one
    embed = queue_embed()
    queue_message = await channel.send(embed=embed, view=QueueView())
    
    await new_match.proceed_to_map_voting(channel)
    log_async_end('proceed_to_match_setup')

# Class for map voting
class MapVotingView(View):
    def __init__(self, match: PugMatch):
        super().__init__(timeout=None)
        self.match = match
        for game_map in GameMap.All:
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
        log_async_start('vote_1')
        await self.match.register_matchup_vote(interaction, 1)
        log_async_end('vote_1')

    @discord.ui.button(label='Matchup 2', style=discord.ButtonStyle.primary, custom_id='vote_2')
    async def vote_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('vote_2')
        await self.match.register_matchup_vote(interaction, 2)
        log_async_end('vote_2')

    @discord.ui.button(label='Matchup 3', style=discord.ButtonStyle.primary, custom_id='vote_3')
    async def vote_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('vote_3')
        await self.match.register_matchup_vote(interaction, 3)
        log_async_end('vote_3')

    @discord.ui.button(label='Re-roll 🎲', style=discord.ButtonStyle.secondary, custom_id='vote_reroll')
    async def vote_reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('vote_reroll')
        await self.match.register_matchup_vote(interaction, reroll_key)
        log_async_end('vote_reroll')
    
    @discord.ui.button(label='Custom', style=discord.ButtonStyle.secondary, custom_id='vote_custom')
    async def vote_custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('vote_custom')
        await self.match.register_matchup_vote(interaction, custom_teams_key)
        log_async_end('vote_custom')




# View for reporting the final result of a match and resetting the queue
class FinalMatchupView(View):
    def __init__(self, match: PugMatch):
        super().__init__(timeout=None)
        self.match = match
 
    @discord.ui.button(label='Match Complete', style=discord.ButtonStyle.red)
    async def complete_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_async_start('complete_match')
        await self.match.register_reset_vote(interaction)
        log_async_end('complete_match')

# Create a waiting room for players not in the Final Matchup
async def create_waiting_room(channel):
   log_async_start('create_waiting_room')
   global waiting_room_message
   embed = waiting_room_embed()
   if waiting_room_message:
       await waiting_room_message.edit(embed=embed)
   else:
       waiting_room_message = await channel.send(embed=embed, view=QueueView())
   log_async_end('create_waiting_room')

# Function to update the waiting room message
async def update_waiting_room_message():
   log_async_start('update_waiting_room_message')
   if waiting_room_message:
       embed = waiting_room_embed()
       await waiting_room_message.edit(embed=embed)
   log_async_end('update_waiting_room_message')

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
    log_async_start('restart_queue')
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
    log_async_end('restart_queue')


# Add waiting room players to the new queue
def add_waiting_room_players_to_queue():
    global queue, waiting_room
    if current_match: # Move all players from requeue into waiting room
        non_duplicates = [user for user in current_match.re_queue if user not in waiting_room]
        waiting_room.extend(non_duplicates)
    # Move players out of the waiting room until queue is full or waiting room is empty
    queue[:] = waiting_room[:queue_size_required]  
    waiting_room[:] = waiting_room[queue_size_required:]

# Start a new queue programmatically without needing the command context
async def start_new_queue(channel):
   log_async_start('start_new_queue')
   global phase, queue_message, waiting_room_message
   phase = Phase.QUEUE
   # Send a completely new queue message instead of editing the old one
   embed = queue_embed()
   queue_message = await channel.send(embed=embed, view=QueueView())
   waiting_room_message = await remove_message(waiting_room_message)
   try_save_pug() # save state and players automatically
   await check_full_queue()
   log_async_end('start_new_queue')
   
# Function to remove the given message (message = await remove_message(message))
async def remove_message(message: discord.Message):
   log_async_start('remove_message')
   if message:
       try:
           await message.delete()
       except discord.NotFound:
           log_msg(LogLevel.WARNING, 'Message was already deleted')
   log_async_end('remove_message')
   return None

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

# checks if a user is configured as an admin
def is_user_admin(ctx):
    return ctx.message.author.id in admin_ids

# initializes bot after first login
async def init_on_first_login():
    log_async_start('init_on_first_login')
    global phase, queue, queue_message
    load_user_settings()
    # load saved state if there is any, it says which channel to start the queue in
    try:
        state_path = load_saved_state(None)
    except Exception as e:
        log_msg(LogLevel.ERROR, str(e))
        log_async_end('init_on_first_login')
        return
    if not state_path:
        log_async_end('init_on_first_login')
        return
    log_msg(LogLevel.NONE, f'PUG state loaded from {state_path} on match #{match_number}')
    if queue_channel_id == 0: # if no channel id stored, do not start queue
        log_msg(LogLevel.WARNING, f'No queue channel found in loaded pug')
        log_async_end('init_on_first_login')
        return
    channel = bot.get_channel(queue_channel_id)
    if not channel:
        log_msg(LogLevel.WARNING, f'Queue channel {queue_channel_id} was not found, so the queue was not started')
        log_async_end('init_on_first_login')
        return
    # load saved players if there are any, the queue still starts if there are not
    try:
        players_path = load_saved_players(channel.guild)
        if players_path:
            log_msg(LogLevel.NONE, f'PUG players loaded from {players_path} with {total_queue_size()} players in queue')
    except Exception as e:
        log_msg(LogLevel.ERROR, str(e))
    log_msg(LogLevel.NONE, f'Automatically starting queue')
    phase = Phase.QUEUE
    # send queue message
    embed = queue_embed()
    queue_message = await channel.send(embed=embed, view=QueueView())
    # If we have the required number of players, move to ready check
    await check_full_queue()
    log_async_end('init_on_first_login')

# gets a message with commands to join a server game
def server_commands_msg(address_and_port):
    cmd1 = f'`open {address_and_port}?team=0` (TEAM 1)'
    cmd2 = f'`open {address_and_port}?team=1` (TEAM 2)'
    msg_lines = [cmd1]
    if current_match and current_match.final_team1_names:
        msg_lines.append(current_match.final_team1_names)
        msg_lines.append('')
    msg_lines.append(cmd2)
    if current_match and current_match.final_team2_names:
        msg_lines.append(current_match.final_team2_names)
    return '\n'.join(msg_lines)

# sends a message with commands to join a server game
async def send_server_join_commands(ctx, address_and_port):
    log_async_start('send_server_join_commands')
    await ctx.send(server_commands_msg(address_and_port))
    if current_match:
        current_match.update_start_time()
    log_async_end('send_server_join_commands')

# gets the PUG state to save
def pug_state_data():
    return {
        'version': 1,
        # if the final matchup has been posted, save the next match number
        'match_number': match_number + 1 if phase >= Phase.PLAY else match_number,
        'channel_id': queue_channel_id,
        'setup_server': server_setup_address,
        'max_players': default_max_players,
        'creature1': default_creature1.codename,
        'creature2': default_creature2.codename,
        'creature3': default_creature3.codename,
        'creature3r': default_creature3r.codename
    }

# gets the ids of the PUG players to save, in the order they are loaded back into the queue
def pug_player_ids():
    user_ids = []
    if phase < Phase.PLAY and queue:
        user_ids.extend(user.id for user in queue)
    if waiting_room:
        user_ids.extend(user.id for user in waiting_room)
    if phase >= Phase.PLAY and current_match and current_match.re_queue:
        user_ids.extend(user.id for user in current_match.re_queue)
    return user_ids

# writes data to a json file, using a temporary file so a failed save cannot leave a partial file
def write_json_file(path, data):
    temp_path = f'{path}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=2)
    os.replace(temp_path, path)

# attempts to save the pug state and players to json files
def try_save_pug(save_state = True, save_players = True):
    if save_state:
        try:
            write_json_file(save_file_path, pug_state_data())
            log_msg(LogLevel.NONE, f'PUG state saved on match #{match_number}')
        except Exception as e:
            log_msg(LogLevel.ERROR, f'Error saving PUG state: {e}')
            return False
    if save_players:
        try:
            write_json_file(save_players_file_path, {'version': 1, 'players': pug_player_ids()})
            log_msg(LogLevel.NONE, f'PUG players saved with {total_queue_size()} players in queue')
        except Exception as e:
            log_msg(LogLevel.ERROR, f'Error saving PUG players: {e}')
            return False
    return True

# gets the value of a setting that a user can change for themselves
def get_user_setting(user, name):
    return user_settings.get(user.id, {}).get(name, user_setting_defaults[name])

# changes a setting for a user and saves the user settings, returns False if they could not be saved
def set_user_setting(user, name, value):
    user_settings.setdefault(user.id, {})[name] = value
    try:
        users_data = {str(user_id): settings for user_id, settings in user_settings.items()}
        write_json_file(user_settings_file_path, {'version': 1, 'users': users_data})
    except Exception as e:
        log_msg(LogLevel.ERROR, f'Error saving user settings: {e}')
        return False
    return True

# loads the user settings from their json file, if there is one
# a file that cannot be read is renamed to keep it, since the next save would replace it
def load_user_settings():
    if not os.path.isfile(user_settings_file_path):
        return
    try:
        with open(user_settings_file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        if not isinstance(data, dict) or not isinstance(data.get('users'), dict):
            raise ValueError('the file does not contain a users object')
        loaded = {}
        for user_id, settings in data['users'].items():
            if not isinstance(settings, dict):
                raise ValueError(f'the settings of user {user_id} are not an object')
            # ignore settings that no longer exist or have the wrong type
            loaded[int(user_id)] = {name: value for name, value in settings.items()
                                    if name in user_setting_defaults and type(value) is type(user_setting_defaults[name])}
        user_settings.clear()
        user_settings.update(loaded)
        log_msg(LogLevel.NONE, f'User settings loaded for {len(user_settings)} users from {user_settings_file_path}')
    except Exception as e:
        log_msg(LogLevel.ERROR, f'Error loading user settings from {user_settings_file_path}: {e}')
        try:
            os.replace(user_settings_file_path, f'{user_settings_file_path}.corrupt')
        except OSError as rename_error:
            log_msg(LogLevel.ERROR, f'Could not keep the unreadable user settings file: {rename_error}')

# function to load the PUG state from an older txt file
def load_pug(guild, file):
    global match_number, queue_channel_id, server_setup_address, default_max_players
    global default_creature1, default_creature2, default_creature3, default_creature3r
    line_type = 'match' # backwards compatibility with file that is match number followed by players
    for id_line in file:
        id_line_strip = id_line.strip()
        if not id_line_strip.isdecimal(): # non-number is line type or custom server
            if (len(id_line_strip) > 0):
                match line_type:
                    case 'setup_server':
                        server_setup_address = id_line_strip
                        line_type = ''
                    case 'creature1':
                        creature = GameCreature.from_string(id_line_strip)
                        if creature and not creature.blocked_message:  # a creature that cannot be selected is not loaded
                            default_creature1 = creature
                        line_type = ''
                    case 'creature2':
                        creature = GameCreature.from_string(id_line_strip)
                        if creature and not creature.blocked_message:  # a creature that cannot be selected is not loaded
                            default_creature2 = creature
                        line_type = ''
                    case 'creature3':
                        creature = GameCreature.from_string(id_line_strip)
                        if creature and not creature.blocked_message:  # a creature that cannot be selected is not loaded
                            default_creature3 = creature
                        line_type = ''
                    case 'creature3r':
                        creature = GameCreature.from_string(id_line_strip)
                        if creature and not creature.blocked_message:  # a creature that cannot be selected is not loaded
                            default_creature3r = creature
                        line_type = ''
                    case 'custom_servers': # no longer used, skip this section of older save files
                        if not id_line_strip[0].isdigit():
                            line_type = id_line_strip
                    case _: # default case
                        line_type = id_line_strip
            continue
        num = int(id_line_strip)
        match line_type:
            case 'match':
                match_number = num
                line_type = 'players' # backwards compatibility with file that is match number followed by players
            case 'channel':
                queue_channel_id = num
                if not guild: # if not coming from a !pug_start command, get the saved channel's guild
                    guild = bot.get_channel(queue_channel_id).guild
            case 'max_players':
                default_max_players = num
            case 'players': # backwards compatibility with file that contains players
                user = guild.get_member(num) # num is user id
                if user:
                    if len(queue) < queue_size_required:
                        if user not in queue:
                            queue.append(user)
                    else:
                        if user not in waiting_room:
                            waiting_room.append(user)
                else:
                    log_msg(LogLevel.WARNING, f'user not found: id={num}')

# adds saved players, given as user ids, to the queue and the waiting room
def add_saved_players(guild, user_ids):
    if not guild: # if not coming from a !start_pug command, get the saved channel's guild
        guild = bot.get_channel(queue_channel_id).guild
    for num in user_ids:
        user = guild.get_member(num) # num is user id
        if user:
            if len(queue) < queue_size_required:
                if user not in queue:
                    queue.append(user)
            else:
                if user not in waiting_room:
                    waiting_room.append(user)
        else:
            log_msg(LogLevel.WARNING, f'user not found: id={num}')

# function to load PUG players from an older txt file, which has one user id per line
def load_pug_players(guild, file):
    user_ids = [int(line.strip()) for line in file if line.strip().isdecimal()]
    add_saved_players(guild, user_ids)

# function to load the PUG state from the data of a json file
# values that are missing from the file keep their current value
def load_pug_json(data):
    global match_number, queue_channel_id, server_setup_address, default_max_players
    global default_creature1, default_creature2, default_creature3, default_creature3r
    if not isinstance(data, dict):
        raise ValueError('the file does not contain a json object')
    match_number = int(data.get('match_number', match_number))
    queue_channel_id = int(data.get('channel_id', queue_channel_id))
    server_setup_address = str(data.get('setup_server', server_setup_address))
    default_max_players = int(data.get('max_players', default_max_players))
    creature = GameCreature.from_string(str(data.get('creature1', '')))
    if creature and not creature.blocked_message:  # a creature that cannot be selected is not loaded
        default_creature1 = creature
    creature = GameCreature.from_string(str(data.get('creature2', '')))
    if creature and not creature.blocked_message:  # a creature that cannot be selected is not loaded
        default_creature2 = creature
    creature = GameCreature.from_string(str(data.get('creature3', '')))
    if creature and not creature.blocked_message:  # a creature that cannot be selected is not loaded
        default_creature3 = creature
    creature = GameCreature.from_string(str(data.get('creature3r', '')))
    if creature and not creature.blocked_message:  # a creature that cannot be selected is not loaded
        default_creature3r = creature

# loads the saved PUG state if there is any
# the json file is used if it exists, otherwise the older txt file
# returns the path of the file that was loaded, or None if there is no saved state
def load_saved_state(guild):
    path = save_file_path if os.path.isfile(save_file_path) else legacy_save_file_path
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as file:
            if path == save_file_path:
                load_pug_json(json.load(file))
            else:
                load_pug(guild, file)
    except Exception as e:
        raise RuntimeError(f'Failed to load saved PUG state from {path}: {e}') from e
    return path

# loads the saved PUG players if there are any, replacing the current queue
# the json file is used if it exists, otherwise the older txt file
# returns the path of the file that was loaded, or None if there are no saved players
def load_saved_players(guild):
    global queue
    path = save_players_file_path if os.path.isfile(save_players_file_path) else legacy_save_players_file_path
    if not os.path.isfile(path):
        return None
    queue = []
    try:
        with open(path, 'r', encoding='utf-8') as file:
            if path == save_players_file_path:
                data = json.load(file)
                if not isinstance(data, dict):
                    raise ValueError('the file does not contain a json object')
                add_saved_players(guild, [int(num) for num in data.get('players', [])])
            else:
                load_pug_players(guild, file)
    except Exception as e:
        queue = []
        raise RuntimeError(f'Failed to load saved PUG players from {path}: {e}') from e
    return path

# Command to end the PUG system
@bot.command(name='end_pug')
async def end_pug_cmd(ctx):
   log_async_start('end_pug_cmd')
   global phase, waiting_room, matches, current_match, results_match, game_in_progress, queue_message
   if not is_user_admin(ctx):
       await ctx.send('You do not have permission to use this command.', ephemeral=True, delete_after=msg_fade1)
       return
   if game_in_progress or queue_message:
       log_msg(LogLevel.NONE, 'Ending PUGs')
       try_save_pug() # save pug state and players to file
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
   log_async_end('end_pug_cmd')


# Command to start the PUG system
@bot.command(name='start_pug')
async def start_pug_cmd(ctx):
   log_async_start('start_pug_cmd')
   global queue_channel_id, phase, queue, queue_message, game_in_progress
   if not is_user_admin(ctx):
       await ctx.send('You do not have permission to use this command.', ephemeral=True, delete_after=msg_fade1)
       return
   if not game_in_progress and not queue_message:
      log_msg(LogLevel.NONE, 'Starting PUGs')
      phase = Phase.QUEUE
      # load state if there is any
      try:
         state_path = load_saved_state(ctx.message.guild)
         if state_path:
            log_msg(LogLevel.NONE, f'PUG state loaded from {state_path} on match #{match_number}')
      except Exception as e:
         log_msg(LogLevel.ERROR, str(e))
      # load players if there are any
      try:
         players_path = load_saved_players(ctx.message.guild)
         if players_path:
            log_msg(LogLevel.NONE, f'PUG players loaded from {players_path} with {total_queue_size()} players in queue')
      except Exception as e:
         log_msg(LogLevel.ERROR, str(e))
      queue_channel_id = ctx.message.channel.id # save channel that command was used
      # send queue message
      embed = queue_embed()
      queue_message = await ctx.send(embed=embed, view=QueueView())
      # If we have the required number of players, move to ready check
      await check_full_queue()
   else:
       await ctx.send('A match is already in progress or the queue is active.')
   log_async_end('start_pug_cmd')

# Command to set the max players allowed on a game server
@bot.command(name='max_players', aliases=['maxp'])
async def max_players_cmd(ctx, num_str = ''):
    global default_max_players
    if len(num_str.strip()) == 0:
        await ctx.send(f'Server config: `max players = {default_max_players}`')
        return
    
    try:
        num_players = int(num_str)
    except ValueError:
        await ctx.send(f'Unable to parse number of players from `!max_players {num_str}`')
        return
    
    default_max_players = num_players
    if current_match:
        current_match.server_max_players = default_max_players
    try_save_pug(save_players=False) # save state
    await ctx.send(f'Server config updated: `max players = {default_max_players}`')

# gets the current ceatures for server setup
def current_creatures_text():
    return f'''creature1  - {default_creature1}
creature2  - {default_creature2}
creature3  - {default_creature3}  (non-reef maps)
creature3r - {default_creature3r} (reef maps only)'''

# Command to show a list of all available creatures
@bot.command(name='creatures', aliases=['cre'])
async def creatures_cmd(ctx):
    creatures_text = '\n'.join([f'{creature.codename} - {creature.name}' + (' (bugged, cannot be set)' if creature.blocked_message else '') for creature in GameCreature.All])
    await ctx.send(f'Current Creatures\n```{current_creatures_text()}```\nAvailable Creatures\n```{creatures_text}```')

# gets the creature a command was given, or None after telling the user why it cannot be used
async def creature_from_command(ctx, command_name, name):
    creature = GameCreature.from_string(name)
    if not creature:
        await ctx.send(f'Unable to parse creature from `!{command_name} {name}`.  Use the !creatures command to get a list of available creatures')
        return None
    if creature.blocked_message:
        await ctx.send(creature.blocked_message)
        return None
    return creature

# Command to set the creature used on the 1 key for map setup (all maps)
@bot.command(name='creature1', aliases=['cre1'])
async def creature1_cmd(ctx, name = ''):
    global default_creature1
    creature = await creature_from_command(ctx, 'creature1', name)
    if not creature:
        return

    default_creature1 = creature
    if current_match:
        current_match.selected_creature1 = creature
    try_save_pug(save_players=False) # save state
    await ctx.send(f'Server config updated\n```{current_creatures_text()}```')

# Command to set the creature used on the 2 key for map setup (all maps)
@bot.command(name='creature2', aliases=['cre2'])
async def creature2_cmd(ctx, name = ''):
    global default_creature2
    creature = await creature_from_command(ctx, 'creature2', name)
    if not creature:
        return
    
    default_creature2 = creature
    if current_match:
        current_match.selected_creature2 = creature
    try_save_pug(save_players=False) # save state
    await ctx.send(f'Server config updated\n```{current_creatures_text()}```')

# Command to set the creature used on the 3 key for map setup (non-reef maps)
@bot.command(name='creature3', aliases=['cre3'])
async def creature3_cmd(ctx, name = ''):
    global default_creature3
    creature = await creature_from_command(ctx, 'creature3', name)
    if not creature:
        return
    
    default_creature3 = creature
    # set current match creature only if map has not been selected or if selected map is not reef
    if current_match and ((not current_match.selected_map) or not current_match.selected_map.is_reef):
        current_match.selected_creature3 = creature
    try_save_pug(save_players=False) # save state
    await ctx.send(f'Server config updated\n```{current_creatures_text()}```')

# Command to set the creature used on the 3 key for map setup (reef maps)
@bot.command(name='creature3r', aliases=['cre3r'])
async def creature3r_cmd(ctx, name = ''):
    global default_creature3r
    creature = await creature_from_command(ctx, 'creature3r', name)
    if not creature:
        return
    
    default_creature3r = creature
    # set current match creature only if map has been selected and is reef
    if current_match and current_match.selected_map and current_match.selected_map.is_reef:
        current_match.selected_creature3 = creature
    try_save_pug(save_players=False) # save state
    await ctx.send(f'Server config updated\n```{current_creatures_text()}```')

# Command to set the address of the game server setup page
@bot.command(name='setup')
async def setup_cmd(ctx, address = ''):
    global server_setup_address
    address_stripped = address.strip().strip('<>') # discord users often wrap links in <>
    if len(address_stripped) > 0: # if an address was sent, update the value
        reason = await asyncio.to_thread(check_server_address, address_stripped)
        if reason:
            await ctx.send(f'Server setup page was not changed: {reason}')
            return
        server_setup_address = address_stripped
        try_save_pug(save_players=False) # save state
    await ctx.send(f'Server setup page: {server_setup_address}')

# Command to post commands to join each team for the game server
# Can also be used to set the game server if it was set up manually
@bot.command(name='join')
async def join_cmd(ctx, address = ''):
    if (not current_match) or (phase != Phase.PLAY):
        await ctx.send(f'No game in progress found.  There must be a game in progress to post join commands.')
        return
    address_stripped = address.strip()
    if len(address_stripped) > 0: # if an address was sent, update the value
        # the address is repeated in bot messages, so it must look like host or host:port
        if not server_address_pattern.fullmatch(address_stripped):
            await ctx.send(f'That does not look like a server address.  Use `!join host:port`, for example `!join myserver.servegame.com:7777`.')
            return
        current_match.server_address_and_port = address_stripped
        await current_match.update_final_matchup()
    if not current_match.server_address_and_port:
        await ctx.send(f'No game server address has been set for this match.  Use `!join address:port` to set it.')
        return
    # post join commands and teams as a response
    await send_server_join_commands(ctx, current_match.server_address_and_port)

# Command to manually add users to the queue
@bot.command(name='queue_users')
async def queue_users_cmd(ctx, members: commands.Greedy[discord.Member]):
    log_async_start('queue_users_cmd')
    if not is_user_admin(ctx):
       await ctx.send('You do not have permission to use this command.', ephemeral=True, delete_after=msg_fade1)
       return
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
        try_save_pug(save_state=False) # save players automatically
    else:
        await ctx.send('Cannot queue players, queue message not found.')
    log_async_end('queue_users_cmd')

# Command to set custom team 1
@bot.command(name='ct1')
async def ct1_cmd(ctx, members: commands.Greedy[discord.Member]):
    log_async_start('ct1_cmd')
    if not current_match:
        await ctx.send('Cannot set custom teams until players are in a match.')
        log_async_end('ct1_cmd')
        return
    if current_match.phase > Phase.PLAY:
        await ctx.send('Cannot set custom teams once a match is complete.')
        log_async_end('ct1_cmd')
        return
    if current_match.phase == Phase.PLAY and current_match.selected_matchup != custom_teams_key:
        await ctx.send('Cannot set custom teams once a non-custom matchup has won the vote.')
        log_async_end('ct1_cmd')
        return
    players_in_match = [p for p in members if p in current_match.players]
    if len(players_in_match) != team_size:
        await ctx.send(f'Must set a custom team of {team_size} players in the current match.')
        log_async_end('ct1_cmd')
        return 
    current_match.custom_team1 = list(players_in_match)
    current_match.custom_team2 = list(set(current_match.players) - set(current_match.custom_team1))
    await current_match.on_custom_teams_changed(ctx.message.channel)
    custom_team1_names = ', '.join([get_display_name(user) for user in current_match.custom_team1])
    custom_team2_names = ', '.join([get_display_name(user) for user in current_match.custom_team2])
    await ctx.send(f'Custom Team 1 has been set to: {custom_team1_names}.\nCustom Team 2 has been set to: {custom_team2_names}.')
    log_async_end('ct1_cmd')

# Command to set custom team 2
@bot.command(name='ct2')
async def ct2_cmd(ctx, members: commands.Greedy[discord.Member]):
    log_async_start('ct2_cmd')
    if not current_match:
        await ctx.send('Cannot set custom teams until players are in a match.')
        log_async_end('ct2_cmd')
        return
    if current_match.phase > Phase.PLAY:
        await ctx.send('Cannot set custom teams once a match is complete.')
        log_async_end('ct2_cmd')
        return
    if current_match.phase == Phase.PLAY and current_match.selected_matchup != custom_teams_key:
        await ctx.send('Cannot set custom teams once a non-custom matchup has won the vote.')
        log_async_end('ct2_cmd')
        return
    players_in_match = [p for p in members if p in current_match.players]
    if len(players_in_match) != team_size:
        await ctx.send(f'Must set a custom team of {team_size} players in the current match.')
        log_async_end('ct2_cmd')
        return 
    current_match.custom_team2 = list(players_in_match)
    current_match.custom_team1 = list(set(current_match.players) - set(current_match.custom_team2))
    await current_match.on_custom_teams_changed(ctx.message.channel)
    custom_team1_names = ', '.join([get_display_name(user) for user in current_match.custom_team1])
    custom_team2_names = ', '.join([get_display_name(user) for user in current_match.custom_team2])
    await ctx.send(f'Custom Team 1 has been set to: {custom_team1_names}.\nCustom Team 2 has been set to: {custom_team2_names}.')
    log_async_end('ct2_cmd')

# Command to trade two players on opposite teams, !swap does the same thing
@bot.command(name='trade', aliases=['swap'])
async def trade_cmd(ctx, members: commands.Greedy[discord.Member]):
    log_async_start('trade_cmd')
    if not current_match:
        await ctx.send('Cannot trade players until players are in a match.')
        log_async_end('trade_cmd')
        return
    if current_match.phase <= Phase.MATCHUP:
        await ctx.send('Cannot trade players until a final matchup has been set.')
        log_async_end('trade_cmd')
        return
    if current_match.phase > Phase.PLAY:
        await ctx.send('Cannot trade players once a match is complete.')
        log_async_end('trade_cmd')
        return
    # find which players are on which team
    team1_players = [p for p in members if p in current_match.final_team1]
    team2_players = [p for p in members if p in current_match.final_team2]
    if len(team1_players) != 1 or len(team2_players) != 1:
        await ctx.send(f'Must trade two players on opposite teams.')
        log_async_end('trade_cmd')
        return
    p1 = team1_players[0]
    p2 = team2_players[0]
    # perform trade
    replace_list_item(current_match.final_team1, p1, p2)
    replace_list_item(current_match.final_team2, p2, p1)
    await current_match.on_final_teams_changed(ctx.message.channel)
    await ctx.send(f'{get_display_name(p1)} has been traded to Team 2 and {get_display_name(p2)} has been traded to Team 1.')
    log_async_end('trade_cmd')

# trades two players on opposite teams of a matchup, used by the commands below
async def trade_matchup_players(ctx, members, matchup_number):
    if not current_match:
        await ctx.send('Cannot trade players until players are in a match.')
        return
    if current_match.phase != Phase.MATCHUP or matchup_number > len(current_match.matchups):
        await ctx.send('Matchups can only be traded during the matchup vote.')
        return
    # find which players are on which team of the matchup
    team1, team2 = current_match.matchups[matchup_number - 1]
    team1_players = [p for p in members if p in team1]
    team2_players = [p for p in members if p in team2]
    if len(team1_players) != 1 or len(team2_players) != 1:
        await ctx.send(f'Must trade two players on opposite teams of Matchup {matchup_number}.')
        return
    p1 = team1_players[0]
    p2 = team2_players[0]
    await current_match.trade_in_matchup(matchup_number, p1, p2, ctx.message.channel)
    await ctx.send(f'In Matchup {matchup_number}, {get_display_name(p1)} has been traded to Team 2 and {get_display_name(p2)} has been traded to Team 1.')

# Commands to trade two players on opposite teams of matchup 1, 2 or 3 during the matchup vote, !swap1 and so on do the same thing
@bot.command(name='trade1', aliases=['swap1'])
async def trade1_cmd(ctx, members: commands.Greedy[discord.Member]):
    log_async_start('trade1_cmd')
    await trade_matchup_players(ctx, members, 1)
    log_async_end('trade1_cmd')

@bot.command(name='trade2', aliases=['swap2'])
async def trade2_cmd(ctx, members: commands.Greedy[discord.Member]):
    log_async_start('trade2_cmd')
    await trade_matchup_players(ctx, members, 2)
    log_async_end('trade2_cmd')

@bot.command(name='trade3', aliases=['swap3'])
async def trade3_cmd(ctx, members: commands.Greedy[discord.Member]):
    log_async_start('trade3_cmd')
    await trade_matchup_players(ctx, members, 3)
    log_async_end('trade3_cmd')

# the replies to someone trying to fill in the bot, which take turns
fill_bot_replies = itertools.cycle(['I WILL DESTROY YOU!', 'DIE!'])

# Command to replace a player in the match with one not in the match
@bot.command(name='fill')
async def fill_cmd(ctx, members: commands.Greedy[discord.Member]):
    log_async_start('fill_cmd')
    if any(member.id == bot.user.id for member in members): # the bot cannot fill, do not change anything
        await ctx.send(next(fill_bot_replies))
        log_async_end('fill_cmd')
        return
    if not current_match:
        await ctx.send('Cannot fill for a player until players are in a match.')
        log_async_end('fill_cmd')
        return
    if current_match.phase > Phase.PLAY:
        await ctx.send('Cannot fill for a player once a match is complete.')
        log_async_end('fill_cmd')
        return
    # find which players are in the match
    in_players = [p for p in members if p in current_match.players]
    out_players = [p for p in members if p not in current_match.players]
    if len(in_players) != 1 or len(out_players) != 1:
        await ctx.send(f'Must fill a player in the match with one not in the match.')
        log_async_end('fill_cmd')
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
    try_save_pug(save_state=False) # save players automatically
    log_async_end('fill_cmd')

# Command to post the ready alarm image for everyone in the channel to see
# the image link is posted as text and discord shows the image from it
@bot.command(name='readyalarm')
async def readyalarm_cmd(ctx):
    log_async_start('readyalarm_cmd')
    await ctx.send(ready_alarm_image_url)
    log_async_end('readyalarm_cmd')

# switches an on or off setting of the user who used a command, and tells them which way it is now
# what says which messages the setting is for, for example 'DMs from this bot'
async def toggle_user_setting(ctx, setting, command_name, what):
    value = not get_user_setting(ctx.author, setting)
    saved = set_user_setting(ctx.author, setting, value)
    msg = f'{get_display_name(ctx.author)}, {what} are now {"on" if value else "off"}.  Use `!{command_name}` again to turn them {"off" if value else "on"}.'
    if value and setting != 'dms' and not get_user_setting(ctx.author, 'dms'):
        msg += '  You will not get them until you turn DMs on with `!pugdms`.'
    if not saved:
        msg += '  This could not be saved, so it may be lost when the bot restarts.'
    await ctx.send(msg, delete_after=msg_fade2)

# Command for a user to turn all of the bot's direct messages to them on or off, it switches each time
@bot.command(name='pugdms')
async def pugdms_cmd(ctx):
    log_async_start('pugdms_cmd')
    await toggle_user_setting(ctx, 'dms', 'pugdms', 'DMs from this bot')
    log_async_end('pugdms_cmd')

# Command for a user to turn the direct message when the map vote starts on or off, it switches each time
# it is off until the user turns it on, and nothing is sent while all DMs are off
@bot.command(name='pugdms_vote')
async def pugdms_vote_cmd(ctx):
    log_async_start('pugdms_vote_cmd')
    await toggle_user_setting(ctx, 'dms_vote', 'pugdms_vote', 'map vote DMs')
    log_async_end('pugdms_vote_cmd')

# Command for a user to turn the direct message when the final matchup is posted on or off, it switches each time
# it is off until the user turns it on, and nothing is sent while all DMs are off
@bot.command(name='pugdms_join')
async def pugdms_join_cmd(ctx):
    log_async_start('pugdms_join_cmd')
    await toggle_user_setting(ctx, 'dms_join', 'pugdms_join', 'final matchup DMs')
    log_async_end('pugdms_join_cmd')

# Command to set scoreboard
@bot.command(name='sb')
async def sb_cmd(ctx, score_str: str = 'x'):
    log_async_start('sb_cmd')
    if not results_match:
        await ctx.send('Cannot update scoreboard, no match is active.')
        log_async_end('sb_cmd')
        return
    if not ctx.message.attachments:
        await ctx.send('No image attached, must attach an image of the scoreboard.')
        log_async_end('sb_cmd')
        return
    if not ctx.message.attachments[0].content_type.startswith('image'):
        await ctx.send(f'Must attach an image, you attached a {ctx.message.attachments[0].content_type}.')
        log_async_end('sb_cmd')
        return
    # check file size
    size_mb = ctx.message.attachments[0].size / 1000000
    if size_mb >= 10:
        await ctx.send(f'Image must be less than 10 MB, you attached a {size_mb} MB image.')
        log_async_end('sb_cmd')
        return
    
    # convert attached image to a file to attach to our own message
    scoreboard_file = await ctx.message.attachments[0].to_file()
    #sb_filename = f'sb/sb{results_match.match_number}.png'
    #sb_saved = await ctx.message.attachments[0].save(sb_filename)
    #scoreboard_file = discord.File(sb_filename)
    await results_match.update_scoreboard(ctx, scoreboard_file)
    #os.remove(sb_filename)  # delete scoreboard file
    
    try:
        score = int(score_str)
    except ValueError:
        log_async_end('sb_cmd')
        return
    await results_match.update_wounds(ctx, score)
    log_async_end('sb_cmd')

# Command to set remaining wounds score
@bot.command(name='wounds')
async def wounds_cmd(ctx, score_str: str = 'x'):
    log_async_start('wounds_cmd')
    if not results_match:
        await ctx.send('Cannot update wounds, no match is active.')
        log_async_end('wounds_cmd')
        return
    try:
        score = int(score_str)
    except ValueError:
        await ctx.send(f'Unable to parse number of wounds from !wounds {score_str}.')
        log_async_end('wounds_cmd')
        return
    await results_match.update_wounds(ctx, score) 
    log_async_end('wounds_cmd')

# Handles errors raised while running a command
# replies never repeat what the user typed, so they cannot be used to make the bot post a mention
@bot.event
async def on_command_error(ctx, error):
    # ignore commands that do not exist, people mistype them and other bots may use the same prefix
    if isinstance(error, commands.CommandNotFound):
        return
    try:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f'`!{ctx.invoked_with}` needs more information: {error.param.name}.  See <{help_url}> for how to use it.', delete_after=msg_fade2)
        elif isinstance(error, commands.UserInputError): # arguments that could not be understood
            await ctx.send(f'I could not understand the arguments for `!{ctx.invoked_with}`.  See <{help_url}> for how to use it.', delete_after=msg_fade2)
        else: # a bug or a problem talking to discord
            original = getattr(error, 'original', error)
            log_msg(LogLevel.ERROR, f'Error in command !{ctx.invoked_with}: {original!r}')
            traceback.print_exception(type(error), error, error.__traceback__)
            await ctx.send(f'Something went wrong running `!{ctx.invoked_with}`.', delete_after=msg_fade2)
    except discord.HTTPException as e:
        log_msg(LogLevel.WARNING, f'Could not reply to the error in command !{ctx.invoked_with}: {e}')

# Run the bot
bot.run(TOKEN)