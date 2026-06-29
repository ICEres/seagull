output "bucket_name" {
  description = "S3 bucket that stores the web assets."
  value       = aws_s3_bucket.web.bucket
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID for the frontend."
  value       = aws_cloudfront_distribution.web.id
}

output "cloudfront_domain_name" {
  description = "CloudFront distribution domain name for the frontend."
  value       = aws_cloudfront_distribution.web.domain_name
}

output "cloudfront_url" {
  description = "Default CloudFront HTTPS URL for the frontend."
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "domain_name" {
  description = "Custom frontend domain name."
  value       = var.domain_name
}

output "admin_domain_name" {
  description = "Custom admin frontend domain name."
  value       = var.admin_domain_name
}

output "url" {
  description = "HTTPS URL for the frontend."
  value       = "https://${var.domain_name}"
}

output "admin_url" {
  description = "HTTPS URL for the admin frontend."
  value       = var.admin_domain_name == "" ? "" : "https://${var.admin_domain_name}"
}
