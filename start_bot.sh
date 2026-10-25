#! /bin/bash

# config

# full path of the folder that holds pugsbot.py, e.g. /home/<user>/app/<bot>
SCRIPTDIR="/path/to/bot/folder"
# the bot script inside that folder
SCRIPT="pugsbot.py"
# full path of the python virtualenv's activate script, e.g. /home/<user>/virtualenv/<bot>/3.11/bin/activate
SOURCEDIR="/path/to/virtualenv/bin/activate"
# full path of the file the bot's output is appended to, e.g. /home/<user>/logs/<bot>.log
LOGFILE="/path/to/bot.log"

# the script is run by its full path, so this bot can be told apart from other bots that run the same script name
SCRIPTPATH="${SCRIPTDIR}/${SCRIPT}"

# use pgrep to search for python processes running that exact script
if pgrep -f "[p]ython.* ${SCRIPTPATH}" >/dev/null; then
  echo "${SCRIPTPATH} is already running"
else
  echo "Starting ${SCRIPTPATH}"
  # set source and directory
  source "${SOURCEDIR}" && cd "${SCRIPTDIR}"
  # run script, append output to log file
  nohup python -u "${SCRIPTPATH}" >> "${LOGFILE}" 2>&1 &
fi