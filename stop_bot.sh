#! /bin/bash

# config

# full path of the folder that holds pugsbot.py, e.g. /home/<user>/app/<bot>
# (must match start_bot.sh, since this is how the running bot is found)
SCRIPTDIR="/path/to/bot/folder"
# the bot script inside that folder
SCRIPT="pugsbot.py"
# full path of the python virtualenv's activate script (same as start_bot.sh)
SOURCEDIR="/path/to/virtualenv/bin/activate"
# full path of the bot's log file (same as start_bot.sh)
LOGFILE="/path/to/bot.log"

# the script is run by its full path, so this bot can be told apart from other bots that run the same script name
SCRIPTPATH="${SCRIPTDIR}/${SCRIPT}"

# use pgrep to search for python processes running that exact script
if pgrep -f "[p]ython.* ${SCRIPTPATH}" >/dev/null; then
  echo "Stopping ${SCRIPTPATH}"
  # kill process
  pkill -f "[p]ython.* ${SCRIPTPATH}"
else
  echo "${SCRIPTPATH} has already stopped"
fi