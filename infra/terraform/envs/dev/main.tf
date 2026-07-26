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
  social_auth_guard_name = "${var.project}-${var.environment}-social-auth-domain-guard"
  social_cognito_domain  = var.social_cognito_domain_prefix != "" ? var.social_cognito_domain_prefix : "${var.project}-${var.environment}-social-${data.aws_caller_identity.current.account_id}"
  social_api_prefix      = "${var.project}-${var.environment}-social-api"
  web_prefix             = "${var.project}-${var.environment}-web"
  web_bucket_name        = "${local.web_prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  web_dist_dir           = "${path.module}/../../../../packages/seagulls/apps/web/dist"
  landing_dist_dir       = "${path.module}/../../../../packages/seagulls/apps/landing/dist"
  payload_objects_bucket = "${var.project}-${var.environment}-msg-payloads-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  # Built by scripts/build-message-hub.sh: lambda_function.py + vendored
  # message_hub and seagull_policy packages (the lambda is a thin adapter
  # over the domain service and imports them at runtime).
  message_hub_api_package = "${path.module}/.terraform/build/message-hub-api/package"
  agent_worker_src        = "${path.module}/../../../../packages/gulls/services/message-hub/aws/agent_worker.py"
  router_bootstrap        = "${path.module}/.terraform/build/message-router/bootstrap"
  mcp_connector_package   = "${path.module}/.terraform/build/mcp-connector/package"
  ai_provider_package     = "${path.module}/.terraform/build/ai-provider/package"
  safety_gateway_package  = "${path.module}/.terraform/build/safety-gateway/package"
  social_auth_guard_src   = "${path.module}/../../../../packages/seagulls/services/social-api/aws/auth_domain_guard.py"
  social_api_package      = "${path.module}/.terraform/build/social-api/package"
  message_hub_tags = {
    Project     = var.project
    Environment = var.environment
  }
  message_hub_storage_resources = concat(
    values(module.message_hub_storage.table_arns),
    [for arn in values(module.message_hub_storage.table_arns) : "${arn}/index/*"],
  )
  message_hub_api_secret_arns = [
    aws_secretsmanager_secret.safety_gateway_admin.arn,
    aws_secretsmanager_secret.guest_status_signing.arn,
  ]
  agent_worker_secret_arns = [
    aws_secretsmanager_secret.agent_webhook_signing.arn,
  ]
  mcp_connector_secret_arns = concat(
    [aws_secretsmanager_secret.mcp_connector_admin.arn],
    var.mcp_dev_token == "" ? [] : [aws_secretsmanager_secret.mcp_dev_token[0].arn],
  )
}

data "aws_caller_identity" "current" {}

data "aws_route53_zone" "root" {
  name         = var.root_domain
  private_zone = false
}

resource "aws_secretsmanager_secret" "agent_webhook_signing" {
  name = "${local.message_hub_prefix}/runtime/agent-webhook-signing-secret"

  tags = merge(local.message_hub_tags, {
    App = "message-hub-agent-worker"
  })
}

resource "aws_secretsmanager_secret_version" "agent_webhook_signing" {
  secret_id     = aws_secretsmanager_secret.agent_webhook_signing.id
  secret_string = var.agent_webhook_signing_secret
}

resource "aws_secretsmanager_secret" "guest_status_signing" {
  name = "${local.message_hub_prefix}/runtime/guest-status-signing-secret"

  tags = merge(local.message_hub_tags, {
    App = "message-hub-api"
  })
}

resource "aws_secretsmanager_secret_version" "guest_status_signing" {
  secret_id     = aws_secretsmanager_secret.guest_status_signing.id
  secret_string = var.guest_status_signing_secret
}

resource "aws_secretsmanager_secret" "safety_gateway_admin" {
  name = "${local.safety_gateway_prefix}/runtime/admin-secret"

  tags = merge(local.message_hub_tags, {
    App = "safety-gateway"
  })
}

resource "aws_secretsmanager_secret_version" "safety_gateway_admin" {
  secret_id     = aws_secretsmanager_secret.safety_gateway_admin.id
  secret_string = var.safety_gateway_admin_secret
}

resource "aws_secretsmanager_secret" "ai_provider_admin" {
  name = "${local.ai_provider_prefix}/runtime/admin-secret"

  tags = merge(local.message_hub_tags, {
    App = "ai-provider"
  })
}

resource "aws_secretsmanager_secret_version" "ai_provider_admin" {
  secret_id     = aws_secretsmanager_secret.ai_provider_admin.id
  secret_string = var.ai_provider_admin_secret
}

resource "aws_secretsmanager_secret" "mcp_connector_admin" {
  name = "${local.mcp_connector_prefix}/runtime/admin-secret"

  tags = merge(local.message_hub_tags, {
    App = "mcp-connector"
  })
}

resource "aws_secretsmanager_secret_version" "mcp_connector_admin" {
  secret_id     = aws_secretsmanager_secret.mcp_connector_admin.id
  secret_string = var.mcp_connector_admin_secret
}

resource "aws_secretsmanager_secret" "mcp_dev_token" {
  count = var.mcp_dev_token == "" ? 0 : 1

  name = "${local.mcp_connector_prefix}/runtime/dev-token"

  tags = merge(local.message_hub_tags, {
    App = "mcp-connector"
  })
}

resource "aws_secretsmanager_secret_version" "mcp_dev_token" {
  count = var.mcp_dev_token == "" ? 0 : 1

  secret_id     = aws_secretsmanager_secret.mcp_dev_token[0].id
  secret_string = var.mcp_dev_token
}

data "archive_file" "message_hub_api" {
  type        = "zip"
  source_dir  = local.message_hub_api_package
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

data "archive_file" "social_auth_guard" {
  type        = "zip"
  source_file = local.social_auth_guard_src
  output_path = "${path.module}/.terraform/build/social-auth-domain-guard.zip"
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
          "dynamodb:Scan",
          "dynamodb:UpdateItem"
        ]
        Resource = local.message_hub_storage_resources
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.agent_jobs.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = "${module.message_hub_storage.payload_objects_bucket_arn}/*"
      }
      ],
      [
        {
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue"]
          Resource = local.message_hub_api_secret_arns
        }
      ]
    )
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
      AGENTS_TABLE                    = module.message_hub_storage.table_names.agents
      AGENT_TOKENS_TABLE              = module.message_hub_storage.table_names.agent_tokens
      AGENT_JOBS_QUEUE_URL            = aws_sqs_queue.agent_jobs.url
      APP_NAME                        = local.message_hub_prefix
      DELIVERIES_TABLE                = module.message_hub_storage.table_names.deliveries
      FEED_EVENTS_TABLE               = module.message_hub_storage.table_names.feed_events
      FOLLOWS_TABLE                   = module.message_hub_storage.table_names.follows
      GUEST_STATUS_SIGNING_SECRET_ARN = aws_secretsmanager_secret.guest_status_signing.arn
      IDEMPOTENCY_TABLE               = module.message_hub_storage.table_names.idempotency_keys
      MESSAGES_TABLE                  = module.message_hub_storage.table_names.messages
      NOTIFICATIONS_TABLE             = module.message_hub_storage.table_names.notifications
      PAYLOAD_OBJECTS_BUCKET          = module.message_hub_storage.payload_objects_bucket_name
      PAYLOADS_TABLE                  = module.message_hub_storage.table_names.payloads
      POSTS_TABLE                     = module.message_hub_storage.table_names.posts
      ROOM_MEMBERSHIPS_TABLE          = module.message_hub_storage.table_names.room_memberships
      ROOMS_TABLE                     = module.message_hub_storage.table_names.rooms
      ROUTING_RULES_TABLE             = module.message_hub_storage.table_names.routing_rules
      SAFETY_BLOCKED_TERMS            = "unsafe:"
      SAFETY_GATEWAY_ADMIN_SECRET_ARN = aws_secretsmanager_secret.safety_gateway_admin.arn
      SAFETY_GATEWAY_URL              = module.safety_gateway.api_endpoint
      TASK_RESULTS_TABLE              = module.message_hub_storage.table_names.task_results
      TASKS_TABLE                     = module.message_hub_storage.table_names.tasks
      THREAD_SUMMARIES_TABLE          = module.message_hub_storage.table_names.thread_summaries
      THREADS_TABLE                   = module.message_hub_storage.table_names.threads
      TOOL_REQUESTS_TABLE             = module.message_hub_storage.table_names.tool_requests
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
    Statement = concat([
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
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:DeleteItem"
        ]
        Resource = [
          module.message_router.connections_table_arn,
          "${module.message_router.connections_table_arn}/index/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["execute-api:ManageConnections"]
        Resource = "${module.message_router.websocket_api_execution_arn}/*/POST/@connections/*"
      }
      ],
      [
        {
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue"]
          Resource = local.agent_worker_secret_arns
        }
      ]
    )
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
      AGENTS_TABLE                       = module.message_hub_storage.table_names.agents
      APP_NAME                           = "${local.message_hub_prefix}-agent-worker"
      CONNECTIONS_TABLE                  = module.message_router.connections_table_name
      DELIVERIES_TABLE                   = module.message_hub_storage.table_names.deliveries
      MESSAGES_TABLE                     = module.message_hub_storage.table_names.messages
      SEAGULL_WEBHOOK_SIGNING_SECRET_ARN = aws_secretsmanager_secret.agent_webhook_signing.arn
      WEBSOCKET_CALLBACK_URL             = module.message_router.websocket_callback_url
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
    Statement = concat([
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
      ],
      [
        {
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue"]
          Resource = local.mcp_connector_secret_arns
        }
      ]
    )
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
        APP_NAME                         = local.mcp_connector_prefix
        CONNECTOR_TOKEN_ADMIN_SECRET_ARN = aws_secretsmanager_secret.mcp_connector_admin.arn
        CONNECTOR_TOKENS_TABLE           = aws_dynamodb_table.mcp_connector_tokens.name
        MCP_AUTHORIZATION_SERVER         = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.mcp_connector.id}"
        MCP_COGNITO_AUTHORIZATION_URL    = "https://${aws_cognito_user_pool_domain.mcp_connector.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/authorize"
        MCP_COGNITO_CLIENT_ID            = aws_cognito_user_pool_client.mcp_connector_chatgpt.id
        MCP_COGNITO_REGION               = var.aws_region
        MCP_COGNITO_TOKEN_URL            = "https://${aws_cognito_user_pool_domain.mcp_connector.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token"
        MCP_COGNITO_USER_POOL_ID         = aws_cognito_user_pool.mcp_connector.id
        MCP_CORS_ALLOWED_ORIGINS         = join(",", var.mcp_allowed_origins)
        MCP_DEV_OWNER_USER_ID            = var.mcp_dev_owner_user_id
        MCP_NO_AUTH_ENABLED              = tostring(var.environment == "dev" && var.mcp_no_auth_enabled)
        MCP_NO_AUTH_OWNER_USER_ID        = var.mcp_no_auth_owner_user_id
        MCP_NO_AUTH_SCOPES               = join(",", var.mcp_no_auth_scopes)
        MCP_RESOURCE_URI                 = "https://${var.mcp_domain_name}/mcp"
        MESSAGE_API_URL                  = "https://${var.message_api_domain}"
      },
      var.mcp_dev_token == "" ? {} : {
        MCP_DEV_TOKEN_ARN = aws_secretsmanager_secret.mcp_dev_token[0].arn
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

# Explicit routes for the guest-reachable public agent URL paths: stage-level
# route_settings only throttle named routes, never $default, so these exist
# purely to hang the tighter guest throttles on. Same integration, same
# lambda dispatch.
resource "aws_apigatewayv2_route" "public_agent_send" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "POST /agents/{name}/messages"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "public_agent_message_status" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /agents/{name}/messages/{deliveryId}"
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

  route_settings {
    route_key              = aws_apigatewayv2_route.public_agent_send.route_key
    throttling_burst_limit = var.public_agent_send_throttling_burst_limit
    throttling_rate_limit  = var.public_agent_send_throttling_rate_limit
  }

  route_settings {
    route_key              = aws_apigatewayv2_route.public_agent_message_status.route_key
    throttling_burst_limit = var.public_agent_status_throttling_burst_limit
    throttling_rate_limit  = var.public_agent_status_throttling_rate_limit
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
  payload_objects_bucket_name    = local.payload_objects_bucket
  tags                           = local.message_hub_tags
}

module "safety_gateway" {
  source = "../../modules/safety-gateway"

  name_prefix             = local.safety_gateway_prefix
  lambda_package_path     = data.archive_file.safety_gateway.output_path
  lambda_source_code_hash = data.archive_file.safety_gateway.output_base64sha256
  admin_secret_arn        = aws_secretsmanager_secret.safety_gateway_admin.arn

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
  admin_secret_arn        = aws_secretsmanager_secret.ai_provider_admin.arn
  jwt_issuer              = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.social_web.id}"
  jwt_audience            = [aws_cognito_user_pool_client.social_web.id]
  message_hub_api_url     = "https://${var.message_api_domain}"

  point_in_time_recovery_enabled = var.dynamodb_point_in_time_recovery_enabled
  deletion_protection_enabled    = var.dynamodb_deletion_protection_enabled
  api_throttling_burst_limit     = var.api_throttling_burst_limit
  api_throttling_rate_limit      = var.api_throttling_rate_limit
  tags                           = local.message_hub_tags
}

resource "aws_ses_domain_identity" "social_auth" {
  domain = var.root_domain
}

resource "aws_route53_record" "social_auth_ses_verification" {
  zone_id = data.aws_route53_zone.root.zone_id
  name    = "_amazonses.${aws_ses_domain_identity.social_auth.domain}"
  type    = "TXT"
  ttl     = 600
  records = [aws_ses_domain_identity.social_auth.verification_token]
}

resource "aws_ses_domain_identity_verification" "social_auth" {
  domain = aws_ses_domain_identity.social_auth.domain

  depends_on = [aws_route53_record.social_auth_ses_verification]
}

resource "aws_ses_domain_dkim" "social_auth" {
  domain = aws_ses_domain_identity.social_auth.domain
}

resource "aws_route53_record" "social_auth_ses_dkim" {
  count = 3

  zone_id = data.aws_route53_zone.root.zone_id
  name    = "${aws_ses_domain_dkim.social_auth.dkim_tokens[count.index]}._domainkey"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_ses_domain_dkim.social_auth.dkim_tokens[count.index]}.dkim.amazonses.com"]
}

resource "aws_iam_role" "social_auth_guard" {
  name = "${local.social_auth_guard_name}-role"

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

  tags = merge(local.message_hub_tags, {
    App = "social-auth-domain-guard"
  })
}

resource "aws_cloudwatch_log_group" "social_auth_guard" {
  name              = "/aws/lambda/${local.social_auth_guard_name}"
  retention_in_days = 7

  tags = merge(local.message_hub_tags, {
    App = "social-auth-domain-guard"
  })
}

resource "aws_iam_role_policy" "social_auth_guard" {
  name = "${local.social_auth_guard_name}-policy"
  role = aws_iam_role.social_auth_guard.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.social_auth_guard.arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "social_auth_guard" {
  function_name    = local.social_auth_guard_name
  role             = aws_iam_role.social_auth_guard.arn
  handler          = "auth_domain_guard.handler"
  runtime          = "python3.13"
  filename         = data.archive_file.social_auth_guard.output_path
  source_code_hash = data.archive_file.social_auth_guard.output_base64sha256
  timeout          = 5
  memory_size      = 128

  depends_on = [
    aws_cloudwatch_log_group.social_auth_guard,
    aws_iam_role_policy.social_auth_guard,
  ]

  tags = merge(local.message_hub_tags, {
    App = "social-auth-domain-guard"
  })
}

resource "aws_lambda_permission" "social_auth_guard_cognito" {
  statement_id   = "AllowExecutionFromCognito"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.social_auth_guard.function_name
  principal      = "cognito-idp.amazonaws.com"
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_cognito_user_pool" "social_web" {
  name           = "${local.social_api_prefix}-users"
  user_pool_tier = "ESSENTIALS"

  auto_verified_attributes = ["email"]
  username_attributes      = ["email"]

  sign_in_policy {
    # Cognito won't remove PASSWORD from an existing password-based pool.
    # The web app only requests EMAIL_OTP, and new registrations omit passwords.
    allowed_first_auth_factors = ["PASSWORD", "EMAIL_OTP"]
  }

  lambda_config {
    pre_authentication = aws_lambda_function.social_auth_guard.arn
    pre_sign_up        = aws_lambda_function.social_auth_guard.arn
  }

  email_configuration {
    email_sending_account = "DEVELOPER"
    from_email_address    = "Seagulls <no-reply@${var.root_domain}>"
    source_arn            = aws_ses_domain_identity_verification.social_auth.arn
  }

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

  depends_on = [aws_lambda_permission.social_auth_guard_cognito]
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
    "ALLOW_USER_AUTH",
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
  message_api_url         = "https://${var.message_api_domain}"

  ai_provider_api_url          = module.ai_provider.api_endpoint
  ai_provider_admin_secret_arn = aws_secretsmanager_secret.ai_provider_admin.arn
  ai_reply_provider            = var.ai_reply_provider
  ai_reply_model               = var.ai_reply_model

  # One network identity per human, in the same namespace as their agents,
  # rather than one proxy per agent domain they happen to chat.
  human_proxy_domain = var.root_domain

  # The deploy role has logs:PutMetricFilter, so the Feed mirror metrics and
  # their alarm can be created. Without them the mirror runs unmeasured and the
  # dual-write cannot be verified, which is step 1 of the cutover runbook.
  feed_mirror_metrics_enabled = true

  # Base Feed records now come from gulls. The mirror was verified live
  # (feed_mirror outcome=ok, alarm quiet) and the backfill brought all six
  # tables to exact parity, so gulls holds everything seagulls does.
  #
  # Which posts appear and in what order stays a seagulls projection; only what
  # a post *is* moves. FallbackFeedSource still serves the seagulls copy on a
  # gulls miss or failure, so this degrades rather than empties a feed.
  gulls_feed_reads_enabled = true

  # Chat content lives in the hub's messages table. Reads stay on the stored
  # seagulls copy until gulls_chat_reads_enabled is flipped.
  gulls_messages_table_name = module.message_hub_storage.table_names.messages
  gulls_messages_table_arn  = module.message_hub_storage.table_arns.messages

  # Feed source of truth is moving to gulls; dual-write into its tables while
  # seagulls still serves reads from its own.
  gulls_feed_table_names = {
    posts            = module.message_hub_storage.table_names.posts
    follows          = module.message_hub_storage.table_names.follows
    rooms            = module.message_hub_storage.table_names.rooms
    room_memberships = module.message_hub_storage.table_names.room_memberships
    feed_events      = module.message_hub_storage.table_names.feed_events
    notifications    = module.message_hub_storage.table_names.notifications
  }
  gulls_feed_table_arns = [
    module.message_hub_storage.table_arns.posts,
    module.message_hub_storage.table_arns.follows,
    module.message_hub_storage.table_arns.rooms,
    module.message_hub_storage.table_arns.room_memberships,
    module.message_hub_storage.table_arns.feed_events,
    module.message_hub_storage.table_arns.notifications,
  ]

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

  # Apex public agent URLs (M3.1): route /agents/* and /.well-known/* on the
  # landing distribution to the message API origin.
  message_api_origin_domain = var.message_api_domain
  social_api_url            = module.social_api.api_endpoint
  ai_provider_api_url       = module.ai_provider.api_endpoint
  auth_mode                 = "cognito"
  auth_issuer               = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.social_web.id}"
  auth_hosted_domain        = "${aws_cognito_user_pool_domain.social_web.domain}.auth.${var.aws_region}.amazoncognito.com"
  auth_client_id            = aws_cognito_user_pool_client.social_web.id
  auth_redirect_uri         = "https://${var.web_domain_name}/auth/callback"
  auth_logout_uri           = "https://${var.web_domain_name}/register"

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
