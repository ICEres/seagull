variable "name_prefix" {
  type        = string
  description = "Prefix used for message router resource names."
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to message router resources."
  default     = {}
}

variable "deletion_protection_enabled" {
  type        = bool
  description = "Enable DynamoDB deletion protection for message router tables."
  default     = true
}

variable "point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable DynamoDB point-in-time recovery for message router tables."
  default     = true
}

variable "dynamodb_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN used for DynamoDB server-side encryption."
  default     = ""
}

variable "api_throttling_burst_limit" {
  type        = number
  description = "Default API Gateway burst throttle for the message router WebSocket API."
  default     = 100
}

variable "api_throttling_rate_limit" {
  type        = number
  description = "Default API Gateway steady-state messages per second for the message router WebSocket API."
  default     = 50
}

variable "access_log_retention_days" {
  type        = number
  description = "Retention in days for message router API Gateway access logs."
  default     = 30
}

variable "lambda_package_path" {
  type        = string
  description = "Path to the zipped message router Lambda package."
}

variable "lambda_source_code_hash" {
  type        = string
  description = "Base64-encoded source hash for the message router Lambda package."
}

variable "agent_tokens_table_name" {
  type        = string
  description = "Message Hub agent token table name used to authenticate WebSocket connections."
}

variable "agent_tokens_table_arn" {
  type        = string
  description = "Message Hub agent token table ARN used to authenticate WebSocket connections."
}

variable "deliveries_table_name" {
  description = <<-EOT
    Name of the hub deliveries table. $connect replays an agent's unacked
    backlog from it, so a reconnect resumes from durable state instead of the
    agent having to ask for its own backlog.

    Empty disables the replay: $connect still authenticates and registers the
    connection, it just returns resumed_count 0.
  EOT
  type        = string
  default     = ""
}

variable "deliveries_table_arn" {
  description = "ARN of the hub deliveries table, joined read-only to the router's grant. Empty leaves the grant unchanged."
  type        = string
  default     = ""
}
