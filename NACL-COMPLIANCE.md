# Network ACL Compliance Remediation

## The finding

| Field | Value |
|---|---|
| Severity | P3 — config & monitoring |
| Account | `cb7933698a-dsamsai-aw` (`360946915124`) |
| Region | us-east-1 (AWS Virginia) |
| Policy name | Test NACL Enforcement+ v2 |
| Policy type | Config |
| Resource | `acl-0c6b046b8850655cc` |

The flagged resource is the **default Network ACL** that AWS auto-creates for every VPC. Its signature gives it away: a single explicit rule (`100`, allow all traffic, both directions) plus the implicit `*` deny-all catch-all — that's exactly what AWS generates for a default NACL, not something anyone configured on purpose.

## Why this is a compliance risk

- The default NACL is easy to forget. It isn't declared anywhere in this repo's CloudFormation — confirmed by a repo-wide search for `NetworkAcl`, `NetworkAclEntry`, and `SubnetNetworkAclAssociation`, which returned zero hits before this change.
- Because no subnet had an explicit NACL association, **every subnet in the VPC was silently riding the default NACL**, meaning its allow-all rule was the *only* network-layer ACL in front of all four subnets.
- NACLs are meant to be a second, stateless layer of defense behind Security Groups (defense-in-depth). An allow-all default NACL contributes nothing to that — it's effectively a no-op control that *looks* like a control to anyone reviewing the account.
- Policies like this one exist to catch exactly this gap: VPCs where the default NACL was never locked down because someone assumed Security Groups were "enough."

## Current state (before this change)

| VPC/Subnet | CIDR | AZ | Public/Private | Hosts |
|---|---|---|---|---|
| VPC | `10.0.0.0/16` | — | — | — |
| PublicSubnet1 | `10.0.1.0/24` | us-east-1a | Public (routes to IGW) | NAT Gateway; Elastic Beanstalk ALB + EC2 (mock service) |
| PublicSubnet2 | `10.0.2.0/24` | us-east-1c | Public (routes to IGW) | Elastic Beanstalk ALB second AZ (required for load-balanced EB) |
| PrivateSubnet1 | `10.0.3.0/24` | us-east-1a | Private (routes to NAT) | KYC Lambda, Backend API Lambda, BedrockAgentCore runtime |
| PrivateSubnet2 | `10.0.4.0/24` | us-east-1c | Private (routes to NAT) | Same workloads, second AZ for HA |

Source: [templates/base/vpc-stack.yaml](templates/base/vpc-stack.yaml).

All four subnets were associated with the same default NACL (`acl-0c6b046b8850655cc`), with no explicit NACL of their own.

Security Groups were already scoped correctly and are unaffected by this change:
- Lambda/AgentCore SGs: allow all egress, **no ingress** (correct — nothing inside the VPC calls them).
- Elastic Beanstalk: EB-managed SG allowing 80/443 from the internet to the ALB, and from the ALB to the instance.

> The `terraform-runner-stack.yaml` (a one-off EC2 used to run Terraform for a Langfuse deployment) has since been removed from this repo; SSH access to it was handled manually rather than through this infrastructure-as-code. No SSH rule appears in the NACL design below as a result.

## To-be NACL design

Two purpose-built NACLs were added in [templates/base/vpc-stack.yaml](templates/base/vpc-stack.yaml), replacing the implicit default-NACL association on every subnet.

### PublicNacl — associated with PublicSubnet1, PublicSubnet2

| Flow | # | Direction | Proto | Port | CIDR | Action | Why |
|---|---|---|---|---|---|---|---|
| Internet client → ALB (request) | 100 | Inbound | TCP | 80, 443 | `0.0.0.0/0` | ALLOW | Elastic Beanstalk ALB serves the mock service publicly over HTTP/HTTPS |
| Internet client → ALB (response) | 120 | Outbound | TCP | 1024–65535 | `0.0.0.0/0` | ALLOW | Stateless return leg for the rule above — response back to whichever client hit the ALB |
| EB instance → internet/AWS APIs (request) | 100 | Outbound | TCP | 80, 443 | `0.0.0.0/0` | ALLOW | EB instance reaching the internet/AWS APIs |
| EB instance → internet/AWS APIs (response) | 120 | Inbound | TCP | 1024–65535 | `0.0.0.0/0` | ALLOW | Stateless return leg for the rule above — NACLs don't track connection state, so the reply needs its own explicit rule |
| DNS | 130 | Outbound | UDP | 53 | VPC CIDR (`10.0.0.0/16`) | ALLOW | DNS resolution via the VPC's Route 53 Resolver (always at the VPC's base address +2) |
| NTP | 140 | Outbound | UDP | 123 | `0.0.0.0/0` | ALLOW | NTP time sync (Amazon Time Sync Service is reached over a link-local address, not the VPC CIDR) |
| — | * | both | all | all | `0.0.0.0/0` | DENY | Implicit default-deny |

No SSH rule is included — the Terraform runner EC2 instance that previously needed port 22 has been removed from this repo, and there is no other workload in the public subnets that requires inbound SSH.

### PrivateNacl — associated with PrivateSubnet1, PrivateSubnet2

| Flow | # | Direction | Proto | Port | CIDR | Action | Why |
|---|---|---|---|---|---|---|---|
| Lambda/AgentCore → AWS APIs over HTTPS (request) | 100 | Outbound | TCP | 443 | `0.0.0.0/0` | ALLOW | HTTPS to Bedrock, S3, DynamoDB, SQS, Textract, and the BRP/PEP mock APIs |
| Lambda/AgentCore → AWS APIs over HTTPS (response) | 100 | Inbound | TCP | 1024–65535 | `0.0.0.0/0` | ALLOW | Stateless return leg for the rule above, routed back through the NAT Gateway |
| Lambda/AgentCore → mock APIs over HTTP (request) | 110 | Outbound | TCP | 80 | `0.0.0.0/0` | ALLOW | Plain-HTTP mock service calls, if `MOCK_SERVICE_URL` is configured without TLS |
| VPC peer → Lambda/AgentCore on 443 (request) | 110 | Inbound | TCP | 443 | VPC CIDR (`10.0.0.0/16`) | ALLOW | Intra-VPC HTTPS, in case Lambda/AgentCore ever call each other directly |
| VPC peer → Lambda/AgentCore on 443 (response) | 130 | Outbound | TCP | 1024–65535 | VPC CIDR (`10.0.0.0/16`) | ALLOW | Stateless return leg for the rule above — answers intra-VPC callers connecting to us on 443 |
| DNS | 120 | Outbound | UDP | 53 | VPC CIDR (`10.0.0.0/16`) | ALLOW | DNS resolution via the VPC's Route 53 Resolver |
| — | * | both | all | all | `0.0.0.0/0` | DENY | Implicit default-deny |

No broad inbound internet rule is needed on `PrivateNacl` — nothing outside the VPC ever initiates a connection to the Lambdas or AgentCore runtime.

## What's intentionally left out of this NACL design

**API Gateway** and **DynamoDB** do not appear in either table because they are AWS-managed services with no ENI, no subnet, and no NACL association:

- `BackendApiRestApi` ([templates/api-stack.yaml](templates/api-stack.yaml)) is a default regional REST API — no `EndpointConfiguration: PRIVATE`, no `VpcLink`. It lives outside the VPC entirely and invokes the backend Lambda over the Lambda control plane, not through subnet networking.
- `KycCasesTable` ([templates/base/storage-stack.yaml](templates/base/storage-stack.yaml)) is a standard DynamoDB table, reached over its public regional service endpoint. No Gateway VPC Endpoint is defined, so the Lambdas/AgentCore in `PrivateSubnet1`/`PrivateSubnet2` reach it via NAT Gateway → IGW → DynamoDB's public endpoint — covered by the `PrivateNacl` outbound 443 rule above, same as S3/SQS/Bedrock/Textract.

## The flagged resource itself still needs manual remediation

CloudFormation cannot manage the rules of a pre-existing **default** NACL — there is no way to "import" `acl-0c6b046b8850655cc` as a managed resource and edit its entries from this template. Adding `PublicNacl`/`PrivateNacl` and associating every subnet with them makes the default NACL associated with zero subnets (inert), but the policy scans the default NACL's *own* rule set regardless of its associations.

To actually close the finding, after deploying the updated `vpc-stack.yaml`:

```bash
# Confirm the default NACL has no subnet associations left
aws ec2 describe-network-acls --network-acl-ids acl-0c6b046b8850655cc --region us-east-1

# Replace its allow-all entries with deny-all
aws ec2 delete-network-acl-entry --network-acl-id acl-0c6b046b8850655cc --rule-number 100 --egress --region us-east-1
aws ec2 delete-network-acl-entry --network-acl-id acl-0c6b046b8850655cc --rule-number 100 --region us-east-1

aws ec2 create-network-acl-entry --network-acl-id acl-0c6b046b8850655cc --rule-number 100 --protocol -1 --rule-action deny --cidr-block 0.0.0.0/0 --egress --region us-east-1
aws ec2 create-network-acl-entry --network-acl-id acl-0c6b046b8850655cc --rule-number 100 --protocol -1 --rule-action deny --cidr-block 0.0.0.0/0 --region us-east-1
```

## Re-flag risk — what would trip this policy again

The same policy (or equivalent CSPM rules) typically flags two independent patterns on **any** NACL, not just the default one:

1. **An "allow all" rule** — protocol `-1`, port range `ALL`, CIDR `0.0.0.0/0`. None of the entries above use `-1`/`ALL`; every rule is scoped to a specific protocol and port range.
2. **Unrestricted access to an admin port** (22, 3389, etc.) from `0.0.0.0/0`. There is no SSH rule at all in this design (see above), so this pattern doesn't apply here. If a future workload needs SSH, scope it to a specific admin IP/CIDR rather than `0.0.0.0/0`.

## Verification

1. Deploy the updated `vpc-stack.yaml`.
2. `aws ec2 describe-network-acls --filters Name=vpc-id,Values=<vpc-id>` — confirm `PublicNacl`/`PrivateNacl` exist and are associated with the correct subnets, and that the default NACL has no associations.
3. Run the manual remediation commands above against `acl-0c6b046b8850655cc`.
4. Smoke test: hit the EB mock service over HTTPS, trigger a KYC case end-to-end (document processing → risk screening → adverse media → orchestrator), confirm Bedrock/DynamoDB/S3/SQS/Textract calls still succeed from the private subnets.
5. Re-run `Test NACL Enforcement+ v2` against account `360946915124` to confirm the finding clears.
