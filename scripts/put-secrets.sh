#!/usr/bin/env bash
# Store the app's secrets in SSM Parameter Store as SecureString.
#
# Deliberately NOT Terraform: even with ignore_changes, Terraform's refresh reads
# a managed parameter's decrypted value into the state file. Values set here
# never pass through Terraform. Rerun any time to rotate a value.
#
#   make secrets          # prompts for each value (input hidden)
#   make secrets-check    # lists which exist and when they changed; never values
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
PREFIX="/vibesense/secrets"

names=(youtube_api_key smtp_user smtp_pass)
prompts=(
  "YouTube Data API key"
  "Gmail address the reports are sent from"
  "Gmail app password (16 characters, spaces are fine)"
)

if [[ "${1:-}" == "--check" ]]; then
  aws ssm describe-parameters --region "$REGION" \
    --parameter-filters "Key=Path,Values=$PREFIX" \
    --query 'Parameters[].{name:Name,type:Type,changed:LastModifiedDate}' --output table
  exit 0
fi

# Values are handed to the AWS CLI through a private temp file (mode 600) that is
# deleted right after each write, never as a command-line argument, so they don't
# show up in `ps` or shell history.
umask 077
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

echo "Writing SecureString parameters under $PREFIX in $REGION."
echo "Press Enter on a prompt to leave that value unchanged."
echo

for i in "${!names[@]}"; do
  name="$PREFIX/${names[$i]}"
  read -rsp "${prompts[$i]}: " value
  echo
  if [[ -z "$value" ]]; then
    echo "  skipped $name"
    continue
  fi

  printf '%s' "$value" >"$tmp"   # no trailing newline
  aws ssm put-parameter --region "$REGION" --name "$name" --type SecureString \
    --overwrite --value "file://$tmp" >/dev/null
  : >"$tmp"                      # empty it straight away

  # put-parameter can't tag while overwriting, so tag separately.
  aws ssm add-tags-to-resource --region "$REGION" \
    --resource-type Parameter --resource-id "$name" \
    --tags Key=Project,Value=vibesense Key=ManagedBy,Value=scripts/put-secrets.sh
  echo "  stored  $name"
  unset value
done
