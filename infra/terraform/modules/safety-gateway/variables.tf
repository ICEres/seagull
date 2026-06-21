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
  default     = false
}

variable "lambda_package_path" {
  type        = string
  description = "Path to the zipped safety gateway Lambda package."
}

variable "lambda_source_code_hash" {
  type        = string
  description = "Base64-encoded source hash for the safety gateway Lambda package."
}
