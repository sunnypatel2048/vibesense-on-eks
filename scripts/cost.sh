#!/usr/bin/env bash
# This month's AWS spend so far, by service (Cost Explorer). Billing data lags
# 8-24 hours. Each Cost Explorer request costs $0.01; this makes one.
#   make cost
#
# Shows usage before credits: an account with AWS credits (e.g. the free plan's
# sign-up credits) is billed $0, which says nothing about what the project costs.
# Also prints the last day Cost Explorer has data for: it can lag a day or two,
# and a missing day looks exactly like a free one.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

start="$(date +%Y-%m-01)"
end="$(date -v+1d +%Y-%m-%d 2>/dev/null || date -d tomorrow +%Y-%m-%d)" # macOS or GNU date
aws ce get-cost-and-usage --time-period Start="$start",End="$end" --granularity DAILY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE Type=DIMENSION,Key=RECORD_TYPE \
  --output json \
  | jq -r --arg start "$start" '
      def r2: . * 100 | round / 100;
      ([.ResultsByTime[] | select(.Groups | length > 0) | .TimePeriod.Start] | last // "no day yet") as $last
      | [.ResultsByTime[].Groups[]
        | {service: .Keys[0], type: .Keys[1], usd: (.Metrics.UnblendedCost.Amount | tonumber)}]
      | (map(select(.type != "Credit" and .type != "Refund"))) as $usage
      | (map(select(.type == "Credit" or .type == "Refund")) | map(.usd) | add // 0) as $credits
      | ($usage | map(.usd) | add // 0) as $total
      | ($usage | group_by(.service) | map({service: .[0].service, usd: (map(.usd) | add)})
          | map(select(.usd >= 0.005)) | sort_by(-.usd)
          | .[] | "  $\(.usd | r2)\t\(.service)"),
        "  ----",
        "  $\($total | r2)\tUsage before credits, \($start) to today",
        "  $\($credits | r2)\tCredits and refunds",
        "  $\(($total + $credits) | r2)\tBilled",
        "  (Cost Explorer has data through \($last); it can lag a day or two)"'
