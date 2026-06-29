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
  default     = false
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
  description = "Development admin secret for AI provider admin operations."
  sensitive   = true
}
