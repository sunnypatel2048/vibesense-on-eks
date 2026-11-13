# Two-AZ VPC with no NAT gateway (ADR 5): nodes and the ALB sit in public
# subnets, RDS in subnets with no internet route.

module "vpc" {
  #checkov:skip=CKV_TF_1:Exact registry version pinned; upgrades are reviewed PRs. A commit-hash Git source would lose readable versions and automated update PRs.
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3" # exact: .terraform.lock.hcl pins providers, not modules

  name = var.project
  cidr = var.vpc_cidr
  azs  = var.availability_zone_ids # zone IDs; the module accepts them directly

  # /20s (4,096 addresses each): every pod gets a VPC IP, so these fill up fast.
  public_subnets = [for i in range(2) : cidrsubnet(var.vpc_cidr, 4, i)] # 10.0.0.0/20, 10.0.16.0/20

  # RDS only; no internet route. The module also creates the DB subnet group.
  database_subnets                       = [for i in range(2) : cidrsubnet(var.vpc_cidr, 8, 200 + i)] # 10.0.200.0/24, 10.0.201.0/24
  create_database_subnet_group           = true
  create_database_internet_gateway_route = false

  # No NAT gateway: ~$33/month idle. Nodes get public IPs instead, and security
  # groups admit only the load balancer (ADR 5). Production would use private
  # subnets with NAT or VPC endpoints.
  enable_nat_gateway      = false
  map_public_ip_on_launch = true

  enable_dns_hostnames = true
  enable_dns_support   = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"         # AWS Load Balancer Controller puts the ALB here (Phase 5)
    "karpenter.sh/discovery" = var.project # Karpenter launches nodes here (Phase 8)
  }
}
