output "account_id" {
  description = "AWS account ID used by the dev deployment."
  value       = data.aws_caller_identity.current.account_id
}

output "api_endpoint" {
  description = "HTTP API endpoint for the message hub."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "message_api_url" {
  description = "Public HTTPS URL for the message hub."
  value       = "https://${var.message_api_domain}"
}

output "message_hub_table_names" {
  description = "DynamoDB table names for the real message hub storage model."
  value       = module.message_hub_storage.table_names
}

output "message_hub_table_arns" {
  description = "DynamoDB table ARNs for the real message hub storage model."
  value       = module.message_hub_storage.table_arns
}

output "message_hub_agent_jobs_queue_url" {
  description = "SQS FIFO queue URL for async agent delivery jobs."
  value       = aws_sqs_queue.agent_jobs.url
}

output "message_hub_agent_jobs_queue_name" {
  description = "SQS FIFO queue name for async agent delivery jobs."
  value       = aws_sqs_queue.agent_jobs.name
}

output "message_hub_agent_jobs_dlq_url" {
  description = "SQS FIFO dead-letter queue URL for failed async agent delivery jobs."
  value       = aws_sqs_queue.agent_jobs_dlq.url
}

output "message_hub_agent_jobs_dlq_name" {
  description = "SQS FIFO dead-letter queue name for failed async agent delivery jobs."
  value       = aws_sqs_queue.agent_jobs_dlq.name
}

output "message_hub_agent_worker_lambda_function_name" {
  description = "Message hub async agent worker Lambda function name."
  value       = aws_lambda_function.agent_worker.function_name
}

output "safety_gateway_api_url" {
  description = "HTTP API endpoint for the safety gateway."
  value       = module.safety_gateway.api_endpoint
}

output "safety_gateway_audit_table_name" {
  description = "DynamoDB table name for safety audit events."
  value       = module.safety_gateway.audit_table_name
}

output "safety_gateway_lambda_function_name" {
  description = "Safety gateway Lambda function name."
  value       = module.safety_gateway.lambda_function_name
}

output "ai_provider_api_url" {
  description = "HTTP API endpoint for the AI provider backend."
  value       = module.ai_provider.api_endpoint
}

output "ai_provider_lambda_function_name" {
  description = "AI provider Lambda function name."
  value       = module.ai_provider.lambda_function_name
}

output "ai_provider_table_names" {
  description = "DynamoDB table names for the AI provider backend."
  value       = module.ai_provider.table_names
}

output "social_api_url" {
  description = "HTTP API endpoint for the social API."
  value       = module.social_api.api_endpoint
}

output "social_api_lambda_function_name" {
  description = "Social API Lambda function name."
  value       = module.social_api.lambda_function_name
}

output "social_api_table_names" {
  description = "DynamoDB table names for the social API."
  value       = module.social_api.table_names
}

output "social_auth_user_pool_id" {
  description = "Cognito user pool ID for web/social auth."
  value       = aws_cognito_user_pool.social_web.id
}

output "social_auth_client_id" {
  description = "Cognito app client ID for the web frontend."
  value       = aws_cognito_user_pool_client.social_web.id
}

output "social_auth_issuer_url" {
  description = "Cognito issuer URL for web/social auth."
  value       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.social_web.id}"
}

output "social_auth_hosted_domain" {
  description = "Cognito Hosted UI domain for web/social auth."
  value       = "${aws_cognito_user_pool_domain.social_web.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "social_auth_authorization_url" {
  description = "Cognito OAuth authorization endpoint for web/social auth."
  value       = "https://${aws_cognito_user_pool_domain.social_web.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/authorize"
}

output "social_auth_token_url" {
  description = "Cognito OAuth token endpoint for web/social auth."
  value       = "https://${aws_cognito_user_pool_domain.social_web.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token"
}

output "web_url" {
  description = "HTTPS URL for the frontend."
  value       = module.web.url
}

output "web_bucket_name" {
  description = "S3 bucket that stores frontend assets."
  value       = module.web.bucket_name
}

output "web_cloudfront_distribution_id" {
  description = "CloudFront distribution ID for the frontend."
  value       = module.web.cloudfront_distribution_id
}

output "web_cloudfront_url" {
  description = "Default CloudFront HTTPS URL for the frontend."
  value       = module.web.cloudfront_url
}

output "web_domain_name" {
  description = "Custom frontend domain name."
  value       = module.web.domain_name
}

output "admin_web_url" {
  description = "Custom admin frontend URL."
  value       = module.web.admin_url
}

output "mcp_connector_url" {
  description = "Public HTTPS URL for the hosted MCP connector service."
  value       = "https://${var.mcp_domain_name}"
}

output "mcp_connector_endpoint" {
  description = "MCP Streamable HTTP endpoint URL."
  value       = "https://${var.mcp_domain_name}/mcp"
}

output "mcp_connector_api_endpoint" {
  description = "Default API Gateway endpoint for the hosted MCP connector."
  value       = aws_apigatewayv2_api.mcp_connector.api_endpoint
}

output "mcp_connector_lambda_function_name" {
  description = "Hosted MCP connector Lambda function name."
  value       = aws_lambda_function.mcp_connector.function_name
}

output "mcp_connector_tokens_table_name" {
  description = "DynamoDB table name for connector token metadata."
  value       = aws_dynamodb_table.mcp_connector_tokens.name
}

output "mcp_oauth_user_pool_id" {
  description = "Cognito user pool ID for MCP OAuth."
  value       = aws_cognito_user_pool.mcp_connector.id
}

output "mcp_oauth_client_id" {
  description = "Cognito app client ID for ChatGPT MCP OAuth."
  value       = aws_cognito_user_pool_client.mcp_connector_chatgpt.id
}

output "mcp_oauth_issuer_url" {
  description = "Cognito issuer URL advertised by the MCP protected resource metadata."
  value       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.mcp_connector.id}"
}

output "mcp_oauth_authorization_url" {
  description = "Cognito OAuth authorization endpoint for ChatGPT MCP setup."
  value       = "https://${aws_cognito_user_pool_domain.mcp_connector.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/authorize"
}

output "mcp_chatgpt_oauth_authorization_url" {
  description = "Seagull OAuth authorization proxy endpoint for ChatGPT MCP setup."
  value       = "https://${var.mcp_domain_name}/oauth/authorize"
}

output "mcp_oauth_token_url" {
  description = "Cognito OAuth token endpoint for ChatGPT MCP setup."
  value       = "https://${aws_cognito_user_pool_domain.mcp_connector.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token"
}

output "mcp_chatgpt_oauth_token_url" {
  description = "Seagull OAuth token proxy endpoint for ChatGPT MCP setup."
  value       = "https://${var.mcp_domain_name}/oauth/token"
}

output "mcp_oauth_hosted_domain" {
  description = "Cognito hosted UI domain for MCP OAuth."
  value       = "${aws_cognito_user_pool_domain.mcp_connector.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "message_router_connections_table_name" {
  description = "DynamoDB table name for active message router connections."
  value       = module.message_router.connections_table_name
}

output "message_router_websocket_url" {
  description = "WebSocket URL for the message router."
  value       = module.message_router.websocket_stage_invoke_url
}

output "message_router_lambda_function_name" {
  description = "Message router Lambda function name."
  value       = module.message_router.lambda_function_name
}

output "lambda_function_name" {
  description = "Message hub API Lambda function name."
  value       = aws_lambda_function.message_hub_api.function_name
}
