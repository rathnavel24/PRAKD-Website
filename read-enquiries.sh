#!/bin/bash
# Show enquiries from the prakd.in contact form, newest first.  Usage: bash ~/apps/prakd-site/read-enquiries.sh [count]
cd "$(dirname "$0")/backend" && python3 - "${1:-20}" <<'PY'
import json, sqlite3, sys
from datetime import datetime
from zoneinfo import ZoneInfo

db = sqlite3.connect("file:data/enquiries.db?mode=ro", uri=True)
rows = db.execute("select created_at,name,email,company,topics,message from enquiries order by created_at desc limit ?",
                  (int(sys.argv[1]),)).fetchall()
if not rows:
    print("No enquiries yet.")
for created, name, email, company, topics, message in rows:
    when = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata"))
    print(f"\n{when:%d %b %Y, %H:%M} IST  {name} <{email}>" + (f"  ({company})" if company else ""))
    print(f"  topics: {', '.join(json.loads(topics)) or '-'}")
    print("  " + (message or "").replace("\n", "\n  "))
PY
