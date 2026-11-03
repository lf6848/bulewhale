#!/bin/bash
set -e
LINE='30 5 * * 7 /usr/bin/python3 /usr/local/bin/memory-prune.py --apply --max-mb 90 --target-mb 70 >> /var/log/memory-prune.log 2>&1'
touch /var/log/memory-prune.log
crontab -l 2>/dev/null > /tmp/ct || true
python3 - "$LINE" <<'PY'
import sys
line = sys.argv[1]
p = "/tmp/ct"
rows = [r for r in open(p).read().splitlines() if "memory-prune" not in r]
rows.append(line)
open(p, "w").write("\n".join(rows) + "\n")
PY
crontab /tmp/ct
echo "=== 当前 crontab ==="
crontab -l
