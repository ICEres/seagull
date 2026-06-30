variable "project" {
  type        = string
  description = "Project name used in AWS resource names."
  default     = "seagull"
}

variable "environment" {
  type        = string
  description = "Deployment environment name."
  default     = "dev"
}

variable "aws_region" {
  type        = string
  description = "AWS region for the dev deployment."
  default     = "ap-southeast-2"
}

variable "aws_profile" {
  type        = string
  description = "Optional AWS CLI profile used by Terraform. Leave empty to use the default AWS credential chain."
  default     = ""
}

variable "root_domain" {
  type        = string
  description = "Route 53 hosted zone domain used for public DNS records."
  default     = "gulls.ai"
}

variable "message_api_domain" {
  type        = string
  description = "Public HTTPS hostname for the message hub API."
  default     = "fishing.gulls.ai"
}

variable "web_domain_name" {
  type        = string
  description = "Public HTTPS hostname for the web frontend."
  default     = "sea.gulls.ai"
}

variable "landing_domain_name" {
  type        = string
  description = "Public HTTPS hostname for the landing page."
  default     = "gulls.ai"
}

variable "admin_domain_name" {
  type        = string
  description = "Public HTTPS hostname for the server-owner admin frontend."
  default     = "admin.gulls.ai"
}

variable "mcp_domain_name" {
  type        = string
  description = "Public HTTPS hostname for the hosted MCP connector."
  default     = "mcp.gulls.ai"
}

variable "agent_webhook_signing_secret" {
  type        = string
  description = "Signing secret used for outbound Seagull agent webhooks. Leave empty only to disable webhook dispatch."
  default     = ""
  sensitive   = true
}

variable "dynamodb_point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable point-in-time recovery for DynamoDB tables."
  default     = false
}

variable "dynamodb_deletion_protection_enabled" {
  type        = bool
  description = "Enable deletion protection for DynamoDB tables."
  default     = false
}

variable "api_throttling_burst_limit" {
  type        = number
  description = "Default API Gateway burst throttle for public APIs in this environment."
  default     = 100
}

variable "api_throttling_rate_limit" {
  type        = number
  description = "Default API Gateway steady-state requests per second for public APIs in this environment."
  default     = 50
}

variable "api_access_log_retention_days" {
  type        = number
  description = "Retention in days for API Gateway access logs."
  default     = 30
}

variable "mcp_connector_admin_secret" {
  type        = string
  description = "Optional admin secret for creating and revoking connector tokens. Leave empty to disable secret-based admin access."
  default     = ""
  sensitive   = true
}

variable "ai_provider_admin_secret" {
  type        = string
  description = "Optional AI provider admin secret. Leave empty to require Cognito admin claims."
  default     = ""
  sensitive   = true
}

variable "mcp_dev_token" {
  type        = string
  description = "Optional development bearer token accepted by the hosted MCP connector."
  default     = ""
  sensitive   = true
}

variable "safety_gateway_admin_secret" {
  type        = string
  description = "Shared secret used by internal Safety Gateway callers."
  default     = ""
  sensitive   = true
}

variable "mcp_dev_owner_user_id" {
  type        = string
  description = "Owner user ID attached to the optional MCP development token."
  default     = "user_dev"
}

variable "mcp_dev_agent_handles" {
  type        = list(string)
  description = "Agent handles attached to the optional MCP development token."
  default     = []
}

variable "mcp_no_auth_enabled" {
  type        = bool
  description = "Enable restricted no-auth MCP access for ChatGPT developer-mode smoke tests. Only honored when environment is dev."
  default     = false
}

variable "mcp_no_auth_owner_user_id" {
  type        = string
  description = "Owner user ID attached to restricted no-auth MCP access."
  default     = "user_chatgpt_dev"
}

variable "mcp_no_auth_agent_handles" {
  type        = list(string)
  description = "Agent handles exposed to restricted no-auth MCP access."
  default     = []
}

variable "mcp_no_auth_scopes" {
  type        = list(string)
  description = "Scopes exposed to restricted no-auth MCP access."
  default     = ["agents:read"]
}

variable "mcp_allowed_origins" {
  type        = list(string)
  description = "Browser origins allowed by the hosted MCP connector CORS policy."
  default = [
    "https://chatgpt.com",
    "https://chat.openai.com",
  ]
}

variable "mcp_cognito_domain_prefix" {
  type        = string
  description = "Optional globally unique Cognito hosted UI domain prefix for MCP OAuth."
  default     = ""
}

variable "social_cognito_domain_prefix" {
  type        = string
  description = "Optional globally unique Cognito hosted UI domain prefix for web/social auth."
  default     = ""
}

variable "chatgpt_oauth_redirect_uris" {
  type        = list(string)
  description = "ChatGPT OAuth callback URLs allowed by the MCP Cognito app client."
  default = [
    "https://chatgpt.com/connector_platform_oauth_redirect",
    "https://chatgpt.com/connector/oauth/b6YSyO7BohhS",
  ]
}
