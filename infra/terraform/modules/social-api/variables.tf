variable "name_prefix" {
  type        = string
  description = "Prefix used for social API resource names."
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to social API resources."
  default     = {}
}

variable "deletion_protection_enabled" {
  type        = bool
  description = "Enable DynamoDB deletion protection for social API tables."
  default     = false
}

variable "lambda_package_path" {
  type        = string
  description = "Path to the zipped social API Lambda package."
}

variable "lambda_source_code_hash" {
  type        = string
  description = "Base64-encoded source hash for the social API Lambda package."
}

variable "jwt_issuer" {
  type        = string
  description = "OIDC issuer URL accepted by the Social API JWT authorizer."
}

variable "jwt_audience" {
  type        = list(string)
  description = "JWT audiences accepted by the Social API JWT authorizer."
}
