#!/usr/bin/env bash
set -euo pipefail

report_date="${1:-}"
[[ "$report_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "invalid report date: $report_date" >&2; exit 2; }
date -d "$report_date" '+%F' >/dev/null

repo_root="${CSBAOYAN_REPO_ROOT:-/opt/csbaoyan-daily}"
pages_dir="${CSBAOYAN_PAGES_DIR:-/var/www/csbaoyan}"
handoff_root="${CSBAOYAN_HANDOFF_ROOT:-/srv/csbaoyan-daily}"
input_file="$handoff_root/inbox/${report_date}Tedge.json"
done_file="$handoff_root/processed/${report_date}.sha256"
log_file="$handoff_root/logs/${report_date}.log"

mkdir -p "$handoff_root/inbox" "$handoff_root/processed" "$handoff_root/logs"
exec 9>"$handoff_root/logs/process.lock"
flock -n 9 || { echo "another report generation is already running" >&2; exit 75; }
exec > >(tee -a "$log_file") 2>&1

[[ -f "$input_file" ]] || { echo "handoff payload missing: $input_file" >&2; exit 3; }
input_hash="$(sha256sum "$input_file" | awk '{print $1}')"
if [[ -f "$done_file" ]] \
  && [[ "$(tr -d '\r\n' < "$done_file")" == "$input_hash" ]] \
  && [[ -s "$pages_dir/data/reports/$report_date.md" ]] \
  && [[ -s "$pages_dir/data/xhs/$report_date.json" ]]; then
    echo "already processed: $report_date"
    rm -f -- "$input_file"
    exit 0
fi

cd "$repo_root"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
"$repo_root/.venv/bin/python" -m csbaoyan_daily.cli pipeline \
  --repo-root "$repo_root" \
  --export-dir "$handoff_root/inbox" \
  --pages-dir "$pages_dir" \
  --date "$report_date" \
  --skip-commit \
  --skip-push \
  --xhs-export

[[ -s "$pages_dir/data/reports/$report_date.md" ]] || { echo "report was not produced" >&2; exit 4; }
[[ -s "$pages_dir/data/xhs/$report_date.json" ]] || { echo "XHS export was not produced" >&2; exit 5; }
printf '%s\n' "$input_hash" > "$done_file"
rm -f -- "$input_file"
echo "server report generation complete: $report_date"
