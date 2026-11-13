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

variable "github_repository" {
  description = "owner/name of the GitHub repository whose workflows may assume the CI roles."
  type        = string
  default     = "sunnypatel2048/vibesense-on-eks"
}

variable "alerts_email" {
  description = "Email for alarm and budget notifications. Set in terraform.tfvars (gitignored)."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alerts_email))
    error_message = "alerts_email must be an email address."
  }
}
