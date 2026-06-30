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

variable "admin_secret" {
  type        = string
  description = "Optional AI provider admin secret. Leave empty to require JWT admin claims."
  sensitive   = true
}

variable "jwt_issuer" {
  type        = string
  description = "OIDC issuer URL accepted by the AI Provider JWT authorizer."
}

variable "jwt_audience" {
  type        = list(string)
  description = "JWT audiences accepted by the AI Provider JWT authorizer."
}
