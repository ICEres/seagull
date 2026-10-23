# Keep unreconciled stream payloads available beyond DynamoDB's 24-hour window.
resource "aws_s3_bucket_server_side_encryption_configuration" "delivery_stream_failures" {
  bucket = aws_s3_bucket.delivery_stream_failures.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "delivery_stream_failures" {
  bucket = aws_s3_bucket.delivery_stream_failures.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_cloudwatch_metric_alarm" "delivery_publisher" {
  for_each = {
    errors = {
      metric      = "Errors"
      statistic   = "Sum"
      threshold   = 1
      description = "Delivery stream publisher failed. Inspect its logs and retained failure payloads."
    }
    throttles = {
      metric      = "Throttles"
      statistic   = "Sum"
      threshold   = 1
      description = "Delivery stream publisher is throttled. Check concurrency before the stream backlog grows."
    }
    destination_failures = {
      metric      = "DestinationDeliveryFailures"
      statistic   = "Sum"
      threshold   = 1
      description = "Lambda could not retain a failed stream payload in S3. Reconcile the affected outage window."
    }
    stream_age = {
      metric      = "IteratorAge"
      statistic   = "Maximum"
      threshold   = 600000
      description = "Delivery stream processing is more than ten minutes behind. Check retries and publisher health."
    }
  }

  alarm_name          = "${local.message_hub_prefix}-delivery-publisher-${each.key}"
  alarm_description   = each.value.description
  namespace           = "AWS/Lambda"
  metric_name         = each.value.metric
  statistic           = each.value.statistic
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = each.value.threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.delivery_stream_publisher.function_name
  }

  tags = local.message_hub_tags
}

resource "aws_cloudwatch_metric_alarm" "delivery_stream_records" {
  for_each = toset([
    "FailedInvokeEventCount",
    "DroppedEventCount",
    "OnFailureDestinationDeliveredEventCount",
  ])

  alarm_name          = "${local.message_hub_prefix}-delivery-stream-${each.key}"
  alarm_description   = "Delivery stream records need attention. Inspect the failure archive and reconcile before closing the alarm."
  namespace           = "AWS/Lambda"
  metric_name         = each.key
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    EventSourceMappingUUID = aws_lambda_event_source_mapping.delivery_stream_publisher.uuid
  }

  tags = local.message_hub_tags
}

resource "aws_cloudwatch_metric_alarm" "agent_jobs_age" {
  alarm_name          = "${local.message_hub_prefix}-agent-jobs-age"
  alarm_description   = "Agent delivery jobs have waited more than fifteen minutes. Inspect webhook retries and worker health."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 900
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.agent_jobs.name
  }

  tags = local.message_hub_tags
}

resource "aws_cloudwatch_metric_alarm" "agent_jobs_dlq" {
  alarm_name          = "${local.message_hub_prefix}-agent-jobs-dlq"
  alarm_description   = "Agent delivery jobs reached the dead-letter queue. Inspect and replay them after repairing the cause."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.agent_jobs_dlq.name
  }

  tags = local.message_hub_tags
}
