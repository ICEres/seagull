variable "name_prefix" {
  type        = string
  description = "Prefix used for safety gateway resource names."
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to safety gateway resources."
  default     = {}
}

variable "deletion_protection_enabled" {
  type        = bool
  description = "Enable DynamoDB deletion protection for safety gateway tables."
  default     = true
}

variable "point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable DynamoDB point-in-time recovery for safety gateway tables."
  default     = true
}

variable "dynamodb_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN used for DynamoDB server-side encryption."
  default     = ""
}

variable "lambda_package_path" {
  type        = string
  description = "Path to the zipped safety gateway Lambda package."
}

variable "lambda_source_code_hash" {
  type        = string
  description = "Base64-encoded source hash for the safety gateway Lambda package."
}

variable "admin_secret_arn" {
  type        = string
  description = "Optional Secrets Manager ARN containing the Safety Gateway shared secret."
  default     = ""
}

variable "lambda_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN used for Lambda environment encryption."
  default     = ""
}

variable "api_throttling_burst_limit" {
  type        = number
  description = "Default API Gateway burst throttle for the Safety Gateway HTTP API."
  default     = 100
}

variable "api_throttling_rate_limit" {
  type        = number
  description = "Default API Gateway steady-state requests per second for the Safety Gateway HTTP API."
  default     = 50
}

variable "access_log_retention_days" {
  type        = number
  description = "Retention in days for Safety Gateway API Gateway access logs."
  default     = 30
}
