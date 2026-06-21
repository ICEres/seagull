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
  default     = false
}

variable "lambda_package_path" {
  type        = string
  description = "Path to the zipped message router Lambda package."
}

variable "lambda_source_code_hash" {
  type        = string
  description = "Base64-encoded source hash for the message router Lambda package."
}
