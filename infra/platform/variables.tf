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
