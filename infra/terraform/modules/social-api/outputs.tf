output "api_endpoint" {
  description = "HTTP API endpoint for the social API."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "lambda_function_name" {
  description = "Social API Lambda function name."
  value       = aws_lambda_function.api.function_name
}

output "table_names" {
  description = "DynamoDB table names for the social API."
  value = {
    agent_asset_bindings  = aws_dynamodb_table.agent_asset_bindings.name
    agent_chat_messages   = aws_dynamodb_table.agent_chat_messages.name
    agent_chats           = aws_dynamodb_table.agent_chats.name
    feed_events           = aws_dynamodb_table.feed_events.name
    follows               = aws_dynamodb_table.follows.name
    identities            = aws_dynamodb_table.identities.name
    moderation            = aws_dynamodb_table.moderation_records.name
    nodes                 = aws_dynamodb_table.nodes.name
    notifications         = aws_dynamodb_table.notifications.name
    pair_tokens           = aws_dynamodb_table.pair_tokens.name
    personal_agent_assets = aws_dynamodb_table.personal_agent_assets.name
    posts                 = aws_dynamodb_table.posts.name
    profiles              = aws_dynamodb_table.profiles.name
    room_memberships      = aws_dynamodb_table.room_memberships.name
    rooms                 = aws_dynamodb_table.rooms.name
  }
}

output "table_arns" {
  description = "DynamoDB table ARNs for the social API."
  value = {
    agent_asset_bindings  = aws_dynamodb_table.agent_asset_bindings.arn
    agent_chat_messages   = aws_dynamodb_table.agent_chat_messages.arn
    agent_chats           = aws_dynamodb_table.agent_chats.arn
    feed_events           = aws_dynamodb_table.feed_events.arn
    follows               = aws_dynamodb_table.follows.arn
    identities            = aws_dynamodb_table.identities.arn
    moderation            = aws_dynamodb_table.moderation_records.arn
    nodes                 = aws_dynamodb_table.nodes.arn
    notifications         = aws_dynamodb_table.notifications.arn
    pair_tokens           = aws_dynamodb_table.pair_tokens.arn
    personal_agent_assets = aws_dynamodb_table.personal_agent_assets.arn
    posts                 = aws_dynamodb_table.posts.arn
    profiles              = aws_dynamodb_table.profiles.arn
    room_memberships      = aws_dynamodb_table.room_memberships.arn
    rooms                 = aws_dynamodb_table.rooms.arn
  }
}

output "feed_mirror_alarm_name" {
  description = "Alarm that fires when the gulls Feed mirror drops writes. Must be quiet before GULLS_FEED_READS is flipped. Null while feed_mirror_metrics_enabled is off."
  value       = one(aws_cloudwatch_metric_alarm.feed_mirror_failed[*].alarm_name)
}

output "feed_mirror_metrics" {
  description = <<-EOT
    CloudWatch metrics proving the dual-write is live. Healthy means ok climbing
    and failed flat at zero; both flat means the mirror is not configured.

    Null while feed_mirror_metrics_enabled is off -- in that state the mirror
    still runs, but nothing measures it, so the dual-write cannot be verified.
  EOT
  value = var.feed_mirror_metrics_enabled ? {
    namespace = one(aws_cloudwatch_log_metric_filter.feed_mirror_ok[*].metric_transformation[0].namespace)
    ok        = one(aws_cloudwatch_log_metric_filter.feed_mirror_ok[*].metric_transformation[0].name)
    failed    = one(aws_cloudwatch_log_metric_filter.feed_mirror_failed[*].metric_transformation[0].name)
  } : null
}
