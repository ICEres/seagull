provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

resource "aws_route53_zone" "root" {
  name    = var.domain_name
  comment = "Seagull project DNS zone managed by Terraform."

  tags = {
    Project = var.project
    Domain  = var.domain_name
  }
}

removed {
  from = aws_route53_record.apex_squarespace

  lifecycle {
    destroy = false
  }
}

resource "aws_route53_record" "www_squarespace" {
  zone_id = aws_route53_zone.root.zone_id
  name    = "www.${var.domain_name}"
  type    = "CNAME"
  ttl     = 300
  records = ["ext-sq.squarespace.com"]
}

resource "aws_route53_record" "spf_reject_all" {
  zone_id = aws_route53_zone.root.zone_id
  name    = var.domain_name
  type    = "TXT"
  ttl     = 300
  records = ["v=spf1 -all"]
}
