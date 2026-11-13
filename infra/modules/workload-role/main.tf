# An IAM role for one Kubernetes workload, granted through EKS Pod Identity:
# pods using <namespace>/<service_account> get this role's credentials.

data "aws_caller_identity" "current" {}

# Pod Identity assumes the role on the pod's behalf. The conditions stop the
# "confused deputy": only this account's cluster can use the role.
data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [var.cluster_arn]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.name
  description        = "Pod Identity: ${var.namespace}/${var.service_account}"
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

resource "aws_iam_role_policy" "this" {
  name   = "workload"
  role   = aws_iam_role.this.id
  policy = var.policy_json
}

resource "aws_eks_pod_identity_association" "this" {
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = var.service_account
  role_arn        = aws_iam_role.this.arn
}
