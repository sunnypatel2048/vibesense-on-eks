# ADR-0005: Public subnets with no NAT gateway

**Status:** Accepted

## Context

Nodes need outbound internet (ECR, the YouTube API, Gmail SMTP). The standard answer, private subnets behind a NAT gateway, costs about $33 a month idle, more than everything else in a session combined.

## Decision

Nodes and the ALB live in two public /20 subnets and get public IPv4 addresses; RDS lives in two database subnets with no internet route. Security groups admit the ALB to the UI pods and nothing else from outside; the EKS API endpoint is public but limited to the admin's IP, with a private endpoint for nodes.

## Consequences

- Saves the NAT gateway; public IPv4 addresses cost $0.005/hour each instead.
- Nodes are reachable only where security groups allow, but defence in depth is thinner than private subnets.
- The README's "What production would change" lists private subnets with NAT or VPC endpoints.

## Alternatives considered

Private subnets + NAT gateway (the production default); private subnets + VPC endpoints only (no route to YouTube or Gmail without NAT anyway).
