#!/usr/bin/env bash
# This month's AWS spend so far, by service (Cost Explorer). Billing data lags
# 8-24 hours. Each Cost Explorer request costs $0.01; this makes one.
#   make cost
set -euo pipefail
source "$(dirname "$0")/lib.sh"

start="$(date +%Y-%m-01)"
end="$(date -v+1d +%Y-%m-%d 2>/dev/null || date -d tomorrow +%Y-%m-%d)" # macOS or GNU date
aws ce get-cost-and-usage --time-period Start="$start",End="$end" --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE --output json \
  | jq -r --arg start "$start" '.ResultsByTime[0].Groups
      | map({service: .Keys[0], usd: (.Metrics.UnblendedCost.Amount | tonumber)})
      | map(select(.usd >= 0.005)) | sort_by(-.usd)
      | (.[] | "  $\(.usd * 100 | round / 100)\t\(.service)"),
        "  ----",
        "  $\(map(.usd) | add // 0 | . * 100 | round / 100)\tTotal, \($start) to today"' 
