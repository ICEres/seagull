variable "name_prefix" {
  type        = string
  description = "Prefix used for web resource names."
}

variable "bucket_name" {
  type        = string
  description = "Globally unique S3 bucket name for static web assets."
}

variable "dist_dir" {
  type        = string
  description = "Path to the built Vite dist directory."
}

variable "domain_name" {
  type        = string
  description = "Public HTTPS hostname for the web frontend."
}

variable "admin_domain_name" {
  type        = string
  description = "Optional public HTTPS hostname for the admin frontend."
  default     = ""
}

variable "landing_domain_name" {
  type        = string
  description = "Optional public HTTPS hostname for the static landing page."
  default     = ""
}

variable "landing_dist_dir" {
  type        = string
  description = "Optional path to static landing page assets."
  default     = ""
}

variable "hosted_zone_id" {
  type        = string
  description = "Route 53 hosted zone ID for the web frontend domain."
}

variable "social_api_url" {
  type        = string
  description = "Runtime Social API URL written to config.js."
}

variable "message_api_url" {
  type        = string
  description = "Runtime Message API URL written to config.js."
}

variable "message_api_origin_domain" {
  type        = string
  description = "Message API hostname to serve /agents/* and /.well-known/* from on the landing (apex) distribution. Empty keeps the landing static-only."
  default     = ""
}

variable "ai_provider_api_url" {
  type        = string
  description = "Runtime AI provider API URL written to config.js."
}

variable "auth_mode" {
  type        = string
  description = "Runtime web auth mode written to config.js."
  default     = "local"
}

variable "auth_issuer" {
  type        = string
  description = "Cognito issuer URL written to config.js."
  default     = ""
}

variable "auth_hosted_domain" {
  type        = string
  description = "Cognito Hosted UI domain written to config.js."
  default     = ""
}

variable "auth_client_id" {
  type        = string
  description = "Cognito app client ID written to config.js."
  default     = ""
}

variable "auth_redirect_uri" {
  type        = string
  description = "OAuth callback URI written to config.js."
  default     = ""
}

variable "auth_logout_uri" {
  type        = string
  description = "Post-logout URI written to config.js."
  default     = ""
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to web resources."
  default     = {}
}
