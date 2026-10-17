output "api_endpoint" {
  description = "HTTP API endpoint for the AI provider backend."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "lambda_function_name" {
  description = "AI provider Lambda function name."
  value       = aws_lambda_function.api.function_name
}

output "lambda_function_arn" {
  description = "AI provider Lambda function ARN."
  value       = aws_lambda_function.api.arn
}

output "worker_lambda_function_name" {
  description = "AI provider worker Lambda function name."
  value       = aws_lambda_function.worker.function_name
}

output "run_worker_queue_url" {
  description = "SQS FIFO queue URL for async AI provider runs."
  value       = aws_sqs_queue.run_worker.url
}

output "run_worker_dlq_url" {
  description = "SQS FIFO dead-letter queue URL for async AI provider runs."
  value       = aws_sqs_queue.run_worker_dlq.url
}

output "alarm_names" {
  description = "CloudWatch alarm names for AI provider API and worker health."
  value = {
    api_errors         = aws_cloudwatch_metric_alarm.api_errors.alarm_name
    worker_dlq_visible = aws_cloudwatch_metric_alarm.worker_dlq_visible.alarm_name
    worker_errors      = aws_cloudwatch_metric_alarm.worker_errors.alarm_name
  }
}

output "table_names" {
  description = "DynamoDB table names for AI provider storage."
  value = {
    admin_audit_events   = aws_dynamodb_table.admin_audit_events.name
    budget_limits        = aws_dynamodb_table.budget_limits.name
    model_policies       = aws_dynamodb_table.model_policies.name
    provider_configs     = aws_dynamodb_table.provider_configs.name
    run_events           = aws_dynamodb_table.run_events.name
    runs                 = aws_dynamodb_table.runs.name
    server_credit_ledger = aws_dynamodb_table.server_credit_ledger.name
    usage_ledger         = aws_dynamodb_table.usage_ledger.name
    user_credit_ledger   = aws_dynamodb_table.user_credit_ledger.name
  }
}

output "table_arns" {
  description = "DynamoDB table ARNs for AI provider storage."
  value = {
    admin_audit_events   = aws_dynamodb_table.admin_audit_events.arn
    budget_limits        = aws_dynamodb_table.budget_limits.arn
    model_policies       = aws_dynamodb_table.model_policies.arn
    provider_configs     = aws_dynamodb_table.provider_configs.arn
    run_events           = aws_dynamodb_table.run_events.arn
    runs                 = aws_dynamodb_table.runs.arn
    server_credit_ledger = aws_dynamodb_table.server_credit_ledger.arn
    usage_ledger         = aws_dynamodb_table.usage_ledger.arn
    user_credit_ledger   = aws_dynamodb_table.user_credit_ledger.arn
  }
}
