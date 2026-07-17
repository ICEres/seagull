terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      configuration_aliases = [aws.us_east_1]
    }
  }
}

locals {
  common_tags = merge(
    var.tags,
    {
      App = "web"
    },
  )

  certificate_sans = [
    for name in distinct(compact([var.admin_domain_name, var.landing_domain_name])) : name
    if name != var.domain_name
  ]
  domain_aliases = distinct(compact([var.domain_name, var.admin_domain_name]))
  landing_files  = var.landing_dist_dir == "" ? toset([]) : setsubtract(fileset(var.landing_dist_dir, "**"), ["config.js"])
  origin_id      = "${var.name_prefix}-s3-origin"
  dist_files     = setsubtract(fileset(var.dist_dir, "**"), ["config.js"])
  runtime_config = "window.SEAGULL_CONFIG = ${jsonencode({
    socialApiUrl     = var.social_api_url
    messageApiUrl    = var.message_api_url
    aiProviderApiUrl = var.ai_provider_api_url
    adminDomainName  = var.admin_domain_name
    auth = {
      mode         = var.auth_mode
      issuer       = var.auth_issuer
      hostedDomain = var.auth_hosted_domain
      clientId     = var.auth_client_id
      redirectUri  = var.auth_redirect_uri
      logoutUri    = var.auth_logout_uri
    }
  })};\n"

  mime_types = {
    ".css"   = "text/css"
    ".html"  = "text/html"
    ".ico"   = "image/x-icon"
    ".js"    = "application/javascript"
    ".json"  = "application/json"
    ".map"   = "application/json"
    ".png"   = "image/png"
    ".svg"   = "image/svg+xml"
    ".txt"   = "text/plain"
    ".webp"  = "image/webp"
    ".woff"  = "font/woff"
    ".woff2" = "font/woff2"
  }
}

resource "aws_acm_certificate" "web" {
  provider = aws.us_east_1

  domain_name               = var.domain_name
  subject_alternative_names = local.certificate_sans
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = local.common_tags
}

resource "aws_route53_record" "certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.web.domain_validation_options : option.domain_name => {
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
  zone_id         = var.hosted_zone_id
}

resource "aws_acm_certificate_validation" "web" {
  provider = aws.us_east_1

  certificate_arn         = aws_acm_certificate.web.arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}

resource "aws_s3_bucket" "web" {
  bucket = var.bucket_name

  tags = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket = aws_s3_bucket.web.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.name_prefix}-oac"
  description                       = "Origin access control for ${var.name_prefix}."
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_cache_policy" "app_shell" {
  name        = "${var.name_prefix}-app-shell"
  comment     = "Short cache policy for the Seagull app shell."
  default_ttl = 60
  max_ttl     = 300
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }

    headers_config {
      header_behavior = "none"
    }

    query_strings_config {
      query_string_behavior = "none"
    }

    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
  }
}

resource "aws_cloudfront_cache_policy" "assets" {
  name        = "${var.name_prefix}-assets"
  comment     = "Long cache policy for hashed Vite assets."
  default_ttl = 31536000
  max_ttl     = 31536000
  min_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }

    headers_config {
      header_behavior = "none"
    }

    query_strings_config {
      query_string_behavior = "none"
    }

    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
  }
}

resource "aws_cloudfront_distribution" "web" {
  aliases             = local.domain_aliases
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.name_prefix} frontend"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
    origin_id                = local.origin_id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = aws_cloudfront_cache_policy.app_shell.id
    compress               = true
    target_origin_id       = local.origin_id
    viewer_protocol_policy = "redirect-to-https"
  }

  ordered_cache_behavior {
    path_pattern           = "/assets/*"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = aws_cloudfront_cache_policy.assets.id
    compress               = true
    target_origin_id       = local.origin_id
    viewer_protocol_policy = "redirect-to-https"
  }

  custom_error_response {
    error_caching_min_ttl = 0
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
  }

  custom_error_response {
    error_caching_min_ttl = 0
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.web.certificate_arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }

  tags = local.common_tags
}

resource "aws_cloudfront_distribution" "landing" {
  count = var.landing_domain_name == "" ? 0 : 1

  aliases             = [var.landing_domain_name]
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.name_prefix} landing"
  default_root_object = "landing/index.html"
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
    origin_id                = local.origin_id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = aws_cloudfront_cache_policy.app_shell.id
    compress               = true
    target_origin_id       = local.origin_id
    viewer_protocol_policy = "redirect-to-https"
  }

  custom_error_response {
    error_caching_min_ttl = 0
    error_code            = 403
    response_code         = 200
    response_page_path    = "/landing/index.html"
  }

  custom_error_response {
    error_caching_min_ttl = 0
    error_code            = 404
    response_code         = 200
    response_page_path    = "/landing/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.web.certificate_arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }

  depends_on = [aws_cloudfront_distribution.web]

  tags = local.common_tags
}

resource "aws_route53_record" "web_ipv4" {
  allow_overwrite = true
  name            = var.domain_name
  type            = "A"
  zone_id         = var.hosted_zone_id

  alias {
    evaluate_target_health = false
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
  }
}

resource "aws_route53_record" "web_ipv6" {
  allow_overwrite = true
  name            = var.domain_name
  type            = "AAAA"
  zone_id         = var.hosted_zone_id

  alias {
    evaluate_target_health = false
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
  }
}

resource "aws_route53_record" "admin_web_ipv4" {
  count = var.admin_domain_name == "" ? 0 : 1

  allow_overwrite = true
  name            = var.admin_domain_name
  type            = "A"
  zone_id         = var.hosted_zone_id

  alias {
    evaluate_target_health = false
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
  }
}

resource "aws_route53_record" "admin_web_ipv6" {
  count = var.admin_domain_name == "" ? 0 : 1

  allow_overwrite = true
  name            = var.admin_domain_name
  type            = "AAAA"
  zone_id         = var.hosted_zone_id

  alias {
    evaluate_target_health = false
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
  }
}

resource "aws_route53_record" "landing_web_ipv4" {
  count = var.landing_domain_name == "" ? 0 : 1

  allow_overwrite = true
  name            = var.landing_domain_name
  type            = "A"
  zone_id         = var.hosted_zone_id

  alias {
    evaluate_target_health = false
    name                   = aws_cloudfront_distribution.landing[0].domain_name
    zone_id                = aws_cloudfront_distribution.landing[0].hosted_zone_id
  }
}

resource "aws_route53_record" "landing_web_ipv6" {
  count = var.landing_domain_name == "" ? 0 : 1

  allow_overwrite = true
  name            = var.landing_domain_name
  type            = "AAAA"
  zone_id         = var.hosted_zone_id

  alias {
    evaluate_target_health = false
    name                   = aws_cloudfront_distribution.landing[0].domain_name
    zone_id                = aws_cloudfront_distribution.landing[0].hosted_zone_id
  }
}

data "aws_iam_policy_document" "web" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values = concat(
        [aws_cloudfront_distribution.web.arn],
        var.landing_domain_name == "" ? [] : [aws_cloudfront_distribution.landing[0].arn],
      )
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = data.aws_iam_policy_document.web.json
}

resource "aws_s3_object" "assets" {
  for_each = local.dist_files

  bucket        = aws_s3_bucket.web.id
  key           = each.value
  source        = "${var.dist_dir}/${each.value}"
  etag          = filemd5("${var.dist_dir}/${each.value}")
  content_type  = lookup(local.mime_types, lower(try(regex("\\.[^.]+$", each.value), "")), "application/octet-stream")
  cache_control = startswith(each.value, "assets/") ? "public,max-age=31536000,immutable" : "public,max-age=60"
}

resource "aws_s3_object" "landing_assets" {
  for_each = local.landing_files

  bucket        = aws_s3_bucket.web.id
  key           = "landing/${each.value}"
  source        = "${var.landing_dist_dir}/${each.value}"
  etag          = filemd5("${var.landing_dist_dir}/${each.value}")
  content_type  = lookup(local.mime_types, lower(try(regex("\\.[^.]+$", each.value), "")), "application/octet-stream")
  cache_control = "public,max-age=60"
}

resource "aws_s3_object" "runtime_config" {
  bucket        = aws_s3_bucket.web.id
  key           = "config.js"
  content       = local.runtime_config
  content_type  = "application/javascript"
  cache_control = "no-cache"
  etag          = md5(local.runtime_config)
}

# The landing build rewrites its /config.js reference to /landing/config.js
# (Vite base), so the runtime config is also written under the landing prefix.
resource "aws_s3_object" "landing_runtime_config" {
  count = var.landing_dist_dir == "" ? 0 : 1

  bucket        = aws_s3_bucket.web.id
  key           = "landing/config.js"
  content       = local.runtime_config
  content_type  = "application/javascript"
  cache_control = "no-cache"
  etag          = md5(local.runtime_config)
}
