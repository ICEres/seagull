variable "name_prefix" {
  type        = string
  description = "Prefix used for AI provider resource names."
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to AI provider resources."
  default     = {}
}

variable "deletion_protection_enabled" {
  type        = bool
  description = "Enable DynamoDB deletion protection for AI provider tables."
  default     = true
}

variable "point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable DynamoDB point-in-time recovery for AI provider tables."
  default     = true
}

variable "dynamodb_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN used for DynamoDB server-side encryption."
  default     = ""
}

variable "lambda_package_path" {
  type        = string
  description = "Path to the zipped AI provider Lambda package."
}

variable "lambda_source_code_hash" {
  type        = string
  description = "Base64-encoded source hash for the AI provider Lambda package."
}

variable "admin_secret_arn" {
  type        = string
  description = "Optional Secrets Manager ARN containing the AI provider admin secret."
  default     = ""
}

variable "lambda_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN used to encrypt Lambda environment variables."
  default     = ""
}

variable "jwt_issuer" {
  type        = string
  description = "OIDC issuer URL accepted by the AI Provider JWT authorizer."
}

variable "jwt_audience" {
  type        = list(string)
  description = "JWT audiences accepted by the AI Provider JWT authorizer."
}

variable "api_throttling_burst_limit" {
  type        = number
  description = "Default API Gateway burst throttle for the AI Provider HTTP API."
  default     = 100
}

variable "api_throttling_rate_limit" {
  type        = number
  description = "Default API Gateway steady-state requests per second for the AI Provider HTTP API."
  default     = 50
}

variable "message_hub_api_url" {
  type        = string
  description = "Optional Message Hub API URL used by the AI Provider worker for task-result callbacks."
  default     = ""
}

variable "worker_timeout_seconds" {
  type        = number
  description = "AI Provider worker Lambda timeout in seconds."
  default     = 60
}

variable "worker_batch_size" {
  type        = number
  description = "Maximum SQS messages delivered to each AI Provider worker invocation."
  default     = 1
}

variable "access_log_retention_days" {
  type        = number
  description = "Retention in days for AI Provider API Gateway access logs."
  default     = 30
}
