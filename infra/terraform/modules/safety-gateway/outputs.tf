output "api_endpoint" {
  description = "HTTP API endpoint for the safety gateway."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "audit_table_name" {
  description = "DynamoDB table name for safety audit events."
  value       = aws_dynamodb_table.audit_events.name
}

output "audit_table_arn" {
  description = "DynamoDB table ARN for safety audit events."
  value       = aws_dynamodb_table.audit_events.arn
}

output "lambda_function_name" {
  description = "Safety gateway Lambda function name."
  value       = aws_lambda_function.api.function_name
}
