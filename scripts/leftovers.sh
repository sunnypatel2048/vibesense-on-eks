#!/usr/bin/env bash
# List anything from the platform layer that still exists after `make down`,
# especially anything that costs money. Exits 1 if it finds something.
#
#   scripts/leftovers.sh      (also run at the end of make down, and nightly in CI)
#
# Persistent resources (the bootstrap layer: state bucket, ECR, CI roles, SNS,
# budgets; and the app secrets in SSM) are expected and not reported.
# Read-only: works with the CI plan role.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

found=0
check() { # check <label> <command printing one item per word/line, or nothing>
  local label=$1; shift
  local out
  out="$("$@" 2>/dev/null | tr '\t' '\n' | grep -v -e '^None$' -e '^$' || true)"
  if [[ -n "$out" ]]; then
    printf '  FOUND  %-28s %s\n' "$label" "$(echo "$out" | paste -sd ' ' -)"
    found=1
  else
    printf '  ok     %s\n' "$label"
  fi
}

check "EKS cluster"               aws eks list-clusters --region "$REGION" --query "clusters[?@=='$CLUSTER']" --output text
check "EC2 instances"             aws ec2 describe-instances --region "$REGION" --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER,karpenter.sh/nodepool,eks:cluster-name" Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' --output text
check "Load balancers"            aws elbv2 describe-load-balancers --region "$REGION" --query "LoadBalancers[?starts_with(LoadBalancerName, 'k8s-vibesens')].LoadBalancerName" --output text
check "Target groups"             aws elbv2 describe-target-groups --region "$REGION" --query "TargetGroups[?starts_with(TargetGroupName, 'k8s-vibesens')].TargetGroupName" --output text
check "RDS instance"              aws rds describe-db-instances --region "$REGION" --query "DBInstances[?starts_with(DBInstanceIdentifier, 'vibesense')].DBInstanceIdentifier" --output text
check "RDS-managed secret"        aws secretsmanager list-secrets --region "$REGION" --query "SecretList[?starts_with(Name, 'rds!')].Name" --output text
check "VPC"                       aws ec2 describe-vpcs --region "$REGION" --filters "Name=tag:Name,Values=$CLUSTER" --query 'Vpcs[].VpcId' --output text
check "Unattached EBS volumes"    aws ec2 describe-volumes --region "$REGION" --filters Name=status,Values=available --query 'Volumes[].VolumeId' --output text
check "Unattached Elastic IPs"    aws ec2 describe-addresses --region "$REGION" --query 'Addresses[?AssociationId==null].PublicIp' --output text
check "SQS queues"                aws sqs list-queues --region "$REGION" --queue-name-prefix vibesense- --query 'QueueUrls' --output text
check "Scheduler schedules/group" aws scheduler list-schedule-groups --region "$REGION" --name-prefix vibesense --query 'ScheduleGroups[].Name' --output text
check "CloudWatch log groups"     aws logs describe-log-groups --region "$REGION" --log-group-name-prefix /aws/eks/vibesense --query 'logGroups[].logGroupName' --output text
check "CloudWatch alarms"         aws cloudwatch describe-alarms --region "$REGION" --alarm-name-prefix vibesense- --query 'MetricAlarms[].AlarmName' --output text
check "Platform SSM parameters"   aws ssm describe-parameters --region "$REGION" --parameter-filters Key=Path,Values=/vibesense/platform --query 'Parameters[].Name' --output text
check "Karpenter instance profiles" aws iam list-instance-profiles --query "InstanceProfiles[?Roles[?RoleName=='vibesense-karpenter-node'] || starts_with(InstanceProfileName, 'vibesense_')].InstanceProfileName" --output text
check "Platform IAM roles"        aws iam list-roles --query "Roles[?starts_with(RoleName, 'vibesense-') && !contains(RoleName, 'vibesense-ci-')].RoleName" --output text

if (( found )); then
  printf '\nLeftovers found (above).\n'
  exit 1
fi
printf '\nNo leftovers.\n'
