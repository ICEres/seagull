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
