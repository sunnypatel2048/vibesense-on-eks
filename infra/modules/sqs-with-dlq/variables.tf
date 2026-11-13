variable "name" {
  description = "Queue name. The DLQ is named \"<name>-dlq\"."
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "How long a received message stays hidden. Match the consumer's longest legitimate processing time."
  type        = number

  validation {
    condition     = var.visibility_timeout_seconds >= 0 && var.visibility_timeout_seconds <= 43200
    error_message = "SQS allows 0 to 43200 seconds."
  }
}

variable "max_receive_count" {
  description = "Failed receives before a message moves to the DLQ."
  type        = number
  default     = 5
}

variable "message_retention_seconds" {
  description = "How long the main queue keeps a message (default 4 days)."
  type        = number
  default     = 345600
}

variable "alarm_topic_arn" {
  description = "SNS topic notified when the DLQ has messages, and again when it's empty."
  type        = string
}
