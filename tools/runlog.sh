#!/bin/bash
# usage: runlog.sh <run_id> [grep pattern]  -> prints job log lines (timestamps stripped)
jid=$(curl -s --max-time 20 "https://api.github.com/repos/bryaniredev/What-the-world-needs-now/actions/runs/$1/jobs" | python3 -c "import json,sys;print(json.load(sys.stdin)['jobs'][0]['id'])")
echo "$jid"
