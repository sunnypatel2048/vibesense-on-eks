# Cluster session runbook (Phase 8)

One sitting, about 90 minutes at ~$0.20/hour, that tests everything built since
the last session and measures it for the README:

| Part | Tests | Task |
| --- | --- | --- |
| A | Platform up, all 9 Argo CD apps healthy, timed | 5.6 |
| B | Network policies block worker ports | 6.5 |
| C | A merged one-line change reaches the cluster with no `kubectl` | Phase 7 |
| D | Load test: KEDA scales the AI worker 0 → 6, Karpenter adds a node, both scale back | 8.4 |
| E | Drain a burst node mid-load: pods move, no message lost | 8.5 |
| F | Teardown in the order that leaves nothing behind | 10.2 |

Write down every number marked **Record**. Phase 10's `make up` / `make down`
will replace parts A and F.

## Before you start

```bash
cd ~/Projects/vibesense-on-eks && git switch main && git pull
aws ec2 describe-vpcs --filters Name=tag:Name,Values=vibesense --query 'Vpcs[].VpcId' --output text   # empty
```

Start Part C's pull request now: CI takes ~10 minutes and can run while the
cluster comes up.

```bash
git switch -c chore/rollout-test
echo "# Rollout test $(date +%F): a merged change reaches the cluster with no kubectl." >> src/ui_service/app.py
git commit -am "Rollout test: one-line change to measure merge-to-Ready"
git push -u origin chore/rollout-test && gh pr create --fill
git switch main
```

Don't merge it yet.

## A. Platform up

```bash
cd infra/platform && time terraform apply && cd ../..
aws eks update-kubeconfig --name vibesense --region us-east-1
kubectl get nodes          # 2 Ready (the system nodes)
make secrets-check
```
**Record:** apply time.

```bash
start=$(date +%s)
make argocd
until kubectl -n argocd get applications -o json | jq -e '(.items | length) == 9 and all(.items[]; .status.health.status == "Healthy" and .status.sync.status == "Synced")' >/dev/null 2>&1; do sleep 5; done
echo "bootstrap → all healthy: $(( $(date +%s) - start ))s"
kubectl -n argocd get applications
```
**Record:** bootstrap-to-healthy seconds. The 9 apps: root, metrics-server,
cert-manager, external-secrets, keda, aws-load-balancer-controller, karpenter,
cluster-config, vibesense. If the loop runs past ~10 minutes, Ctrl-C and look
at which app isn't Healthy.

```bash
kubectl -n vibesense get pods,scaledobjects
kubectl get nodepools,ec2nodeclasses
```
Expected: ui, ingestion, aggregation, notification Running; **no ai pod** (KEDA
scaled it to zero); 4 ScaledObjects `READY True`; nodepool `burst` and
ec2nodeclass `default` `READY True`.

```bash
ADDR=$(kubectl -n vibesense get ingress ui -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
until [ "$(curl -s -o /dev/null -w '%{http_code}' "http://$ADDR/_stcore/health")" = 200 ]; do sleep 10; done; echo "UI: http://$ADDR"
```

## B. Network policies (Task 6.5)

```bash
kubectl -n vibesense get networkpolicies      # 3
IP=$(kubectl -n vibesense get pod -l app.kubernetes.io/component=ingestion -o jsonpath='{.items[0].status.podIP}')
kubectl -n vibesense run np-test --rm -i --image=curlimages/curl --restart=Never -- \
  curl -s -m 5 "http://$IP:9000/healthz" || echo "BLOCKED (expected)"
kubectl -n vibesense get pods                 # all still Ready: probes aren't blocked
```
Pass: `BLOCKED (expected)`, and the UI still loads at `http://$ADDR`.

## C. Merge to rollout, no kubectl (Phase 7 "done when")

When the PR's checks are green:

```bash
OLD=$(kubectl -n vibesense get deploy ui -o jsonpath='{.spec.template.spec.containers[0].image}' | sed 's/.*://')
gh pr merge chore/rollout-test --merge --delete-branch; t0=$(date +%s); echo "merged at $(date +%T)"
until NEW=$(kubectl -n vibesense get deploy ui -o jsonpath='{.spec.template.spec.containers[0].image}' | sed 's/.*://'); [ "$NEW" != "$OLD" ]; do sleep 10; done
kubectl -n vibesense rollout status deploy/ui
echo "merge → new pods Ready: $(( $(date +%s) - t0 ))s  ($OLD → $NEW)"
git pull
```
**Record:** merge-to-Ready seconds. It's mostly the release build; Argo CD
picks up the bot's commit within 60 s.

## D. Autoscaling under load (Task 8.4)

Three terminals, side by side, each printing timestamps:

```bash
# Terminal 1: AI pods
kubectl -n vibesense get pods -l app.kubernetes.io/component=ai -w | while read -r l; do echo "$(date +%T) $l"; done

# Terminal 2: Karpenter's nodes
kubectl get nodeclaims -w | while read -r l; do echo "$(date +%T) $l"; done

# Terminal 3: queue depth (visible, in flight) every 10 s
Q=$(aws sqs get-queue-url --queue-name vibesense-analysis --query QueueUrl --output text)
while true; do echo "$(date +%T) $(aws sqs get-queue-attributes --queue-url "$Q" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query 'Attributes.[ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible]' --output text)"; sleep 10; done
```

Then, in a fourth terminal:

```bash
make load JOBS=20 MESSAGES=200
```

What should happen, and what to **record** (times from the timestamps):

1. Messages land in the queue → KEDA sees them within ~10 s and creates AI pods
   (Pending: nothing can host them yet).
2. Karpenter creates a NodeClaim → a Graviton Spot node joins.
   **Record:** NodeClaim created → node Ready, and the instance type it chose
   (`kubectl get nodes -L node.kubernetes.io/instance-type,karpenter.sh/capacity-type`).
3. AI pods pull the image and start. **Record:** first message sent → first AI
   pod Ready (scale-from-zero cold start).
4. Pods scale toward 6 while the queue drains. **Record:** max AI pods, and
   time to drain 200 messages (queue back to `0 0`).
5. ~2 minutes after the queue empties, AI pods go to 0. About a minute later
   Karpenter removes the node. **Record:** queue empty → node gone.

Check that nothing was lost:

```bash
kubectl -n vibesense logs -l app.kubernetes.io/component=notification --tail=-1 --since=30m | grep -c email_suppressed   # 200
for q in analysis aggregation notification; do
  echo "$q DLQ: $(aws sqs get-queue-attributes --queue-url "$(aws sqs get-queue-url --queue-name vibesense-$q-dlq --query QueueUrl --output text)" --attribute-names ApproximateNumberOfMessages --query Attributes.ApproximateNumberOfMessages --output text)"
done   # all 0
kubectl top pods -n vibesense   # while it's running, if you catch it: AI memory under load
```

## E. Spot drill: drain a node mid-load (Task 8.5)

```bash
make load JOBS=10 MESSAGES=200
# Once at least 2 AI pods are Running on a burst node:
NODE=$(kubectl get nodes -l vibesense/node-role=burst -o jsonpath='{.items[0].metadata.name}')
kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data
```

Watch terminals 1 and 2: the evicted pods go Pending, Karpenter launches a
replacement node, the pods start there. On SIGTERM each worker hands its
unfinished messages back to SQS, so they're redelivered, and any duplicate is
absorbed by the idempotent writes from Task 1.6.

Pass: the notification count reaches **400** in total (200 from D + 200 from
E: run the `grep -c` again with `--since=60m`), and all three DLQs stay at 0.
**Record:** drain → replacement node Ready.

Then remove the synthetic jobs: `make load-clean`.

## F. Teardown, in this order

Each step removes something the cluster created that Terraform can't see.

```bash
# 1. Stop self-heal: deleting root (no cascade finalizer) leaves the apps running
kubectl -n argocd delete application root

# 2. The app, and with it the Ingress, and with it the ALB
kubectl -n argocd delete applicationset vibesense
kubectl -n vibesense wait --for=delete ingress/ui --timeout=5m && echo "ALB gone"

# 3. Karpenter's NodePool and EC2NodeClass: it drains and terminates its nodes,
#    then deletes the instance profile it made (which would block deleting the
#    node role)
kubectl -n argocd delete application cluster-config
kubectl wait --for=delete nodeclaims --all --timeout=5m
kubectl wait --for=delete ec2nodeclasses --all --timeout=5m && echo "Karpenter nodes and instance profile gone"

# 4. Nothing the cluster created may remain (both must print nothing)
aws resourcegroupstaggingapi get-resources --tag-filters Key=elbv2.k8s.aws/cluster,Values=vibesense --query 'ResourceTagMappingList[].ResourceARN' --output text
aws ec2 describe-instances --filters Name=tag:karpenter.sh/nodepool,Values=burst Name=instance-state-name,Values=pending,running --query 'Reservations[].Instances[].InstanceId' --output text

# 5. Now Terraform
cd infra/platform && time terraform destroy && cd ../..
```
**Record:** destroy time.

## Results to send back

- [ ] apply time, bootstrap seconds
- [ ] network policy: blocked?
- [ ] merge → Ready seconds
- [ ] node join time and instance type
- [ ] cold start (first message → first AI pod Ready)
- [ ] max AI pods, 200-message drain time
- [ ] queue empty → node removed
- [ ] email_suppressed counts (200, then 400), DLQs 0
- [ ] drain → replacement node Ready
- [ ] destroy time
