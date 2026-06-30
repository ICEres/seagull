provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile != "" ? var.aws_profile : null
}

provider "aws" {
  alias   = "us_east_1"
  region  = "us-east-1"
  profile = var.aws_profile != "" ? var.aws_profile : null
}

locals {
  message_api_prefix     = "${var.project}-${var.environment}-message-hub-api"
  message_hub_prefix     = "${var.project}-${var.environment}-message-hub"
  message_router_prefix  = "${var.project}-${var.environment}-message-router"
  ai_provider_prefix     = "${var.project}-${var.environment}-ai-provider"
  mcp_connector_prefix   = "${var.project}-${var.environment}-mcp-connector"
  mcp_cognito_domain     = var.mcp_cognito_domain_prefix != "" ? var.mcp_cognito_domain_prefix : "${var.project}-${var.environment}-mcp-${data.aws_caller_identity.current.account_id}"
  safety_gateway_prefix  = "${var.project}-${var.environment}-safety-gateway"
  social_cognito_domain  = var.social_cognito_domain_prefix != "" ? var.social_cognito_domain_prefix : "${var.project}-${var.environment}-social-${data.aws_caller_identity.current.account_id}"
  social_api_prefix      = "${var.project}-${var.environment}-social-api"
  web_prefix             = "${var.project}-${var.environment}-web"
  web_bucket_name        = "${local.web_prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  web_dist_dir           = "${path.module}/../../../../apps/web/dist"
  landing_dist_dir       = "${path.module}/../../../../apps/landing"
  lambda_src             = "${path.module}/../../../../apps/message-hub/aws/lambda_function.py"
  agent_worker_src       = "${path.module}/../../../../apps/message-hub/aws/agent_worker.py"
  router_bootstrap       = "${path.module}/.terraform/build/message-router/bootstrap"
  mcp_connector_package  = "${path.module}/.terraform/build/mcp-connector/package"
  ai_provider_package    = "${path.module}/.terraform/build/ai-provider/package"
  safety_gateway_package = "${path.module}/.terraform/build/safety-gateway/package"
  social_api_package     = "${path.module}/.terraform/build/social-api/package"
  message_hub_tags = {
    Project     = var.project
    Environment = var.environment
  }
  message_hub_storage_resources = concat(
    values(module.message_hub_storage.table_arns),
    [for arn in values(module.message_hub_storage.table_arns) : "${arn}/index/*"],
  )
}

data "aws_caller_identity" "current" {}

data "aws_route53_zone" "root" {
  name         = var.root_domain
  private_zone = false
}

data "archive_file" "message_hub_api" {
  type        = "zip"
  source_file = local.lambda_src
  output_path = "${path.module}/.terraform/build/message-hub-api.zip"
}

data "archive_file" "agent_worker" {
  type        = "zip"
  source_file = local.agent_worker_src
  output_path = "${path.module}/.terraform/build/message-hub-agent-worker.zip"
}

data "archive_file" "message_router" {
  type        = "zip"
  source_file = local.router_bootstrap
  output_path = "${path.module}/.terraform/build/message-router.zip"
}

data "archive_file" "mcp_connector" {
  type        = "zip"
  source_dir  = local.mcp_connector_package
  output_path = "${path.module}/.terraform/build/mcp-connector.zip"
}

data "archive_file" "ai_provider" {
  type        = "zip"
  source_dir  = local.ai_provider_package
  output_path = "${path.module}/.terraform/build/ai-provider.zip"
}

data "archive_file" "safety_gateway" {
  type        = "zip"
  source_dir  = local.safety_gateway_package
  output_path = "${path.module}/.terraform/build/safety-gateway.zip"
}

data "archive_file" "social_api" {
  type        = "zip"
  source_dir  = local.social_api_package
  output_path = "${path.module}/.terraform/build/social-api.zip"
}

resource "aws_iam_role" "lambda" {
  name = "${local.message_api_prefix}-lambda-role"

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

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-api"
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.message_api_prefix}"
  retention_in_days = 7

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-api"
  }
}

resource "aws_iam_role_policy" "lambda" {
  name = "${local.message_api_prefix}-lambda-policy"
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
          "dynamodb:Scan",
          "dynamodb:TransactWriteItems",
          "dynamodb:UpdateItem"
        ]
        Resource = local.message_hub_storage_resources
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.agent_jobs.arn
      }
    ]
  })
}

resource "aws_lambda_function" "message_hub_api" {
  function_name    = local.message_api_prefix
  role             = aws_iam_role.lambda.arn
  handler          = "lambda_function.handler"
  runtime          = "python3.13"
  filename         = data.archive_file.message_hub_api.output_path
  source_code_hash = data.archive_file.message_hub_api.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      AGENTS_TABLE                = module.message_hub_storage.table_names.agents
      AGENT_TOKENS_TABLE          = module.message_hub_storage.table_names.agent_tokens
      AGENT_JOBS_QUEUE_URL        = aws_sqs_queue.agent_jobs.url
      APP_NAME                    = local.message_hub_prefix
      DELIVERIES_TABLE            = module.message_hub_storage.table_names.deliveries
      IDEMPOTENCY_TABLE           = module.message_hub_storage.table_names.idempotency_keys
      MESSAGES_TABLE              = module.message_hub_storage.table_names.messages
      ROUTING_RULES_TABLE         = module.message_hub_storage.table_names.routing_rules
      SAFETY_BLOCKED_TERMS        = "unsafe:"
      SAFETY_GATEWAY_ADMIN_SECRET = var.safety_gateway_admin_secret
      SAFETY_GATEWAY_URL          = module.safety_gateway.api_endpoint
      TASK_RESULTS_TABLE          = module.message_hub_storage.table_names.task_results
      TASKS_TABLE                 = module.message_hub_storage.table_names.tasks
      THREAD_SUMMARIES_TABLE      = module.message_hub_storage.table_names.thread_summaries
      THREADS_TABLE               = module.message_hub_storage.table_names.threads
      TOOL_REQUESTS_TABLE         = module.message_hub_storage.table_names.tool_requests
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda,
  ]

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-api"
  }
}

resource "aws_sqs_queue" "agent_jobs_dlq" {
  name                        = "${local.message_hub_prefix}-agent-jobs-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-agent-worker"
  }
}

resource "aws_sqs_queue" "agent_jobs" {
  name                        = "${local.message_hub_prefix}-agent-jobs.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  visibility_timeout_seconds  = 60
  message_retention_seconds   = 345600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.agent_jobs_dlq.arn
    maxReceiveCount     = 5
  })

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-agent-worker"
  }
}

resource "aws_iam_role" "agent_worker" {
  name = "${local.message_hub_prefix}-agent-worker-role"

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

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-agent-worker"
  }
}

resource "aws_cloudwatch_log_group" "agent_worker" {
  name              = "/aws/lambda/${local.message_hub_prefix}-agent-worker"
  retention_in_days = 7

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-agent-worker"
  }
}

resource "aws_iam_role_policy" "agent_worker" {
  name = "${local.message_hub_prefix}-agent-worker-policy"
  role = aws_iam_role.agent_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.agent_worker.arn}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:UpdateItem"
        ]
        Resource = values(module.message_hub_storage.table_arns)
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.agent_jobs.arn
      }
    ]
  })
}

resource "aws_lambda_function" "agent_worker" {
  function_name    = "${local.message_hub_prefix}-agent-worker"
  role             = aws_iam_role.agent_worker.arn
  handler          = "agent_worker.handler"
  runtime          = "python3.13"
  filename         = data.archive_file.agent_worker.output_path
  source_code_hash = data.archive_file.agent_worker.output_base64sha256
  timeout          = 20
  memory_size      = 256

  environment {
    variables = {
      AGENTS_TABLE                   = module.message_hub_storage.table_names.agents
      APP_NAME                       = "${local.message_hub_prefix}-agent-worker"
      DELIVERIES_TABLE               = module.message_hub_storage.table_names.deliveries
      MESSAGES_TABLE                 = module.message_hub_storage.table_names.messages
      SEAGULL_WEBHOOK_SIGNING_SECRET = var.agent_webhook_signing_secret
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.agent_worker,
    aws_iam_role_policy.agent_worker,
  ]

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-agent-worker"
  }
}

resource "aws_lambda_event_source_mapping" "agent_jobs" {
  event_source_arn        = aws_sqs_queue.agent_jobs.arn
  function_name           = aws_lambda_function.agent_worker.arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]
}

resource "aws_dynamodb_table" "mcp_connector_tokens" {
  name         = "${local.mcp_connector_prefix}-tokens"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "token_id"

  attribute {
    name = "token_id"
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

  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.dynamodb_point_in_time_recovery_enabled
  }

  deletion_protection_enabled = var.dynamodb_deletion_protection_enabled

  server_side_encryption {
    enabled = true
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_cognito_user_pool" "mcp_connector" {
  name = "${local.mcp_connector_prefix}-users"

  auto_verified_attributes = ["email"]

  username_configuration {
    case_sensitive = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = false
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  schema {
    name                = "sg_owner_id"
    attribute_data_type = "String"
    mutable             = true
    required            = false

    string_attribute_constraints {
      min_length = 1
      max_length = 256
    }
  }

  schema {
    name                = "sg_handles"
    attribute_data_type = "String"
    mutable             = true
    required            = false

    string_attribute_constraints {
      min_length = 1
      max_length = 2048
    }
  }

  schema {
    name                = "sg_scopes"
    attribute_data_type = "String"
    mutable             = true
    required            = false

    string_attribute_constraints {
      min_length = 1
      max_length = 512
    }
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_cognito_user_pool_domain" "mcp_connector" {
  domain       = local.mcp_cognito_domain
  user_pool_id = aws_cognito_user_pool.mcp_connector.id
}

resource "aws_cognito_user_pool_client" "mcp_connector_chatgpt" {
  name         = "${local.mcp_connector_prefix}-chatgpt"
  user_pool_id = aws_cognito_user_pool.mcp_connector.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  callback_urls                        = var.chatgpt_oauth_redirect_uris
  logout_urls                          = ["https://chatgpt.com"]
  supported_identity_providers         = ["COGNITO"]
  prevent_user_existence_errors        = "ENABLED"
  access_token_validity                = 1
  id_token_validity                    = 1
  refresh_token_validity               = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

resource "aws_iam_role" "mcp_connector" {
  name = "${local.mcp_connector_prefix}-lambda-role"

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

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_cloudwatch_log_group" "mcp_connector" {
  name              = "/aws/lambda/${local.mcp_connector_prefix}"
  retention_in_days = 7

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_iam_role_policy" "mcp_connector" {
  name = "${local.mcp_connector_prefix}-lambda-policy"
  role = aws_iam_role.mcp_connector.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.mcp_connector.arn}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          aws_dynamodb_table.mcp_connector_tokens.arn,
          "${aws_dynamodb_table.mcp_connector_tokens.arn}/index/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["cognito-idp:AdminGetUser"]
        Resource = aws_cognito_user_pool.mcp_connector.arn
      }
    ]
  })
}

resource "aws_lambda_function" "mcp_connector" {
  function_name    = local.mcp_connector_prefix
  role             = aws_iam_role.mcp_connector.arn
  handler          = "lambda_function.handler"
  runtime          = "python3.13"
  filename         = data.archive_file.mcp_connector.output_path
  source_code_hash = data.archive_file.mcp_connector.output_base64sha256
  timeout          = 15
  memory_size      = 256

  environment {
    variables = merge(
      {
        APP_NAME                      = local.mcp_connector_prefix
        CONNECTOR_TOKEN_ADMIN_SECRET  = var.mcp_connector_admin_secret
        CONNECTOR_TOKENS_TABLE        = aws_dynamodb_table.mcp_connector_tokens.name
        MCP_AUTHORIZATION_SERVER      = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.mcp_connector.id}"
        MCP_COGNITO_AUTHORIZATION_URL = "https://${aws_cognito_user_pool_domain.mcp_connector.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/authorize"
        MCP_COGNITO_CLIENT_ID         = aws_cognito_user_pool_client.mcp_connector_chatgpt.id
        MCP_COGNITO_REGION            = var.aws_region
        MCP_COGNITO_TOKEN_URL         = "https://${aws_cognito_user_pool_domain.mcp_connector.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token"
        MCP_COGNITO_USER_POOL_ID      = aws_cognito_user_pool.mcp_connector.id
        MCP_CORS_ALLOWED_ORIGINS      = join(",", var.mcp_allowed_origins)
        MCP_DEV_OWNER_USER_ID         = var.mcp_dev_owner_user_id
        MCP_NO_AUTH_ENABLED           = tostring(var.environment == "dev" && var.mcp_no_auth_enabled)
        MCP_NO_AUTH_OWNER_USER_ID     = var.mcp_no_auth_owner_user_id
        MCP_NO_AUTH_SCOPES            = join(",", var.mcp_no_auth_scopes)
        MCP_RESOURCE_URI              = "https://${var.mcp_domain_name}/mcp"
        MESSAGE_API_URL               = "https://${var.message_api_domain}"
      },
      var.mcp_dev_token == "" ? {} : {
        MCP_DEV_TOKEN = var.mcp_dev_token
      },
      length(var.mcp_dev_agent_handles) == 0 ? {} : {
        MCP_DEV_AGENT_HANDLES = join(",", var.mcp_dev_agent_handles)
      },
      length(var.mcp_no_auth_agent_handles) == 0 ? {} : {
        MCP_NO_AUTH_AGENT_HANDLES = join(",", var.mcp_no_auth_agent_handles)
      }
    )
  }

  depends_on = [
    aws_cloudwatch_log_group.mcp_connector,
    aws_iam_role_policy.mcp_connector,
  ]

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_apigatewayv2_api" "mcp_connector" {
  name          = "${local.mcp_connector_prefix}-http"
  protocol_type = "HTTP"

  cors_configuration {
    allow_headers = [
      "authorization",
      "content-type",
      "mcp-protocol-version",
      "mcp-session-id",
      "x-seagull-admin-secret"
    ]
    allow_methods = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_origins = var.mcp_allowed_origins
    max_age       = 300
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_apigatewayv2_integration" "mcp_connector" {
  api_id                 = aws_apigatewayv2_api.mcp_connector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.mcp_connector.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "mcp_connector_default" {
  api_id    = aws_apigatewayv2_api.mcp_connector.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.mcp_connector.id}"
}

resource "aws_apigatewayv2_stage" "mcp_connector" {
  api_id      = aws_apigatewayv2_api.mcp_connector.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = var.api_throttling_burst_limit
    throttling_rate_limit  = var.api_throttling_rate_limit
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_lambda_permission" "mcp_connector_api_gateway" {
  statement_id  = "AllowExecutionFromMcpConnectorGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mcp_connector.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.mcp_connector.execution_arn}/*/*"
}

resource "aws_acm_certificate" "mcp_connector" {
  domain_name       = var.mcp_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_route53_record" "mcp_connector_certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.mcp_connector.domain_validation_options : option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.root.zone_id
}

resource "aws_acm_certificate_validation" "mcp_connector" {
  certificate_arn         = aws_acm_certificate.mcp_connector.arn
  validation_record_fqdns = [for record in aws_route53_record.mcp_connector_certificate_validation : record.fqdn]
}

resource "aws_apigatewayv2_domain_name" "mcp_connector" {
  domain_name = var.mcp_domain_name

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.mcp_connector.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "mcp-connector"
  }
}

resource "aws_apigatewayv2_api_mapping" "mcp_connector" {
  api_id      = aws_apigatewayv2_api.mcp_connector.id
  domain_name = aws_apigatewayv2_domain_name.mcp_connector.id
  stage       = aws_apigatewayv2_stage.mcp_connector.id
}

resource "aws_route53_record" "mcp_connector" {
  name    = var.mcp_domain_name
  type    = "A"
  zone_id = data.aws_route53_zone.root.zone_id

  alias {
    evaluate_target_health = false
    name                   = aws_apigatewayv2_domain_name.mcp_connector.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.mcp_connector.domain_name_configuration[0].hosted_zone_id
  }
}

resource "aws_apigatewayv2_api" "http" {
  name          = "${local.message_api_prefix}-http"
  protocol_type = "HTTP"

  cors_configuration {
    allow_headers = ["content-type"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_origins = ["*"]
    max_age       = 300
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-api"
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.message_hub_api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "$default"
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

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-api"
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.message_hub_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

resource "aws_acm_certificate" "message_api" {
  domain_name       = var.message_api_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-api"
  }
}

resource "aws_route53_record" "message_api_certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.message_api.domain_validation_options : option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.root.zone_id
}

resource "aws_acm_certificate_validation" "message_api" {
  certificate_arn         = aws_acm_certificate.message_api.arn
  validation_record_fqdns = [for record in aws_route53_record.message_api_certificate_validation : record.fqdn]
}

resource "aws_apigatewayv2_domain_name" "message_api" {
  domain_name = var.message_api_domain

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.message_api.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = {
    Project     = var.project
    Environment = var.environment
    App         = "message-hub-api"
  }
}

resource "aws_apigatewayv2_api_mapping" "message_api" {
  api_id      = aws_apigatewayv2_api.http.id
  domain_name = aws_apigatewayv2_domain_name.message_api.id
  stage       = aws_apigatewayv2_stage.default.id
}

resource "aws_route53_record" "message_api" {
  name    = var.message_api_domain
  type    = "A"
  zone_id = data.aws_route53_zone.root.zone_id

  alias {
    evaluate_target_health = false
    name                   = aws_apigatewayv2_domain_name.message_api.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.message_api.domain_name_configuration[0].hosted_zone_id
  }
}

module "message_hub_storage" {
  source = "../../modules/message-hub"

  name_prefix                    = local.message_hub_prefix
  point_in_time_recovery_enabled = var.dynamodb_point_in_time_recovery_enabled
  deletion_protection_enabled    = var.dynamodb_deletion_protection_enabled
  tags                           = local.message_hub_tags
}

module "safety_gateway" {
  source = "../../modules/safety-gateway"

  name_prefix             = local.safety_gateway_prefix
  lambda_package_path     = data.archive_file.safety_gateway.output_path
  lambda_source_code_hash = data.archive_file.safety_gateway.output_base64sha256
  admin_secret            = var.safety_gateway_admin_secret

  point_in_time_recovery_enabled = var.dynamodb_point_in_time_recovery_enabled
  deletion_protection_enabled    = var.dynamodb_deletion_protection_enabled
  api_throttling_burst_limit     = var.api_throttling_burst_limit
  api_throttling_rate_limit      = var.api_throttling_rate_limit
  tags                           = local.message_hub_tags
}

module "ai_provider" {
  source = "../../modules/ai-provider"

  name_prefix             = local.ai_provider_prefix
  lambda_package_path     = data.archive_file.ai_provider.output_path
  lambda_source_code_hash = data.archive_file.ai_provider.output_base64sha256
  admin_secret            = var.ai_provider_admin_secret
  jwt_issuer              = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.social_web.id}"
  jwt_audience            = [aws_cognito_user_pool_client.social_web.id]

  point_in_time_recovery_enabled = var.dynamodb_point_in_time_recovery_enabled
  deletion_protection_enabled    = var.dynamodb_deletion_protection_enabled
  api_throttling_burst_limit     = var.api_throttling_burst_limit
  api_throttling_rate_limit      = var.api_throttling_rate_limit
  tags                           = local.message_hub_tags
}

resource "aws_cognito_user_pool" "social_web" {
  name = "${local.social_api_prefix}-users"

  auto_verified_attributes = ["email"]
  username_attributes      = ["email"]

  username_configuration {
    case_sensitive = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = false
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  tags = merge(
    local.message_hub_tags,
    {
      App = "social-api-auth"
    },
  )
}

resource "aws_cognito_user_pool_domain" "social_web" {
  domain       = local.social_cognito_domain
  user_pool_id = aws_cognito_user_pool.social_web.id
}

resource "aws_cognito_user_pool_client" "social_web" {
  name         = "${local.social_api_prefix}-web"
  user_pool_id = aws_cognito_user_pool.social_web.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  callback_urls = compact([
    "https://${var.web_domain_name}/auth/callback",
    var.admin_domain_name == "" ? "" : "https://${var.admin_domain_name}/auth/callback",
    "http://localhost:5173/auth/callback",
  ])
  logout_urls = compact([
    "https://${var.web_domain_name}/register",
    var.admin_domain_name == "" ? "" : "https://${var.admin_domain_name}/register",
    "http://localhost:5173/register",
  ])
  supported_identity_providers  = ["COGNITO"]
  prevent_user_existence_errors = "ENABLED"
  explicit_auth_flows = [
    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

module "social_api" {
  source = "../../modules/social-api"

  name_prefix             = local.social_api_prefix
  lambda_package_path     = data.archive_file.social_api.output_path
  lambda_source_code_hash = data.archive_file.social_api.output_base64sha256
  jwt_issuer              = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.social_web.id}"
  jwt_audience            = [aws_cognito_user_pool_client.social_web.id]

  point_in_time_recovery_enabled = var.dynamodb_point_in_time_recovery_enabled
  deletion_protection_enabled    = var.dynamodb_deletion_protection_enabled
  api_throttling_burst_limit     = var.api_throttling_burst_limit
  api_throttling_rate_limit      = var.api_throttling_rate_limit
  tags                           = local.message_hub_tags
}

module "web" {
  source = "../../modules/web"

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  name_prefix         = local.web_prefix
  bucket_name         = local.web_bucket_name
  domain_name         = var.web_domain_name
  admin_domain_name   = var.admin_domain_name
  landing_domain_name = var.landing_domain_name
  dist_dir            = local.web_dist_dir
  landing_dist_dir    = local.landing_dist_dir
  hosted_zone_id      = data.aws_route53_zone.root.zone_id
  message_api_url     = "https://${var.message_api_domain}"
  social_api_url      = module.social_api.api_endpoint
  ai_provider_api_url = module.ai_provider.api_endpoint
  auth_mode           = "cognito"
  auth_issuer         = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.social_web.id}"
  auth_hosted_domain  = "${aws_cognito_user_pool_domain.social_web.domain}.auth.${var.aws_region}.amazoncognito.com"
  auth_client_id      = aws_cognito_user_pool_client.social_web.id
  auth_redirect_uri   = "https://${var.web_domain_name}/auth/callback"
  auth_logout_uri     = "https://${var.web_domain_name}/register"

  tags = local.message_hub_tags
}

module "message_router" {
  source = "../../modules/message-router"

  name_prefix             = local.message_router_prefix
  lambda_package_path     = data.archive_file.message_router.output_path
  lambda_source_code_hash = data.archive_file.message_router.output_base64sha256
  agent_tokens_table_name = module.message_hub_storage.table_names.agent_tokens
  agent_tokens_table_arn  = module.message_hub_storage.table_arns.agent_tokens

  point_in_time_recovery_enabled = var.dynamodb_point_in_time_recovery_enabled
  deletion_protection_enabled    = var.dynamodb_deletion_protection_enabled
  api_throttling_burst_limit     = var.api_throttling_burst_limit
  api_throttling_rate_limit      = var.api_throttling_rate_limit
  tags                           = local.message_hub_tags
}
