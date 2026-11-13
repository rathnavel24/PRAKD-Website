#!/bin/bash
# Show enquiries from the prakd.in contact form, newest first.  Usage: bash ~/apps/prakd-site/read-enquiries.sh [count]
cd "$(dirname "$0")/backend" && node --disable-warning=ExperimentalWarning -e '
const { DatabaseSync } = require("node:sqlite");
const rows = new DatabaseSync("data/enquiries.db", { readOnly: true })
  .prepare("select created_at,name,email,company,topics,message from enquiries order by created_at desc limit ?").all(Number(process.argv[1] || 20));
const ist = t => new Date(t).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short", hour12: false }) + " IST";
if (!rows.length) console.log("No enquiries yet.");
for (const r of rows) console.log(`\n${ist(r.created_at)}  ${r.name} <${r.email}>${r.company ? "  (" + r.company + ")" : ""}\n  topics: ${JSON.parse(r.topics).join(", ") || "-"}\n  ${(r.message || "").replace(/\n/g, "\n  ")}`);
' "${1:-20}"
