# Container logs of the vibesense namespace, shipped by Fluent Bit (
# deploy/apps/fluent-bit.yaml). In the platform layer, so `make down` deletes
# them with everything else.
#
# Why ship them at all: KEDA removes worker pods when queues drain, and a
# removed pod's logs go with it. CloudWatch keeps them, searchable by job_id
# (scripts/trace-job.sh --cloudwatch, or Logs Insights).

resource "aws_cloudwatch_log_group" "containers" {
  #checkov:skip=CKV_AWS_158:Encrypted at rest by CloudWatch already; a customer-managed key would be created and scheduled for deletion on every make up/down
  #checkov:skip=CKV_AWS_338:Demo logs; one day is enough to debug a session, and the group is deleted on make down anyway
  name              = "/aws/eks/${var.project}/containers"
  retention_in_days = 1
}

data "aws_iam_policy_document" "fluent_bit" {
  statement {
    sid = "WriteContainerLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    # This log group and its streams only. No CreateLogGroup: Terraform owns it.
    resources = [
      aws_cloudwatch_log_group.containers.arn,
      "${aws_cloudwatch_log_group.containers.arn}:*",
    ]
  }
}

module "fluent_bit_role" {
  source = "../modules/workload-role"

  name            = "${var.project}-fluent-bit"
  cluster_name    = module.eks.cluster_name
  cluster_arn     = module.eks.cluster_arn
  namespace       = "logging"
  service_account = "fluent-bit"
  policy_json     = data.aws_iam_policy_document.fluent_bit.json
}
