output "table_names" {
  description = "Message hub DynamoDB table names."
  value = {
    agents           = aws_dynamodb_table.agents.name
    agent_tokens     = aws_dynamodb_table.agent_tokens.name
    messages         = aws_dynamodb_table.messages.name
    threads          = aws_dynamodb_table.threads.name
    deliveries       = aws_dynamodb_table.deliveries.name
    routing_rules    = aws_dynamodb_table.routing_rules.name
    idempotency_keys = aws_dynamodb_table.idempotency_keys.name
    thread_summaries = aws_dynamodb_table.thread_summaries.name
    payloads         = aws_dynamodb_table.payloads.name
    tasks            = aws_dynamodb_table.tasks.name
    tool_requests    = aws_dynamodb_table.tool_requests.name
    task_results     = aws_dynamodb_table.task_results.name
  }
}

output "table_arns" {
  description = "Message hub DynamoDB table ARNs."
  value = {
    agents           = aws_dynamodb_table.agents.arn
    agent_tokens     = aws_dynamodb_table.agent_tokens.arn
    messages         = aws_dynamodb_table.messages.arn
    threads          = aws_dynamodb_table.threads.arn
    deliveries       = aws_dynamodb_table.deliveries.arn
    routing_rules    = aws_dynamodb_table.routing_rules.arn
    idempotency_keys = aws_dynamodb_table.idempotency_keys.arn
    thread_summaries = aws_dynamodb_table.thread_summaries.arn
    payloads         = aws_dynamodb_table.payloads.arn
    tasks            = aws_dynamodb_table.tasks.arn
    tool_requests    = aws_dynamodb_table.tool_requests.arn
    task_results     = aws_dynamodb_table.task_results.arn
  }
}

output "payload_objects_bucket_name" {
  description = "S3 bucket name for compressed payload objects."
  value       = aws_s3_bucket.payload_objects.bucket
}

output "payload_objects_bucket_arn" {
  description = "S3 bucket ARN for compressed payload objects."
  value       = aws_s3_bucket.payload_objects.arn
}
