#!/usr/bin/env bash
# Follow one job through every stage of the pipeline, from its logs.
#
#   scripts/trace-job.sh <job_id>                # from the running pods (last 2 h; SINCE=30m to change)
#   scripts/trace-job.sh <job_id> --cloudwatch   # from CloudWatch Logs, which keeps
#                                                # logs of pods KEDA has since removed
#   (or: make trace JOB=<job_id> [SOURCE=cloudwatch])
#
# Every service logs one JSON object per line, with job_id attached to every
# line written while a message is handled (src/common/logs.py). This keeps that
# job's lines and prints them in time order: ingestion → ai → aggregation →
# notification.
set -euo pipefail

job="${1:?usage: scripts/trace-job.sh <job_id> [--cloudwatch]}"
source="${2:-}"
LOG_GROUP=/aws/eks/vibesense/containers

# time, service, level, event, then any other fields as key=value.
fmt='[.timestamp, .service, .level, .event,
      (del(.timestamp, .service, .level, .event, .job_id, .kubernetes, .stream, .time, .log, ._p)
       | to_entries | map("\(.key)=\(.value | tostring)") | join(" "))] | @tsv'

if [[ "$source" == "--cloudwatch" ]]; then
  aws logs filter-log-events --log-group-name "$LOG_GROUP" \
    --filter-pattern "{ \$.job_id = \"$job\" }" \
    --start-time $(( ($(date +%s) - 86400) * 1000 )) \
    --query 'events[].message' --output json \
    | jq -c '.[] | fromjson' | jq -rs "sort_by(.timestamp)[] | $fmt"
else
  kubectl -n vibesense logs -l app.kubernetes.io/name=vibesense --tail=-1 --since="${SINCE:-2h}" --max-log-requests=30 \
    | jq -cR 'fromjson? // empty' \
    | jq -rs --arg id "$job" "map(select(.job_id == \$id)) | sort_by(.timestamp)[] | $fmt"
fi | column -t -s $'\t'
