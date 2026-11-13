# EKS cluster and its system node group.

module "eks" {
  #checkov:skip=CKV_TF_1:Exact registry version pinned; upgrades are reviewed PRs (see docs/security.md)
  source  = "terraform-aws-modules/eks/aws"
  version = "21.29.0" # exact: .terraform.lock.hcl pins providers, not modules

  name               = var.project
  kubernetes_version = var.kubernetes_version

  # By default EKS moves an aging version into extended support ($0.60/hr
  # instead of $0.10). STANDARD makes it upgrade the version instead.
  upgrade_policy = {
    support_type = "STANDARD"
  }

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets

  # kubectl from your IP only. The private endpoint is required: with public
  # access restricted, nodes join the cluster through it.
  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.admin_cidrs
  endpoint_private_access      = true

  # Access entries (not the aws-auth ConfigMap). Whoever runs apply gets
  # cluster admin; CI never applies.
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = true

  # Pods get AWS credentials through EKS Pod Identity (ADR 9), so the module's
  # default IRSA setup (a per-cluster OIDC provider) isn't needed.
  enable_irsa = false

  # No control-plane logs: billed per GB, and the log group outlives the
  # cluster. Production would enable at least "audit".
  enabled_log_types           = []
  create_cloudwatch_log_group = false

  # EKS envelope-encrypts all Kubernetes API data by default (AWS-owned key).
  # A customer-managed key would be created on every `make up` and linger 7+
  # days after each destroy.
  create_kms_key    = false
  encryption_config = null

  addons = {
    # Before the nodes, so they start fully networked. Network policy
    # enforcement is used in Task 6.5.
    vpc-cni = {
      before_compute       = true
      configuration_values = jsonencode({ enableNetworkPolicy = "true" })
    }
    # Hands pods their IAM credentials (EKS Pod Identity, Task 4.7).
    eks-pod-identity-agent = {
      before_compute = true
    }
    coredns    = {}
    kube-proxy = {}
  }

  eks_managed_node_groups = {
    # Hosts Argo CD, the controllers and Karpenter. Karpenter adds burst
    # capacity in Phase 8.
    system = {
      ami_type      = "AL2023_ARM_64_STANDARD"
      capacity_type = "SPOT"
      # Three types: Spot capacity rarely runs out for all of them at once.
      instance_types = ["t4g.large", "m6g.large", "m7g.large"]

      min_size     = 2
      desired_size = 2
      max_size     = 3

      labels = {
        "vibesense/node-role" = "system"
      }
    }
  }
}
