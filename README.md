# pugsbot
Discord bot for managing Gigantic PUGs, written in python. Original author: IluZDave

# config
Requires a file named '.env' in the same folder with the data:
DISCORD_TOKEN=____the token for the bot____

## discord bot config
On discord under the Bot settings page, make sure Server Members Intent and Message Content Intent are enabled

## admins
Admins can use !start_pug, !end_pug and !queue_users. Nobody is an admin until you add your Discord user id to `config.toml`:

1. In Discord, open User Settings > Advanced and turn on Developer Mode.
2. Right-click your name or avatar anywhere in Discord and choose Copy User ID.
3. Add the id to `admin_ids` in `config.toml`, one entry per admin (a comment after each id is a good way to remember whose it is):

```toml
admin_ids = [
    123456789012345678,  # your name
]
```

4. Restart the bot.
