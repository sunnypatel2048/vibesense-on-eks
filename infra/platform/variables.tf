variable "region" {
  description = "AWS region for everything in this project."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix and Project tag for all resources."
  type        = string
  default     = "vibesense"
}

variable "vpc_cidr" {
  description = "Address range for the VPC. Pods get real VPC IPs (VPC CNI), so keep it roomy."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zone_ids" {
  description = <<-EOT
    Exactly two zone IDs. IDs (use1-az1), not names (us-east-1a): an ID is the
    same physical zone in every account, and an explicit list can't shift when
    AWS adds a zone (which would recreate the subnets). EKS doesn't support use1-az3.
  EOT
  type        = list(string)
  default     = ["use1-az1", "use1-az2"]

  validation {
    condition     = length(var.availability_zone_ids) == 2 && !contains(var.availability_zone_ids, "use1-az3")
    error_message = "Give exactly two zone IDs, not including use1-az3 (unsupported by EKS)."
  }
}

variable "kubernetes_version" {
  description = "EKS version. Use the newest in standard support: older ones auto-enroll in extended support at 6x the price."
  type        = string
  default     = "1.37"
}

variable "admin_cidrs" {
  description = "CIDRs allowed to reach the public EKS API (your IP as x.x.x.x/32). Set in terraform.tfvars (gitignored)."
  type        = list(string)

  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for c in var.admin_cidrs : can(cidrhost(c, 0)) && c != "0.0.0.0/0"])
    error_message = "Give at least one valid CIDR, and never 0.0.0.0/0."
  }
}
