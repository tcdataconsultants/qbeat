#!/usr/bin/env python3
"""Set the server's YouTube search key without putting it in shell history."""
import getpass
import os
from pathlib import Path
import re
import subprocess

if os.geteuid() != 0:
    raise SystemExit('Run this script with sudo.')
key = getpass.getpass('YouTube Data API key (hidden): ').strip()
if not re.fullmatch(r'[A-Za-z0-9_-]{20,120}', key):
    raise SystemExit('The key format is invalid. Nothing was changed.')
path = Path('/etc/qbeat.env')
lines = [line for line in path.read_text().splitlines() if not line.startswith('YOUTUBE_API_KEY=')]
path.write_text('\n'.join(lines) + '\nYOUTUBE_API_KEY=' + key + '\n')
path.chmod(0o600)
subprocess.run(['systemctl', 'restart', 'qbeat'], check=True)
print('YouTube search configured. Qbeat restarted.')
