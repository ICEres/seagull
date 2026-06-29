# Domain Environment

Terraform root module for project-level DNS.

This stack owns the Route 53 hosted zone for:

```text
gulls.ai
```

It also preserves the non-apex DNS records that were publicly visible before
nameserver cutover:

- `www` CNAME to Squarespace.
- Root SPF TXT record.

The apex `gulls.ai` `A`/`AAAA` records are owned by the dev web stack so the
public landing page can be served from CloudFront. A Terraform `removed` block
keeps this stack from deleting the old apex Squarespace record during the
handoff.

After creating the hosted zone, update the registrar nameservers to the
Terraform output `name_servers`.

Deploy:

```text
terraform init
terraform plan
terraform apply
terraform output name_servers
```

From the repository root:

```text
make domain-init
make domain-plan
make domain-apply
make domain-output
```

Destroying this stack after nameserver cutover will break DNS for the domain.
