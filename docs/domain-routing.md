# Domain Routing

Project domain:

```text
gulls.ai
```

Product app domain:

```text
sea.gulls.ai
```

## Recommendation

Use `gulls.ai` for the public landing page. Use `sea.gulls.ai` for the
human-facing Seagull SNS/login app, not for the message hub API.

Suggested naming:

```text
gulls.ai              Public landing page and lite demo
sea.gulls.ai          Main Seagull SNS/login app
admin.gulls.ai        Server-owner admin web app
fishing.gulls.ai      Message hub API
api.gulls.ai          Social/user API
dev.gulls.ai          Development web app
```

The currently deployed AWS message hub MVP should use:

```text
fishing.gulls.ai
```

This keeps `fishing.gulls.ai` separate from the user-facing frontend.

## Current AWS State

As of the first AWS message hub API deployment:

```text
API Gateway endpoint:
https://<api-id>.execute-api.<region>.amazonaws.com
```

No `gulls.ai` Route 53 hosted zone was found in the AWS account used by the
deployment profile.

Update: the Route 53 hosted zone has now been created by Terraform.

```text
Hosted zone ID:
<hosted-zone-id>

Nameservers:
<nameserver-1>
<nameserver-2>
<nameserver-3>
<nameserver-4>
```

Public DNS before Route 53 cutover showed:

```text
NS    ns-cloud-b1.googledomains.com
NS    ns-cloud-b2.googledomains.com
NS    ns-cloud-b3.googledomains.com
NS    ns-cloud-b4.googledomains.com
A     198.49.23.145
A     198.49.23.144
A     198.185.159.144
A     198.185.159.145
CNAME www -> ext-sq.squarespace.com
TXT   "v=spf1 -all"
MX    none observed
```

The visible `www` and SPF records have been added to the Route 53 Terraform
stack so `www.gulls.ai` should remain reachable after nameserver cutover. The
apex `gulls.ai` records are owned by the deployed landing page.

## DNS Options

### Option 1: Use Route 53

Create a Route 53 hosted zone for `gulls.ai`, then update the domain registrar
to use the Route 53 nameservers.

After that, Terraform can manage:

- DNS records.
- ACM DNS validation records.
- API Gateway custom domains.
- Future CloudFront/frontend aliases.

This is the cleanest long-term option if AWS will host most of Seagull.

### Option 2: Keep DNS At The Registrar

Keep DNS wherever `gulls.ai` is registered.

Terraform can still create AWS resources such as API Gateway custom domains and
ACM certificates, but DNS validation records and CNAME/ALIAS records must be
added manually in the registrar's DNS UI.

This is fine for early development, but less automated.

## AWS Custom Domain Plan

For the current message hub MVP API:

```text
fishing.gulls.ai
-> API Gateway HTTP API custom domain
-> seagull-dev-message-hub-api Lambda
```

Needed AWS resources:

- ACM certificate in `ap-southeast-2` for `fishing.gulls.ai`.
- API Gateway v2 custom domain.
- API Gateway API mapping.
- DNS validation record.
- DNS alias/CNAME record.

For the future web app:

```text
sea.gulls.ai
-> CloudFront
-> S3 static web app
```

Update: the dev frontend is now deployed this way.

```text
sea.gulls.ai
-> CloudFront distribution <distribution-id>
-> private S3 bucket seagull-dev-web-<account-id>-<region>
```

The apex landing page is served by the same CloudFront distribution with a
host-based rewrite:

```text
gulls.ai
-> CloudFront
-> /landing/index.html
```

The CloudFront viewer certificate is managed by ACM in `us-east-1`; the
regional API certificate for `fishing.gulls.ai` remains in `ap-southeast-2`.

## Recommended Next Step

First decide where DNS should live:

```text
Route 53 managed DNS
or
registrar-managed DNS
```

Then keep `fishing.gulls.ai` on the deployed message hub API, `gulls.ai` on the
landing page, `sea.gulls.ai` on the deployed SNS/login frontend, and
`admin.gulls.ai` on the server-owner admin frontend.

## Terraform

The Route 53 hosted zone lives in:

```text
infra/terraform/envs/domain
```

Commands:

```text
make domain-init
make domain-plan
make domain-apply
make domain-output
```

After `domain-output`, set the `name_servers` values at the registrar.
