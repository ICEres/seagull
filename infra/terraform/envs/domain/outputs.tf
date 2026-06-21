output "domain_name" {
  description = "Managed root domain."
  value       = aws_route53_zone.root.name
}

output "hosted_zone_id" {
  description = "Route 53 hosted zone ID."
  value       = aws_route53_zone.root.zone_id
}

output "name_servers" {
  description = "Nameservers to set at the domain registrar."
  value       = aws_route53_zone.root.name_servers
}
