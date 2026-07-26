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
  default     = true
}

variable "point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable DynamoDB point-in-time recovery for social API tables."
  default     = true
}

variable "dynamodb_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN used for DynamoDB server-side encryption."
  default     = ""
}

variable "lambda_package_path" {
  type        = string
  description = "Path to the zipped social API Lambda package."
}

variable "lambda_source_code_hash" {
  type        = string
  description = "Base64-encoded source hash for the social API Lambda package."
}

variable "message_api_url" {
  type        = string
  description = "Optional Message Hub API URL for chat-to-agent delivery."
  default     = ""
}

variable "message_hub_legacy_route_secret_arn" {
  type        = string
  description = "Optional Secrets Manager ARN containing the Message Hub legacy route secret."
  default     = ""
}

variable "ai_provider_api_url" {
  type        = string
  description = "Optional AI provider API URL for provider-backed chat replies."
  default     = ""
}

variable "ai_provider_admin_secret_arn" {
  type        = string
  description = "Optional Secrets Manager ARN containing the AI provider admin secret used for chat reply runs."
  default     = ""
}

variable "ai_reply_provider" {
  type        = string
  description = "AI provider name used for chat reply runs (empty disables provider-backed replies)."
  default     = ""
}

variable "ai_reply_model" {
  type        = string
  description = "AI model used for chat reply runs (empty disables provider-backed replies)."
  default     = ""
}

variable "lambda_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN used to encrypt Lambda environment variables."
  default     = ""
}

variable "jwt_issuer" {
  type        = string
  description = "OIDC issuer URL accepted by the Social API JWT authorizer."
}

variable "jwt_audience" {
  type        = list(string)
  description = "JWT audiences accepted by the Social API JWT authorizer."
}

variable "auth_bypass_secret_arn" {
  type        = string
  description = "Optional Secrets Manager ARN containing the shared secret required when SOCIAL_AUTH_REQUIRED is disabled."
  default     = ""
}

variable "api_throttling_burst_limit" {
  type        = number
  description = "Default API Gateway burst throttle for the Social API HTTP API."
  default     = 100
}

variable "api_throttling_rate_limit" {
  type        = number
  description = "Default API Gateway steady-state requests per second for the Social API HTTP API."
  default     = 50
}

variable "access_log_retention_days" {
  type        = number
  description = "Retention in days for Social API Gateway access logs."
  default     = 30
}

variable "gulls_feed_table_names" {
  description = <<-EOT
    Names of the gulls Feed tables to dual-write into, keyed by
    posts/follows/rooms/room_memberships/feed_events/notifications. Empty
    disables the mirror, so an environment applied before those tables existed
    keeps working unchanged.
  EOT
  type        = map(string)
  default     = {}
}

variable "gulls_feed_table_arns" {
  description = "ARNs of the gulls Feed tables, for the dual-write IAM grant."
  type        = list(string)
  default     = []
}

variable "gulls_feed_reads_enabled" {
  description = <<-EOT
    Serve base Feed records from the gulls tables instead of the seagulls ones.
    Keep this off until the dual-write has run long enough that gulls holds the
    posts being read; reads fall back to seagulls for anything gulls does not
    have, so enabling it early degrades quietly rather than loudly.
  EOT
  type        = bool
  default     = false
}
