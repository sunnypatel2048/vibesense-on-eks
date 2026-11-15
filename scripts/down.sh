#!/usr/bin/env bash
# Tear everything down to zero cost, in the order that leaves nothing behind,
# then prove it with scripts/leftovers.sh.
#
#   make down
#
# Each step removes something the cluster created that Terraform can't see:
#   1. root app      stop Argo CD self-heal, or it recreates what we delete next
#   2. the app       its Ingress, and with it the ALB and its security groups
#   3. Karpenter     its nodes and the instance profile it made for them
#   4. cluster       Terraform destroys EKS first, then (5) stray network
#                    interfaces are removed, then (6) Terraform destroys the rest
#
# Safe to rerun after a partial failure: steps that find nothing skip ahead.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

aws sts get-caller-identity >/dev/null || fail "No AWS credentials."

if cluster_exists; then
  aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER" >/dev/null
  if kubectl get --raw /healthz >/dev/null 2>&1; then

    step "1/6 Stop Argo CD self-heal (delete the root app, not its children)"
    kubectl -n argocd delete application root --ignore-not-found --wait=false
    # Root has no cascade finalizer, so its child apps (and what they run) stay.

    step "2/6 Delete the app, and with it the ALB"
    kubectl -n argocd delete applicationset vibesense --ignore-not-found --timeout=10m \
      || note "still deleting after 10 minutes; continuing (leftovers.sh will report what's left)"
    if kubectl -n vibesense get ingress ui >/dev/null 2>&1; then
      # The load balancer controller removes the Ingress only after deleting the ALB.
      kubectl -n vibesense wait --for=delete ingress/ui --timeout=5m && note "ALB deleted"
    else
      note "no Ingress, so no ALB"
    fi

    step "3/6 Remove Karpenter's nodes and instance profile"
    kubectl -n argocd delete application cluster-config --ignore-not-found --timeout=10m \
      || note "still deleting after 10 minutes; continuing"
    kubectl wait --for=delete nodeclaims --all --timeout=5m 2>/dev/null || true
    kubectl wait --for=delete ec2nodeclasses --all --timeout=5m 2>/dev/null || true
    note "nodeclaims left: $(kubectl get nodeclaims -o name 2>/dev/null | wc -l | tr -d ' ')"

    # Nothing here uses persistent volumes (Prometheus uses emptyDir), but if
    # anything ever does, its EBS volume would outlive the cluster.
    if [[ -n "$(kubectl get pvc -A -o name 2>/dev/null)" ]]; then
      kubectl delete pvc --all -A --wait=true --timeout=5m
    fi
  else
    note "The cluster exists but kubectl can't reach it (is your IP in admin_cidrs?). Skipping steps 1-3; leftovers.sh will show anything they would have removed."
  fi
else
  note "No EKS cluster: skipping the Kubernetes steps."
fi

# Belt and braces: wait for anything the load balancer controller or Karpenter
# made to actually be gone from AWS, not just from Kubernetes.
lb_gone() { [[ -z "$(aws resourcegroupstaggingapi get-resources --region "$REGION" --tag-filters Key=elbv2.k8s.aws/cluster,Values=$CLUSTER --resource-type-filters elasticloadbalancing:loadbalancer --query 'ResourceTagMappingList[].ResourceARN' --output text)" ]]; }
nodes_gone() { [[ -z "$(aws ec2 describe-instances --region "$REGION" --filters Name=tag:karpenter.sh/nodepool,Values=burst Name=instance-state-name,Values=pending,running,stopping --query 'Reservations[].Instances[].InstanceId' --output text)" ]]; }
wait_for 300 "the ALB to be deleted" lb_gone || true
wait_for 300 "Karpenter's instances to terminate" nodes_gone || true

step "4/6 Terraform: destroy the cluster and everything attached to it"
"${TF_PLATFORM[@]}" init -input=false -backend-config=../bootstrap/backend.hcl >/dev/null
# -target on purpose: once the nodes are gone, step 5 can clean up what they
# left behind before Terraform tries to delete the VPC.
"${TF_PLATFORM[@]}" destroy -auto-approve -input=false -target=module.eks -target=module.karpenter

step "5/6 Remove network interfaces the VPC CNI left behind"
vpc="$(aws ec2 describe-vpcs --region "$REGION" --filters Name=tag:Name,Values=$CLUSTER --query 'Vpcs[0].VpcId' --output text)"
if [[ "$vpc" != "None" ]]; then
  # "aws-K8S-*" interfaces are created by the CNI for pod IPs; "available" means
  # nothing is attached. With the nodes gone these are always strays, and any
  # one of them blocks deleting the subnets.
  for eni in $(aws ec2 describe-network-interfaces --region "$REGION" \
      --filters Name=vpc-id,Values="$vpc" Name=status,Values=available Name=description,Values='aws-K8S-*' \
      --query 'NetworkInterfaces[].NetworkInterfaceId' --output text); do
    aws ec2 delete-network-interface --region "$REGION" --network-interface-id "$eni" && note "deleted stray $eni"
  done
  # Security groups the load balancer controller made, if step 2 couldn't run.
  for sg in $(aws ec2 describe-security-groups --region "$REGION" --filters Name=vpc-id,Values="$vpc" \
      --query "SecurityGroups[?starts_with(GroupName, 'k8s-')].GroupId" --output text); do
    aws ec2 delete-security-group --region "$REGION" --group-id "$sg" && note "deleted $sg" || true
  done
else
  note "no VPC"
fi

step "6/6 Terraform: destroy the rest (VPC, RDS, queues, roles, ...)"
"${TF_PLATFORM[@]}" destroy -auto-approve -input=false

step "Checking for leftovers"
if "$ROOT/scripts/leftovers.sh"; then
  printf '\n================ make down: done in %s, nothing left ================\n' "$(elapsed)"
else
  fail "make down finished in $(elapsed), but leftovers.sh found the resources above."
fi
