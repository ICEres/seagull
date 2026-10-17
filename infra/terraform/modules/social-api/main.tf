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

  # The Feed dual-write writes into the gulls Feed tables, so those ARNs join
  # the grant. Empty until the mirror is configured.
  #
  # The hub messages table joins it too once chat reads are configured: chat
  # content lives there, not in the Feed tables. Read-only in practice -- chat
  # writes reach the hub over its API, not by writing this table directly.
  chat_table_arns = var.gulls_messages_table_arn == "" ? [] : [
    var.gulls_messages_table_arn,
    "${var.gulls_messages_table_arn}/index/*",
  ]

  table_resources = concat(
    local.table_arns,
    [for arn in local.table_arns : "${arn}/index/*"],
    var.gulls_feed_table_arns,
    [for arn in var.gulls_feed_table_arns : "${arn}/index/*"],
    local.chat_table_arns,
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

  global_secondary_index {
    name            = "followed-index"
    hash_key        = "followed_agent_id"
    range_key       = "follower_agent_id"
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

resource "aws_dynamodb_table" "posts" {
  name                        = "${var.name_prefix}-posts"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "post_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "post_id"
    type = "S"
  }

  attribute {
    name = "timeline_partition"
    type = "S"
  }

  attribute {
    name = "author_agent_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "created-at-index"
    hash_key        = "timeline_partition"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "author-created-at-index"
    hash_key        = "author_agent_id"
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

resource "aws_dynamodb_table" "feed_events" {
  name                        = "${var.name_prefix}-feed-events"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "event_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "event_id"
    type = "S"
  }

  attribute {
    name = "timeline_partition"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "created-at-index"
    hash_key        = "timeline_partition"
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
    name = "owner_user_id"
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

resource "aws_dynamodb_table" "moderation_records" {
  name                        = "${var.name_prefix}-moderation-records"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "moderation_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "moderation_id"
    type = "S"
  }

  attribute {
    name = "timeline_partition"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "created-at-index"
    hash_key        = "timeline_partition"
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
    Statement = concat([
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
      ],
      var.message_hub_legacy_route_secret_arn == "" && var.auth_bypass_secret_arn == "" && var.ai_provider_admin_secret_arn == "" ? [] : [
        {
          Effect = "Allow"
          Action = ["secretsmanager:GetSecretValue"]
          Resource = compact([
            var.message_hub_legacy_route_secret_arn,
            var.auth_bypass_secret_arn,
            var.ai_provider_admin_secret_arn,
          ])
        },
      ],
      var.ai_provider_function_arn == "" ? [] : [
        {
          Effect   = "Allow"
          Action   = ["lambda:InvokeFunction"]
          Resource = var.ai_provider_function_arn
        },
      ],
      var.message_hub_legacy_route_secret_arn == "" && var.auth_bypass_secret_arn == "" && var.ai_provider_admin_secret_arn == "" && var.lambda_kms_key_arn == "" ? [] : [
        {
          Effect   = "Allow"
          Action   = ["kms:Decrypt"]
          Resource = var.lambda_kms_key_arn != "" ? var.lambda_kms_key_arn : (var.dynamodb_kms_key_arn != "" ? var.dynamodb_kms_key_arn : "*")
        }
      ]
    )
  })
}

resource "aws_lambda_function" "api" {
  function_name    = var.name_prefix
  role             = aws_iam_role.lambda.arn
  handler          = "lambda_function.handler"
  runtime          = "python3.13"
  filename         = var.lambda_package_path
  source_code_hash = var.lambda_source_code_hash
  # Long enough for one synchronous provider-backed chat reply run.
  timeout     = 30
  memory_size = 256
  kms_key_arn = var.lambda_kms_key_arn != "" ? var.lambda_kms_key_arn : null

  environment {
    variables = merge(
      {
        AGENT_ASSET_BINDINGS_TABLE  = aws_dynamodb_table.agent_asset_bindings.name
        AGENT_CHAT_MESSAGES_TABLE   = aws_dynamodb_table.agent_chat_messages.name
        AGENT_CHATS_TABLE           = aws_dynamodb_table.agent_chats.name
        APP_NAME                    = var.name_prefix
        FEED_EVENTS_TABLE           = aws_dynamodb_table.feed_events.name
        FOLLOWS_TABLE               = aws_dynamodb_table.follows.name
        IDENTITIES_TABLE            = aws_dynamodb_table.identities.name
        MODERATION_TABLE            = aws_dynamodb_table.moderation_records.name
        NODES_TABLE                 = aws_dynamodb_table.nodes.name
        NOTIFICATIONS_TABLE         = aws_dynamodb_table.notifications.name
        PAIR_TOKENS_TABLE           = aws_dynamodb_table.pair_tokens.name
        PERSONAL_AGENT_ASSETS_TABLE = aws_dynamodb_table.personal_agent_assets.name
        POSTS_TABLE                 = aws_dynamodb_table.posts.name
        PROFILES_TABLE              = aws_dynamodb_table.profiles.name
        ROOM_MEMBERSHIPS_TABLE      = aws_dynamodb_table.room_memberships.name
        ROOMS_TABLE                 = aws_dynamodb_table.rooms.name
        SOCIAL_AUTH_REQUIRED        = "true"
        MESSAGE_API_URL             = var.message_api_url
        AI_PROVIDER_API_URL         = var.ai_provider_api_url
        AI_PROVIDER_FUNCTION_ARN    = var.ai_provider_function_arn
        AI_REPLY_PROVIDER           = var.ai_reply_provider
        AI_REPLY_MODEL              = var.ai_reply_model
        AI_REPLY_MAX_OUTPUT_TOKENS  = tostring(var.ai_reply_max_output_tokens)
        HUMAN_PROXY_DOMAIN          = var.human_proxy_domain
        REQUIRE_AGENT_REGISTRY      = var.require_agent_registry ? "true" : "false"
      },
      var.auth_bypass_secret_arn == "" ? {} : {
        SOCIAL_AUTH_BYPASS_SECRET_ARN = var.auth_bypass_secret_arn
      },
      var.message_hub_legacy_route_secret_arn == "" ? {} : {
        MESSAGE_HUB_LEGACY_ROUTE_SECRET_ARN = var.message_hub_legacy_route_secret_arn
      },
      var.ai_provider_admin_secret_arn == "" ? {} : {
        AI_PROVIDER_ADMIN_SECRET_ARN = var.ai_provider_admin_secret_arn
      },
      # GULLS_*-prefixed: this Lambda already binds POSTS_TABLE and friends to
      # the seagulls tables, so the Feed dual-write targets need their own names.
      length(var.gulls_feed_table_names) == 0 ? {} : {
        GULLS_POSTS_TABLE            = var.gulls_feed_table_names.posts
        GULLS_FOLLOWS_TABLE          = var.gulls_feed_table_names.follows
        GULLS_ROOMS_TABLE            = var.gulls_feed_table_names.rooms
        GULLS_ROOM_MEMBERSHIPS_TABLE = var.gulls_feed_table_names.room_memberships
        GULLS_FEED_EVENTS_TABLE      = var.gulls_feed_table_names.feed_events
        GULLS_NOTIFICATIONS_TABLE    = var.gulls_feed_table_names.notifications
        GULLS_FEED_READS             = var.gulls_feed_reads_enabled ? "true" : "false"
      },
      # Chat content lives in the hub's messages table, not the Feed tables.
      var.gulls_messages_table_name == "" ? {} : {
        GULLS_MESSAGES_TABLE = var.gulls_messages_table_name
        GULLS_CHAT_READS     = var.gulls_chat_reads_enabled ? "true" : "false"
      }
    )
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
    allow_headers = ["authorization", "content-type", "x-seagull-auth-bypass-secret"]
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

  default_route_settings {
    throttling_burst_limit = var.api_throttling_burst_limit
    throttling_rate_limit  = var.api_throttling_rate_limit
  }

  tags = local.common_tags
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromSocialApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Feed mirror observability
#
# BestEffortFeedMirror swallows gulls-side failures on purpose: during the
# dual-write stage seagulls is still authoritative, so a mirror problem must
# never cost a human their post. The cost of that choice is that a broken
# mirror is invisible -- gulls silently falls behind, and the first symptom is
# a thin feed after GULLS_FEED_READS is flipped.
#
# These filters make it visible. The mirror emits one JSON line per attempt
# with event="feed_mirror"; the pattern below keys off that field, matching
# FEED_MIRROR_EVENT in social_api/domain/feed_mirror.py.
#
# Both outcomes are metered, not just failures. An alarm on failures alone
# cannot tell "healthy" from "never configured" -- NullFeedMirror is equally
# silent. Comparing ok against failed is what proves the dual-write is live
# before reads move over.
# ---------------------------------------------------------------------------

# Gated because the deploy role needs logs:PutMetricFilter to create these, and
# that role is bootstrap IAM the dev stack deliberately does not manage. Without
# the gate a missing grant fails the whole apply, so an unrelated change cannot
# deploy either -- a bootstrap dependency should not be able to red the entire
# pipeline. Turn on once the grant is in place (see
# infra/terraform/docs/github-actions-deploy-role.md).
resource "aws_cloudwatch_log_metric_filter" "feed_mirror_ok" {
  count = var.feed_mirror_metrics_enabled ? 1 : 0

  name           = "${var.name_prefix}-feed-mirror-ok"
  log_group_name = aws_cloudwatch_log_group.lambda.name
  pattern        = "{ $.event = \"feed_mirror\" && $.outcome = \"ok\" }"

  metric_transformation {
    name          = "FeedMirrorOk"
    namespace     = "Seagull/SocialApi"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "feed_mirror_failed" {
  count = var.feed_mirror_metrics_enabled ? 1 : 0

  name           = "${var.name_prefix}-feed-mirror-failed"
  log_group_name = aws_cloudwatch_log_group.lambda.name
  pattern        = "{ $.event = \"feed_mirror\" && $.outcome = \"failed\" }"

  metric_transformation {
    name          = "FeedMirrorFailed"
    namespace     = "Seagull/SocialApi"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "feed_mirror_failed" {
  count = var.feed_mirror_metrics_enabled ? 1 : 0

  alarm_name          = "${var.name_prefix}-feed-mirror-failed"
  alarm_description   = "gulls Feed mirror is dropping writes; gulls is falling behind seagulls. Do not flip GULLS_FEED_READS while this is alarming."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.feed_mirror_failed[0].metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.feed_mirror_failed[0].metric_transformation[0].namespace
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  tags = local.common_tags
}
