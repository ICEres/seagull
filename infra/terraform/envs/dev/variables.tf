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
  description = "AWS CLI profile used by Terraform."
  default     = "personal"
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
  description = "Development signing secret used for outbound Seagull agent webhooks."
  default     = "dev-only-change-me"
  sensitive   = true
}

variable "mcp_connector_admin_secret" {
  type        = string
  description = "Development admin secret for creating and revoking connector tokens."
  default     = "dev-only-change-me"
  sensitive   = true
}

variable "ai_provider_admin_secret" {
  type        = string
  description = "Development admin secret for AI provider admin operations."
  default     = "dev-only-change-me"
  sensitive   = true
}

variable "mcp_dev_token" {
  type        = string
  description = "Optional development bearer token accepted by the hosted MCP connector."
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
  description = "Enable restricted no-auth MCP access for ChatGPT developer-mode smoke tests in dev."
  default     = true
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
