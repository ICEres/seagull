# GitHub Actions Dev Deploy Role

Status: Current.

Last updated: 2026-07-27.

## Contents

Setup and reference:

- [Trust Policy](#trust-policy) — the GitHub OIDC trust relationship for the
  deploy role.
- [GitHub Repository Configuration](#github-repository-configuration) — the
  repository variables and secrets `CI Deploy` reads.
- [Permission Contract](#permission-contract) — every AWS action the role needs,
  by resource family. Keep this aligned with the Terraform modules.

Runbooks — executable procedures:

- [Deploy Runbook](#deploy-runbook) — how to authenticate, inspect state, and
  run a dev deploy. **Start here for a normal deploy.**
- [S3 Policy Repair](#s3-policy-repair) — when `Deploy dev` fails during refresh
  with `AccessDenied` on bucket configuration reads.
- [CloudWatch Alarm Policy Repair](#cloudwatch-alarm-policy-repair) — when
  `Deploy dev` fails during apply with `AccessDenied` from
  `CloudWatch: PutMetricAlarm`.
- [Log Metric Filter Policy Repair](#log-metric-filter-policy-repair) — when
  `Deploy dev` fails during apply with `AccessDenied` from
  `CloudWatch Logs: PutMetricFilter`.

Each repair runbook patches the role's inline policy in place with `aws iam
put-role-policy` and ends with a verification query. They need an admin AWS
profile, not the deploy role itself.

## Overview

The dev app stack assumes an AWS IAM role from GitHub Actions before Terraform
can read remote state or manage AWS resources. That role is bootstrap
infrastructure: it must exist before the `infra/terraform/envs/dev` stack can
run, so the dev stack does not create or update it.

Current dev convention:

```text
Role name:   seagull-github-actions-dev-deploy
Policy name: seagull-dev-terraform-deploy
Workflow:    .github/workflows/ci-deploy.yml
```

## Trust Policy

The role should trust the GitHub OIDC provider for this repository on `main`.
Use the repository owner/name that owns the deploy workflow.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:<owner>/<repo>:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

## GitHub Repository Configuration

`CI Deploy` reads these repository variables:

```text
AWS_ROLE_TO_ASSUME
TF_BACKEND_BUCKET
TF_BACKEND_DYNAMODB_TABLE
TF_BACKEND_KEY            # optional, defaults to seagull/dev/terraform.tfstate
TF_BACKEND_REGION         # optional, defaults to AWS_REGION or ap-southeast-2
AWS_REGION                # optional, defaults to ap-southeast-2
```

The workflow also needs the Lambda/admin secrets listed in
[`../envs/dev/README.md`](../envs/dev/README.md). Terraform materializes those
GitHub secrets into Secrets Manager; Lambda environment variables receive only
the resulting secret ARNs.

## Permission Contract

The deploy role needs permissions for the remote Terraform backend and for every
AWS resource family managed by the dev stack. Keep the role policy aligned with
the Terraform modules when adding resource types.

At minimum, the S3 bucket statements must include both Terraform-managed dev
buckets:

```text
arn:aws:s3:::seagull-dev-web-<account-id>-<region>
arn:aws:s3:::seagull-dev-msg-payloads-<account-id>-<region>
```

The matching object statement must include:

```text
arn:aws:s3:::seagull-dev-web-<account-id>-<region>/*
arn:aws:s3:::seagull-dev-msg-payloads-<account-id>-<region>/*
```

When adding another Terraform-managed S3 bucket, update both the bucket-level
and object-level statements before running `Deploy dev`.

The DynamoDB statement scoped to `seagull-dev-*` tables must include the
point-in-time recovery lifecycle actions used by Terraform:

```text
dynamodb:DescribeContinuousBackups
dynamodb:UpdateContinuousBackups
```

The bucket-level statement needs the Terraform S3 configuration actions used by
the web and message payload bucket resources, including:

```text
s3:CreateBucket
s3:DeleteBucket
s3:GetBucketLocation
s3:GetBucketPolicy
s3:PutBucketPolicy
s3:DeleteBucketPolicy
s3:GetBucketPublicAccessBlock
s3:PutBucketPublicAccessBlock
s3:GetBucketOwnershipControls
s3:PutBucketOwnershipControls
s3:GetEncryptionConfiguration
s3:PutEncryptionConfiguration
s3:GetBucketVersioning
s3:PutBucketVersioning
s3:ListBucket
s3:GetBucketTagging
s3:PutBucketTagging
s3:DeleteBucketTagging
```

The role also needs Secrets Manager permissions for runtime Lambda secrets under
the dev stack prefixes, for example:

```text
arn:aws:secretsmanager:<region>:<account-id>:secret:seagull-dev-*/runtime/*
```

The statement should cover Terraform lifecycle and version updates:

```text
secretsmanager:CreateSecret
secretsmanager:DeleteSecret
secretsmanager:DescribeSecret
secretsmanager:GetResourcePolicy
secretsmanager:GetSecretValue
secretsmanager:ListSecretVersionIds
secretsmanager:PutSecretValue
secretsmanager:TagResource
secretsmanager:UpdateSecret
```

The role needs CloudWatch alarm permissions for Terraform-managed dev alarms:

```text
cloudwatch:DescribeAlarms
cloudwatch:DescribeAlarmHistory
cloudwatch:PutMetricAlarm
cloudwatch:DeleteAlarms
cloudwatch:ListTagsForResource
cloudwatch:TagResource
cloudwatch:UntagResource
```

Scope write and tag actions to the dev alarm prefix:

```text
arn:aws:cloudwatch:<region>:<account-id>:alarm:seagull-dev-*
```

The Feed mirror alarm reads a metric produced by log metric filters, so the
role also needs CloudWatch Logs metric-filter permissions:

```text
logs:PutMetricFilter
logs:DeleteMetricFilter
logs:DescribeMetricFilters
```

Scope them to the dev Lambda log groups:

```text
arn:aws:logs:<region>:<account-id>:log-group:/aws/lambda/seagull-dev-*
```

The web module resolves the AWS-managed `Managed-AllViewerExceptHostHeader`
origin request policy by name. The CloudFront statement therefore needs:

```text
cloudfront:ListOriginRequestPolicies
cloudfront:GetOriginRequestPolicy
```

The passwordless social auth deployment verifies the root domain with Amazon
SES and enables Easy DKIM. The legacy SES identity APIs require these actions;
use `Resource: "*"` because they don't support identity-level resource scoping:

```text
ses:VerifyDomainIdentity
ses:GetIdentityVerificationAttributes
ses:DeleteIdentity
ses:VerifyDomainDkim
ses:GetIdentityDkimAttributes
ses:SetIdentityDkimEnabled
ses:GetAccount
```

SES production access is regional. Before deploying email-code authentication,
confirm that production access is enabled in the same region as the Cognito
user pool so codes can reach recipients whose addresses aren't separately
verified.

## S3 Policy Repair

Use this when Terraform state contains a bucket but `Deploy dev` fails during
refresh with `AccessDenied` for bucket configuration reads.

```sh
export AWS_PROFILE=personal
export AWS_REGION=ap-southeast-2
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export ROLE_NAME=seagull-github-actions-dev-deploy
export POLICY_NAME=seagull-dev-terraform-deploy
export PAYLOAD_BUCKET="seagull-dev-msg-payloads-${ACCOUNT_ID}-${AWS_REGION}"

aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --query PolicyDocument \
  --output json > /tmp/seagull-dev-terraform-deploy-policy.json

jq \
  --arg bucket_arn "arn:aws:s3:::${PAYLOAD_BUCKET}" \
  --arg object_arn "arn:aws:s3:::${PAYLOAD_BUCKET}/*" \
  '(.Statement[] | select(.Sid == "DevS3Buckets") | .Resource) |= (. + [$bucket_arn] | unique)
   | (.Statement[] | select(.Sid == "DevS3Objects") | .Resource) |= (. + [$object_arn] | unique)' \
  /tmp/seagull-dev-terraform-deploy-policy.json \
  > /tmp/seagull-dev-terraform-deploy-policy-updated.json

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document file:///tmp/seagull-dev-terraform-deploy-policy-updated.json
```

Verify the scoped S3 resources:

```sh
aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --query 'PolicyDocument.Statement[?Sid==`DevS3Buckets` || Sid==`DevS3Objects`].[Sid,Resource]' \
  --output json
```

## CloudWatch Alarm Policy Repair

Use this when `Deploy dev` fails during apply with `AccessDenied` from
`CloudWatch: PutMetricAlarm`.

```sh
export AWS_PROFILE=personal
export AWS_REGION=ap-southeast-2
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export ROLE_NAME=seagull-github-actions-dev-deploy
export POLICY_NAME=seagull-dev-terraform-deploy

aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --query PolicyDocument \
  --output json > /tmp/seagull-dev-terraform-deploy-policy.json

jq \
  --arg alarm_arn "arn:aws:cloudwatch:${AWS_REGION}:${ACCOUNT_ID}:alarm:seagull-dev-*" \
  '(.Statement) =
    ([.Statement[] | select(.Sid != "DevCloudWatchAlarmRead" and .Sid != "DevCloudWatchAlarms")] + [
      {
        "Sid": "DevCloudWatchAlarmRead",
        "Effect": "Allow",
        "Action": [
          "cloudwatch:DescribeAlarms",
          "cloudwatch:DescribeAlarmHistory"
        ],
        "Resource": "*"
      },
      {
        "Sid": "DevCloudWatchAlarms",
        "Effect": "Allow",
        "Action": [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:ListTagsForResource",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource"
        ],
        "Resource": $alarm_arn
      }
    ])' \
  /tmp/seagull-dev-terraform-deploy-policy.json \
  > /tmp/seagull-dev-terraform-deploy-policy-updated.json

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document file:///tmp/seagull-dev-terraform-deploy-policy-updated.json
```

Verify the scoped CloudWatch alarm statements:

```sh
aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --query 'PolicyDocument.Statement[?Sid==`DevCloudWatchAlarmRead` || Sid==`DevCloudWatchAlarms`].[Sid,Action,Resource]' \
  --output json
```

## Log Metric Filter Policy Repair

Use this when `Deploy dev` fails during apply with `AccessDenied` from
`CloudWatch Logs: PutMetricFilter`, as it did when the Feed mirror metric
filters were first added:

```text
User: .../seagull-github-actions-dev-deploy/GitHubActions is not authorized to
perform: logs:PutMetricFilter on resource: .../seagull-dev-social-api
```

The alarm those filters feed is what makes the Feed dual-write verifiable, so
the deploy cannot be considered done while this is failing.

```sh
export AWS_PROFILE=personal
export AWS_REGION=ap-southeast-2
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export ROLE_NAME=seagull-github-actions-dev-deploy
export POLICY_NAME=seagull-dev-terraform-deploy

aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --query PolicyDocument \
  --output json > /tmp/seagull-dev-terraform-deploy-policy.json

jq \
  --arg log_group_arn "arn:aws:logs:${AWS_REGION}:${ACCOUNT_ID}:log-group:/aws/lambda/seagull-dev-*" \
  '(.Statement) =
    ([.Statement[] | select(.Sid != "DevLogMetricFilters")] + [
      {
        "Sid": "DevLogMetricFilters",
        "Effect": "Allow",
        "Action": [
          "logs:PutMetricFilter",
          "logs:DeleteMetricFilter",
          "logs:DescribeMetricFilters"
        ],
        "Resource": $log_group_arn
      }
    ])' \
  /tmp/seagull-dev-terraform-deploy-policy.json \
  > /tmp/seagull-dev-terraform-deploy-policy-updated.json

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document file:///tmp/seagull-dev-terraform-deploy-policy-updated.json
```

Verify the scoped statement, then re-run `Deploy dev`:

```sh
aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --query 'PolicyDocument.Statement[?Sid==`DevLogMetricFilters`].[Sid,Action,Resource]' \
  --output json
```

## Deploy Runbook

1. Authenticate an admin AWS profile when changing bootstrap IAM:

   ```sh
   aws sso login --profile personal
   aws sts get-caller-identity --profile personal
   ```

2. Initialize the dev backend locally when inspecting state:

   ```sh
   AWS_PROFILE=personal TF_VAR_aws_profile=personal make aws-dev-init
   AWS_PROFILE=personal TF_VAR_aws_profile=personal terraform -chdir=infra/terraform/envs/dev state list
   ```

3. Prefer the manual GitHub workflow for dev applies, because it supplies the
   repository secrets that Terraform writes into Secrets Manager for Lambda
   runtime lookup:

   ```sh
   gh workflow run "CI Deploy" --repo <owner>/<repo> --ref main
   gh run watch <run-id> --repo <owner>/<repo> --exit-status
   ```

Avoid a local full `terraform apply` unless every sensitive `TF_VAR_*` value used
by CI is present locally. Applying with missing secret variables can overwrite
the deployed Secrets Manager secret versions.
