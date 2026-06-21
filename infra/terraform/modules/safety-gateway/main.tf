locals {
  common_tags = merge(
    var.tags,
    {
      App = "safety-gateway"
    },
  )
}

resource "aws_dynamodb_table" "audit_events" {
  name                        = "${var.name_prefix}-audit-events"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "audit_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "audit_id"
    type = "S"
  }

  attribute {
    name = "actor_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "actor-created-at-index"
    hash_key        = "actor_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = false
  }

  server_side_encryption {
    enabled = true
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
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.audit_events.arn,
          "${aws_dynamodb_table.audit_events.arn}/index/*"
        ]
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
      APP_NAME                         = var.name_prefix
      AUDIT_TABLE                      = aws_dynamodb_table.audit_events.name
      SAFETY_BLOCKED_TERMS             = "unsafe:"
      SAFETY_MAX_EVENTS_PER_WINDOW     = "20"
      SAFETY_MAX_REPEATED_REPLIES      = "4"
      SAFETY_MAX_THREAD_DEPTH          = "12"
      SAFETY_RATE_LIMIT_WINDOW_SECONDS = "60"
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
    allow_headers = ["content-type"]
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

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  tags = local.common_tags
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromSafetyGatewayApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
