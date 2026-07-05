# Limited IAM Roles, CloudFormation, and `iam:PassRole`

A reference note on what happens when deploying CloudFormation templates that
create resources (e.g. Bedrock AgentCore runtimes, CodePipeline pipelines) beyond
what your own IAM identity is permitted to create directly.

---

## Scenario

You have an IAM identity scoped to:

```
s3:*
dynamodb:*
```

You run a CloudFormation template that provisions:

- `AWS::BedrockAgentCore::Runtime`
- `AWS::CodePipeline::Pipeline`
- S3 buckets / DynamoDB tables

You do **not** have `bedrock-agentcore:*` or `codepipeline:*` permissions yourself.

---

## What happens

CloudFormation evaluates permissions for whichever principal actually performs
the resource creation calls:

- **No service role attached** → CloudFormation uses *your* IAM identity's
  permissions for every resource. The S3/DynamoDB resources succeed; the
  AgentCore/CodePipeline resources fail with `AccessDenied`.
- **Default rollback behavior** → on failure, CloudFormation rolls back the
  *entire* stack, deleting the S3/DynamoDB resources that did succeed (unless
  `--disable-rollback` is set).
- **Service role (`--role-arn`) attached** → CloudFormation uses *that role's*
  permissions instead of yours. If the role is broad enough, the stack
  succeeds even though you personally could never have created those
  resources directly.
- You also need `cloudformation:CreateStack` / `UpdateStack` itself — without
  it, the call fails before touching any resource-specific permissions.

---

## So I need a broader service role + `iam:PassRole`?

Yes. To let CloudFormation create resources outside your own permissions:

1. A CloudFormation **service role** exists with the broader permissions
   needed (`bedrock-agentcore:CreateAgentRuntime`, `codepipeline:CreatePipeline`,
   plus your existing S3/DynamoDB needs).
2. Your IAM identity needs **`iam:PassRole`** on that role's ARN, so you can
   tell CloudFormation "use this role" when calling `CreateStack`.
3. CloudFormation then performs the actual resource API calls using the
   **service role's** permissions, not yours.

---

## Is this privilege escalation?

**Mechanically, yes — it's the textbook pattern.** This is one of the most
commonly documented AWS privilege-escalation vectors (see Rhino Security
Labs' AWS privesc research):

```
iam:PassRole + cloudformation:CreateStack
    → arbitrary capability via whatever the passed role can do
```

A user with nothing but `s3:*`, `dynamodb:*`, `cloudformation:CreateStack`,
and `iam:PassRole` on one broad service role can end up with effectively
admin-equivalent capability — routed through CloudFormation as the actor —
without that capability ever appearing directly on their own identity.

**Whether it gets flagged as a finding depends on how tightly it's scoped:**

| Factor | Low risk (sanctioned pattern) | High risk (flagged in review) |
|---|---|---|
| `PassRole` resource scope | Restricted to one specific role ARN | `Resource: "*"` — can pass *any* role |
| Service role's own permissions | Scoped to exactly what the stack needs | Broad/admin-equivalent |
| Condition keys | `iam:PassedToService: cloudformation.amazonaws.com` enforced | No condition — role could be passed to other services too |
| Role mutability | Same limited users cannot edit the role's policy | Same users can also `iam:PutRolePolicy` / `iam:UpdateAssumeRolePolicy` on it — creates a self-escalation loop |

### The legitimate, non-escalating way to do this

- Scope `iam:PassRole` to the **exact** CloudFormation service role ARN, not `*`.
- Add the condition:
  ```json
  "Condition": {
    "StringEquals": {
      "iam:PassedToService": "cloudformation.amazonaws.com"
    }
  }
  ```
  so the grant can't be reused to pass the role to other services.
- Scope the service role itself to only what this stack actually needs
  (AgentCore, CodePipeline, S3, DynamoDB) — not broad/admin.
- Do **not** also grant the same limited user `iam:PutRolePolicy` or
  `iam:UpdateAssumeRolePolicy` on that role — otherwise they could rewrite it
  to grant themselves more later.

### Bottom line

This is the **sanctioned, intentional version** of the privilege-escalation
pattern — it's exactly how CI/CD and IaC pipelines are designed to work
everywhere (why CodePipeline + CloudFormation deployments always use a
dedicated, scoped service role rather than the deploying user's own
permissions). It only becomes a security **finding** when the `PassRole`
grant or the role's own permissions are broader than the task actually
requires.
