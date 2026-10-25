# Config
Requires a file named `.env` in the same folder with the data:

```
DISCORD_TOKEN=____the token for the bot____
```

## Discord bot config
On discord under the Bot settings page, make sure Server Members Intent and Message Content Intent are enabled

## Admins
Admins can use these commands. Anyone else gets "You do not have permission to use this command."

| Command | What it does |
| --- | --- |
| `!start_pug` | Starts the PUG queue in the channel where you use it, and posts the queue message there. It loads the saved state and players if there are any. Does nothing if a match is in progress or the queue is already active. |
| `!end_pug` | Ends the current PUG session. The state and players are saved first, so `!start_pug` picks them up again. |
| `!queue_users` | Use with user names to add them to the queue. When the queue is full, they go to the waiting room instead. Example: `!queue_users @Alice @Bob` |

Nobody is an admin until you add your Discord user id to `config.toml`:

1. In Discord, open User Settings > Advanced and turn on Developer Mode.
2. Right-click your name or avatar anywhere in Discord and choose Copy User ID.
3. Add the id to `admin_ids` in `config.toml`, one entry per admin (a comment after each id is a good way to remember whose it is):

```toml
admin_ids = [
    123456789012345678,  # your name
]
```

4. Restart the bot.
