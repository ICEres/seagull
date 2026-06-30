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
