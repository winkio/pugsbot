# Commands

Type these in Discord, in the channel where the bot is running. Commands are not case-sensitive, so `!SB` and `!sb` do the same thing.

- [Match](#match)
- [Your settings](#your-settings)
- [Server setup](#server-setup)

## Match

Managing the current match.

| Command | What it does |
| --- | --- |
| `!ct1` `!ct2` | Use with user names to set Team 1 or Team 2 for custom teams. |
| `!trade` `!swap` | Trades two players on opposite teams. |
| `!trade1` `!trade2` `!trade3` | During the matchup vote, trades two players on opposite teams of that matchup and updates the vote. `!swap1`, `!swap2` and `!swap3` do the same thing. Votes already cast stay as they are. Example: `!trade2 @Alice @Bob` trades Alice and Bob in Matchup 2. |
| `!fill` | Replaces a player in the match with one who is not in the match. |
| `!readyalarm` | Posts the ready alarm image in the channel, for everyone to see. |
| `!sb` | Use with an attached image to set the scoreboard of the current match. You can also pass the remaining wounds to set them at the same time. Example: `!sb -1` sets the scoreboard image and the wounds together. |
| `!wounds` | Use with a number to say which team won the current match and how many wounds remained. `+` means Team 1 won, `-` means Team 2 won. Examples: `!wounds 2` means Team 1 won with 2 wounds remaining, `!wounds -3` means Team 2 won with 3 wounds remaining. |

## Your settings

Settings that each player can change for themselves. The bot remembers them, also after it restarts.

| Command | What it does |
| --- | --- |
| `!pugdms` | Turns all the direct messages the bot sends you on or off, such as the message when the queue pops. It switches each time you use it, and the bot tells you which way it is now. They are on until you turn them off. |
| `!pugdms_vote` | Turns the direct message you get when the map vote starts, if you are in the match, on or off. The message links to the vote. It switches each time you use it, and it is off until you turn it on. You only get it while your DMs are on with `!pugdms`. |
| `!pugdms_join` | Turns the direct message you get when the final matchup is posted, if you are in the match, on or off. The message links to the final matchup, which has the commands to join the game server once it is set up. It switches each time you use it, and it is off until you turn it on. You only get it while your DMs are on with `!pugdms`. |

## Server setup

The bot can start a game server for the match through the server setup page.

| Command | What it does |
| --- | --- |
| `!setup` | Sets the address of the game server setup page. Include `http://` or `https://`. Only public web addresses are accepted. Without an address, it shows the current one. |
| `!join` | Posts the commands to join each team for the game server. It can also set the game server if you set it up manually. Example: `!join myserver.servegame.com:7777` |
| `!max_players` `!maxp` | Sets the maximum number of players allowed on the game server. Without a number, it shows the current value. |
| `!creatures` `!cre` | Shows the creatures currently selected and the list of all available creatures. |
| `!creature1` `!creature2` `!cre1` `!cre2` | Set the creature used on the 1 key or the 2 key for map setup, on all maps. |
| `!creature3` `!cre3` | Sets the creature used on the 3 key for map setup on non-reef maps. |
| `!creature3r` `!cre3r` | Sets the creature used on the 3 key for map setup on reef maps. |

Use the name or code name shown by `!creatures`, for example `!creature1 bloomer_winter`. These are all the creatures:

| Creature | Code name | Notes |
| --- | --- | --- |
| Summer Bloomer | `bloomer` | |
| Winter Bloomer | `bloomer_winter` | |
| Spring Bloomer | `bloomer_spring` | Bugged, cannot be set |
| Autumn Bloomer | `bloomer_autumn` | |
| Cerberus Majoris | `cerb` | |
| Shadow Cerberus | `cerb_shadow` | |
| Stone Cerberus | `cerb_stone` | |
| Mountain Cyclops | `cyclops` | |
| Yeti Cyclops | `cyclops_yeti` | |
| Riftborn Cyclops | `cyclops_riftborn` | |
| Fire Drake | `dragon` | |
| Storm Drake | `dragon_storm` | |
| Crimson Infernal | `infernal` | |
| Void Infernal | `infernal_void` | |
| Savage Infernal | `infernal_savage` | |
| Ancient Obelisk | `obelisk` | |
