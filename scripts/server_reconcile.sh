#!/usr/bin/env bash
set -euo pipefail

handoff_root="${CSBAOYAN_HANDOFF_ROOT:-/srv/csbaoyan-daily}"
shopt -s nullglob
for input_file in "$handoff_root"/inbox/*Tedge.json; do
  file_name="$(basename "$input_file")"
  report_date="${file_name%%Tedge.json}"
  [[ "$report_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
  systemctl start --no-block "csbaoyan-daily@${report_date}.service"
done

