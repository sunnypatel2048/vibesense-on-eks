# Karpenter's AWS side, from the EKS module's karpenter sub-module:
#   - the controller's IAM role, bound to kube-system/karpenter by Pod Identity
#   - the IAM role for the nodes it launches, with an EKS access entry
#   - an SQS queue + EventBridge rules for Spot interruption warnings, so
#     Karpenter drains a node during its 2-minute notice instead of losing it
# The controller itself is installed by Argo CD (deploy/apps/karpenter.yaml);
# its NodePool and EC2NodeClass live in deploy/cluster-config/.

module "karpenter" {
  #checkov:skip=CKV_TF_1:Exact registry version pinned; upgrades are reviewed PRs (see docs/security.md)
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "21.29.0" # same release as the EKS module

  cluster_name = module.eks.cluster_name

  # Controller: Pod Identity, like every other workload (ADR 9).
  namespace                       = "kube-system"
  service_account                 = "karpenter"
  create_pod_identity_association = true
  iam_role_name                   = "${var.project}-karpenter-controller"
  iam_role_use_name_prefix        = false

  # Nodes: a fixed name, because the EC2NodeClass refers to it from Git.
  node_iam_role_name            = "${var.project}-karpenter-node"
  node_iam_role_use_name_prefix = false
  create_access_entry           = true # lets the nodes join the cluster

  # Spot interruption handling.
  enable_spot_termination = true
  queue_name              = "${var.project}-karpenter"
}
