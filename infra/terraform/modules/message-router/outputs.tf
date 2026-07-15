output "connections_table_name" {
  description = "DynamoDB table name for active router connections."
  value       = aws_dynamodb_table.connections.name
}

output "connections_table_arn" {
  description = "DynamoDB table ARN for active router connections."
  value       = aws_dynamodb_table.connections.arn
}

output "websocket_api_id" {
  description = "API Gateway WebSocket API ID for the message router."
  value       = aws_apigatewayv2_api.websocket.id
}

output "websocket_api_endpoint" {
  description = "API Gateway WebSocket endpoint for the message router."
  value       = aws_apigatewayv2_api.websocket.api_endpoint
}

output "websocket_stage_invoke_url" {
  description = "Invoke URL for the default WebSocket stage."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "lambda_function_name" {
  description = "Message router Lambda function name."
  value       = aws_lambda_function.router.function_name
}

output "websocket_api_execution_arn" {
  description = "Execution ARN of the WebSocket API (for ManageConnections IAM grants)."
  value       = aws_apigatewayv2_api.websocket.execution_arn
}

output "websocket_callback_url" {
  description = "HTTPS management endpoint for posting to router connections."
  value       = replace(aws_apigatewayv2_stage.default.invoke_url, "wss://", "https://")
}
