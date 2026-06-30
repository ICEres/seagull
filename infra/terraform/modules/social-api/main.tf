locals {
  common_tags = merge(
    var.tags,
    {
      App = "social-api"
    },
  )

  table_arns = [
    aws_dynamodb_table.identities.arn,
    aws_dynamodb_table.profiles.arn,
    aws_dynamodb_table.personal_agent_assets.arn,
    aws_dynamodb_table.agent_asset_bindings.arn,
    aws_dynamodb_table.agent_chats.arn,
    aws_dynamodb_table.agent_chat_messages.arn,
    aws_dynamodb_table.nodes.arn,
    aws_dynamodb_table.pair_tokens.arn,
    aws_dynamodb_table.rooms.arn,
    aws_dynamodb_table.room_memberships.arn,
    aws_dynamodb_table.follows.arn,
    aws_dynamodb_table.posts.arn,
    aws_dynamodb_table.feed_events.arn,
    aws_dynamodb_table.notifications.arn,
    aws_dynamodb_table.moderation_records.arn,
  ]

  table_resources = concat(
    local.table_arns,
    [for arn in local.table_arns : "${arn}/index/*"],
  )
}

resource "aws_dynamodb_table" "identities" {
  name                        = "${var.name_prefix}-identities"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "user_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "provider_subject"
    type = "S"
  }

  global_secondary_index {
    name            = "provider-subject-index"
    hash_key        = "provider_subject"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "profiles" {
  name                        = "${var.name_prefix}-profiles"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "agent_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "agent_id"
    type = "S"
  }

  attribute {
    name = "handle"
    type = "S"
  }

  attribute {
    name = "owner_user_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "handle-index"
    hash_key        = "handle"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "owner-created-at-index"
    hash_key        = "owner_user_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "personal_agent_assets" {
  name                        = "${var.name_prefix}-personal-agent-assets"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "asset_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "asset_id"
    type = "S"
  }

  attribute {
    name = "owner_user_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "owner-created-at-index"
    hash_key        = "owner_user_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "agent_asset_bindings" {
  name                        = "${var.name_prefix}-agent-asset-bindings"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "agent_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "agent_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "agent_chats" {
  name                        = "${var.name_prefix}-agent-chats"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "chat_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "chat_id"
    type = "S"
  }

  attribute {
    name = "owner_user_id"
    type = "S"
  }

  attribute {
    name = "updated_at"
    type = "S"
  }

  global_secondary_index {
    name            = "owner-updated-at-index"
    hash_key        = "owner_user_id"
    range_key       = "updated_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "agent_chat_messages" {
  name                        = "${var.name_prefix}-agent-chat-messages"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "chat_message_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "chat_message_id"
    type = "S"
  }

  attribute {
    name = "chat_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "chat-created-at-index"
    hash_key        = "chat_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "nodes" {
  name                        = "${var.name_prefix}-nodes"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "node_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "node_id"
    type = "S"
  }

  attribute {
    name = "owner_user_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "owner-created-at-index"
    hash_key        = "owner_user_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "pair_tokens" {
  name                        = "${var.name_prefix}-pair-tokens"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pair_token"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "pair_token"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "rooms" {
  name                        = "${var.name_prefix}-rooms"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "room_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "room_id"
    type = "S"
  }

  attribute {
    name = "slug"
    type = "S"
  }

  global_secondary_index {
    name            = "slug-index"
    hash_key        = "slug"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "room_memberships" {
  name                        = "${var.name_prefix}-room-memberships"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "room_id"
  range_key                   = "agent_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "room_id"
    type = "S"
  }

  attribute {
    name = "agent_id"
    type = "S"
  }

  global_secondary_index {
    name            = "agent-index"
    hash_key        = "agent_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "follows" {
  name                        = "${var.name_prefix}-follows"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "follower_agent_id"
  range_key                   = "followed_agent_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "follower_agent_id"
    type = "S"
  }

  attribute {
    name = "followed_agent_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "posts" {
  name                        = "${var.name_prefix}-posts"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "post_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "post_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "feed_events" {
  name                        = "${var.name_prefix}-feed-events"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "event_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "event_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "notifications" {
  name                        = "${var.name_prefix}-notifications"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "notification_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "notification_id"
    type = "S"
  }

  attribute {
    name = "recipient_agent_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "recipient-created-at-index"
    hash_key        = "recipient_agent_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_dynamodb_table" "moderation_records" {
  name                        = "${var.name_prefix}-moderation-records"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "moderation_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "moderation_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : null
  }

  tags = local.common_tags
}

resource "aws_iam_role" "lambda" {
  name = "${var.name_prefix}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name_prefix}"
  retention_in_days = 7

  tags = local.common_tags
}

resource "aws_iam_role_policy" "lambda" {
  name = "${var.name_prefix}-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = local.table_resources
      }
    ]
  })
}

resource "aws_lambda_function" "api" {
  function_name    = var.name_prefix
  role             = aws_iam_role.lambda.arn
  handler          = "lambda_function.handler"
  runtime          = "python3.13"
  filename         = var.lambda_package_path
  source_code_hash = var.lambda_source_code_hash
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      AGENT_ASSET_BINDINGS_TABLE      = aws_dynamodb_table.agent_asset_bindings.name
      AGENT_CHAT_MESSAGES_TABLE       = aws_dynamodb_table.agent_chat_messages.name
      AGENT_CHATS_TABLE               = aws_dynamodb_table.agent_chats.name
      APP_NAME                        = var.name_prefix
      FEED_EVENTS_TABLE               = aws_dynamodb_table.feed_events.name
      FOLLOWS_TABLE                   = aws_dynamodb_table.follows.name
      IDENTITIES_TABLE                = aws_dynamodb_table.identities.name
      MODERATION_TABLE                = aws_dynamodb_table.moderation_records.name
      NODES_TABLE                     = aws_dynamodb_table.nodes.name
      NOTIFICATIONS_TABLE             = aws_dynamodb_table.notifications.name
      PAIR_TOKENS_TABLE               = aws_dynamodb_table.pair_tokens.name
      PERSONAL_AGENT_ASSETS_TABLE     = aws_dynamodb_table.personal_agent_assets.name
      POSTS_TABLE                     = aws_dynamodb_table.posts.name
      PROFILES_TABLE                  = aws_dynamodb_table.profiles.name
      ROOM_MEMBERSHIPS_TABLE          = aws_dynamodb_table.room_memberships.name
      ROOMS_TABLE                     = aws_dynamodb_table.rooms.name
      SOCIAL_AUTH_REQUIRED            = "true"
      MESSAGE_API_URL                 = var.message_api_url
      MESSAGE_HUB_LEGACY_ROUTE_SECRET = var.message_hub_legacy_route_secret
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda,
  ]

  tags = local.common_tags
}

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.name_prefix}-http"
  protocol_type = "HTTP"

  cors_configuration {
    allow_headers = ["authorization", "content-type"]
    allow_methods = ["GET", "PATCH", "POST", "PUT", "OPTIONS"]
    allow_origins = ["*"]
    max_age       = 300
  }

  tags = local.common_tags
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.http.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${var.name_prefix}-jwt"

  jwt_configuration {
    audience = var.jwt_audience
    issuer   = var.jwt_issuer
  }
}

resource "aws_apigatewayv2_route" "default" {
  api_id             = aws_apigatewayv2_api.http.id
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  route_key          = "$default"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "agent_registrations" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "POST /agent-registrations"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "options_proxy" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "OPTIONS /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  tags = local.common_tags
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromSocialApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
