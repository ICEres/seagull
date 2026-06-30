variable "name_prefix" {
  type        = string
  description = "Prefix used for message hub storage table names."
}

variable "point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable DynamoDB point-in-time recovery for message hub tables."
  default     = true
}

variable "deletion_protection_enabled" {
  type        = bool
  description = "Enable DynamoDB deletion protection for message hub tables."
  default     = true
}

variable "dynamodb_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN used for DynamoDB server-side encryption."
  default     = ""
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to message hub resources."
  default     = {}
}
