locals {
  common_tags = merge(
    var.tags,
    {
      App = "message-hub"
    },
  )

  payload_objects_bucket_name = var.payload_objects_bucket_name != "" ? var.payload_objects_bucket_name : "${var.name_prefix}-payload-objects"
}

resource "aws_dynamodb_table" "agents" {
  name                        = "${var.name_prefix}-agents"
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

  global_secondary_index {
    name            = "handle-index"
    hash_key        = "handle"
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

resource "aws_dynamodb_table" "agent_tokens" {
  name                        = "${var.name_prefix}-agent-tokens"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "token_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "token_id"
    type = "S"
  }

  attribute {
    name = "agent_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "agent-created-at-index"
    hash_key        = "agent_id"
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

resource "aws_dynamodb_table" "messages" {
  name                        = "${var.name_prefix}-messages"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "message_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "message_id"
    type = "S"
  }

  attribute {
    name = "thread_id"
    type = "S"
  }

  attribute {
    name = "sender_agent_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "thread-created-at-index"
    hash_key        = "thread_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "sender-created-at-index"
    hash_key        = "sender_agent_id"
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

resource "aws_dynamodb_table" "threads" {
  name                        = "${var.name_prefix}-threads"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "thread_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "thread_id"
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

resource "aws_dynamodb_table" "deliveries" {
  name                        = "${var.name_prefix}-deliveries"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "delivery_id"
  deletion_protection_enabled = var.deletion_protection_enabled
  stream_enabled              = true
  stream_view_type            = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "delivery_id"
    type = "S"
  }

  attribute {
    name = "recipient_agent_id"
    type = "S"
  }

  attribute {
    name = "sender_agent_id"
    type = "S"
  }

  attribute {
    name = "message_id"
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
    name            = "sender-created-at-index"
    hash_key        = "sender_agent_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "message-recipient-index"
    hash_key        = "message_id"
    range_key       = "recipient_agent_id"
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

resource "aws_dynamodb_table" "routing_rules" {
  name                        = "${var.name_prefix}-routing-rules"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "rule_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "rule_id"
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

resource "aws_dynamodb_table" "idempotency_keys" {
  name                        = "${var.name_prefix}-idempotency-keys"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "sender_agent_id"
  range_key                   = "idempotency_key"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "sender_agent_id"
    type = "S"
  }

  attribute {
    name = "idempotency_key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
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

resource "aws_dynamodb_table" "thread_summaries" {
  name                        = "${var.name_prefix}-thread-summaries"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "thread_id"
  range_key                   = "created_at"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "thread_id"
    type = "S"
  }

  attribute {
    name = "created_at"
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

resource "aws_dynamodb_table" "payloads" {
  name                        = "${var.name_prefix}-payloads"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "content_ref"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "content_ref"
    type = "S"
  }

  attribute {
    name = "retention_state"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "retention-state-created-at-index"
    hash_key        = "retention_state"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl_expires_at_epoch"
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

resource "aws_s3_bucket" "payload_objects" {
  bucket = local.payload_objects_bucket_name

  tags = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "payload_objects" {
  bucket = aws_s3_bucket.payload_objects.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "payload_objects" {
  bucket = aws_s3_bucket.payload_objects.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "payload_objects" {
  bucket = aws_s3_bucket.payload_objects.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_dynamodb_table" "tasks" {
  name                        = "${var.name_prefix}-tasks"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "task_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "task_id"
    type = "S"
  }

  attribute {
    name = "thread_id"
    type = "S"
  }

  attribute {
    name = "requester_agent_id"
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
    name            = "thread-created-at-index"
    hash_key        = "thread_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "requester-created-at-index"
    hash_key        = "requester_agent_id"
    range_key       = "created_at"
    projection_type = "ALL"
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

resource "aws_dynamodb_table" "tool_requests" {
  name                        = "${var.name_prefix}-tool-requests"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "tool_request_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "tool_request_id"
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

resource "aws_dynamodb_table" "task_results" {
  name                        = "${var.name_prefix}-task-results"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "result_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "result_id"
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

# --- Feed ---------------------------------------------------------------------
# Feed is a gulls network capability: durable one-to-many publishing and
# subscription. These tables hold the base source of truth that the seagulls
# SNS interface ranks and projects on top of.

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
    name = "author_agent_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
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

  # Reverse edge: who follows this agent.
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
    range_key       = "room_id"
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
