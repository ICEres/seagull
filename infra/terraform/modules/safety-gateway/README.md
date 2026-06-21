# Safety Gateway Module

Terraform module for the safety gateway.

Current MVP resources:

- API Gateway HTTP API.
- Lambda function for policy evaluation.
- DynamoDB table for safety audit events.

Later resources:

- DynamoDB tables for policies, trust labels, and review state.
- EventBridge rules for safety events.
- SQS queues for quarantine and human-review workflows.
- CloudWatch logs and alarms.
