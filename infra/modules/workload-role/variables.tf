variable "name" {
  description = "IAM role name."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster the Pod Identity association belongs to."
  type        = string
}

variable "cluster_arn" {
  description = "EKS cluster ARN; the trust policy accepts only this cluster."
  type        = string
}

variable "namespace" {
  description = "Kubernetes namespace of the ServiceAccount."
  type        = string
}

variable "service_account" {
  description = "Kubernetes ServiceAccount whose pods get this role."
  type        = string
}

variable "policy_json" {
  description = "The role's permissions, as an IAM policy document (JSON)."
  type        = string
}
