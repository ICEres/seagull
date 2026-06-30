variable "aws_profile" {
  type        = string
  description = "Optional AWS CLI profile used by Terraform. Leave empty to use the default AWS credential chain."
  default     = ""
}

variable "aws_region" {
  type        = string
  description = "AWS region used by the provider. Route 53 hosted zones are global."
  default     = "ap-southeast-2"
}

variable "domain_name" {
  type        = string
  description = "Root DNS domain for Seagull."
  default     = "gulls.ai"
}

variable "project" {
  type        = string
  description = "Project tag value."
  default     = "seagull"
}
