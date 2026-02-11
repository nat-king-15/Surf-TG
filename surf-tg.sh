if [ -d "venv" ]; then
    ./venv/bin/python3 update.py && ./venv/bin/python3 -m bot
else
    python3 update.py && python3 -m bot
fi