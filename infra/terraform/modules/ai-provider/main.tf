locals {
  common_tags = merge(
    var.tags,
    {
      App = "ai-provider"
    },
  )

  table_arns = [
    aws_dynamodb_table.runs.arn,
    aws_dynamodb_table.run_events.arn,
    aws_dynamodb_table.usage_ledger.arn,
    aws_dynamodb_table.user_credit_ledger.arn,
    aws_dynamodb_table.server_credit_ledger.arn,
    aws_dynamodb_table.provider_configs.arn,
    aws_dynamodb_table.admin_audit_events.arn,
    aws_dynamodb_table.model_policies.arn,
    aws_dynamodb_table.budget_limits.arn,
  ]

  table_resources = concat(
    local.table_arns,
    [for arn in local.table_arns : "${arn}/index/*"],
  )
}

resource "aws_dynamodb_table" "runs" {
  name                        = "${var.name_prefix}-runs"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "run_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "actor_agent_id"
    type = "S"
  }

  attribute {
    name = "task_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "actor-created-at-index"
    hash_key        = "actor_agent_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "task-created-at-index"
    hash_key        = "task_id"
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

resource "aws_dynamodb_table" "run_events" {
  name                        = "${var.name_prefix}-run-events"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "event_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "event_id"
    type = "S"
  }

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "run-created-at-index"
    hash_key        = "run_id"
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

resource "aws_dynamodb_table" "usage_ledger" {
  name                        = "${var.name_prefix}-usage-ledger"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "usage_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "usage_id"
    type = "S"
  }

  attribute {
    name = "owner_user_id"
    type = "S"
  }

  attribute {
    name = "agent_id"
    type = "S"
  }

  attribute {
    name = "run_id"
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

  global_secondary_index {
    name            = "agent-created-at-index"
    hash_key        = "agent_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "run-created-at-index"
    hash_key        = "run_id"
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

resource "aws_dynamodb_table" "user_credit_ledger" {
  name                        = "${var.name_prefix}-user-credit-ledger"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "entry_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "entry_id"
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

resource "aws_dynamodb_table" "server_credit_ledger" {
  name                        = "${var.name_prefix}-server-credit-ledger"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "entry_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "entry_id"
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

resource "aws_dynamodb_table" "provider_configs" {
  name                        = "${var.name_prefix}-provider-configs"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "provider"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "provider"
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

resource "aws_dynamodb_table" "admin_audit_events" {
  name                        = "${var.name_prefix}-admin-audit-events"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "audit_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "audit_id"
    type = "S"
  }

  attribute {
    name = "admin_actor_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "admin-created-at-index"
    hash_key        = "admin_actor_id"
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

resource "aws_dynamodb_table" "model_policies" {
  name                        = "${var.name_prefix}-model-policies"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "policy_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "policy_id"
    type = "S"
  }

  attribute {
    name = "scope_key"
    type = "S"
  }

  attribute {
    name = "updated_at"
    type = "S"
  }

  global_secondary_index {
    name            = "scope-updated-at-index"
    hash_key        = "scope_key"
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

resource "aws_dynamodb_table" "budget_limits" {
  name                        = "${var.name_prefix}-budget-limits"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "budget_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "budget_id"
    type = "S"
  }

  attribute {
    name = "scope_key"
    type = "S"
  }

  attribute {
    name = "updated_at"
    type = "S"
  }

  global_secondary_index {
    name            = "scope-updated-at-index"
    hash_key        = "scope_key"
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
  timeout          = 15
  memory_size      = 256

  environment {
    variables = {
      AI_ADMIN_AUDIT_EVENTS_TABLE   = aws_dynamodb_table.admin_audit_events.name
      AI_BUDGET_LIMITS_TABLE        = aws_dynamodb_table.budget_limits.name
      AI_MODEL_POLICIES_TABLE       = aws_dynamodb_table.model_policies.name
      AI_PROVIDER_ADMIN_SECRET      = var.admin_secret
      AI_PROVIDER_CONFIGS_TABLE     = aws_dynamodb_table.provider_configs.name
      AI_RUN_EVENTS_TABLE           = aws_dynamodb_table.run_events.name
      AI_RUNS_TABLE                 = aws_dynamodb_table.runs.name
      AI_SERVER_CREDIT_LEDGER_TABLE = aws_dynamodb_table.server_credit_ledger.name
      AI_USAGE_LEDGER_TABLE         = aws_dynamodb_table.usage_ledger.name
      AI_USER_CREDIT_LEDGER_TABLE   = aws_dynamodb_table.user_credit_ledger.name
      APP_NAME                      = var.name_prefix
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
    allow_headers = ["authorization", "content-type", "x-seagull-admin-secret"]
    allow_methods = ["GET", "POST", "OPTIONS"]
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

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  tags = local.common_tags
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromAiProviderApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
