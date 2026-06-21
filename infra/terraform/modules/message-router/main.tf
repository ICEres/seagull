locals {
  common_tags = merge(
    var.tags,
    {
      App = "message-router"
    },
  )
}

resource "aws_dynamodb_table" "connections" {
  name                        = "${var.name_prefix}-connections"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "connection_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "connection_id"
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

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.common_tags
}

resource "aws_apigatewayv2_api" "websocket" {
  name                       = "${var.name_prefix}-websocket"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"

  tags = local.common_tags
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.websocket.id
  name        = "$default"
  auto_deploy = true

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
          "dynamodb:DeleteItem",
          "dynamodb:PutItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.connections.arn,
          "${aws_dynamodb_table.connections.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "execute-api:ManageConnections"
        ]
        Resource = "${aws_apigatewayv2_api.websocket.execution_arn}/*/POST/@connections/*"
      }
    ]
  })
}

resource "aws_lambda_function" "router" {
  function_name    = var.name_prefix
  role             = aws_iam_role.lambda.arn
  handler          = "bootstrap"
  runtime          = "provided.al2023"
  architectures    = ["arm64"]
  filename         = var.lambda_package_path
  source_code_hash = var.lambda_source_code_hash
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.connections.name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda,
  ]

  tags = local.common_tags
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.websocket.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.router.invoke_arn
  payload_format_version = "1.0"
}

resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.websocket.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "disconnect" {
  api_id    = aws_apigatewayv2_api.websocket.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.websocket.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromWebSocketApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.router.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket.execution_arn}/*/*"
}
