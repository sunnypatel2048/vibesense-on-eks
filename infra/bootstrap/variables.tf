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

# Public, not secret: `gh api users/<owner> --jq .id` and
# `gh api repos/<owner>/<repo> --jq .id`. Part of GitHub's OIDC subject claim.
variable "github_owner_id" {
  description = "Numeric ID of the repository owner's GitHub account."
  type        = string
  default     = "73701502"

  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "A numeric GitHub user ID."
  }
}

variable "github_repository_id" {
  description = "Numeric ID of the GitHub repository."
  type        = string
  default     = "1433402447"

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "A numeric GitHub repository ID."
  }
}

variable "alerts_email" {
  description = "Email for alarm and budget notifications. Set in terraform.tfvars (gitignored)."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alerts_email))
    error_message = "alerts_email must be an email address."
  }
}
