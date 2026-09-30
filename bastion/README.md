# Windows RDP bastion

A single Windows EC2 instance in the existing private subnets, for reaching
the internal ALB (VPC-only) via RDP + browser. No inbound ports are opened:
RDP is tunneled through AWS Systems Manager Session Manager, so 3389 never
crosses the subnet boundary and no changes are needed to the NACLs in
[`../templates/base/vpc-stack.yaml`](../templates/base/vpc-stack.yaml) (see
[`../NACL-COMPLIANCE.md`](../NACL-COMPLIANCE.md) for why an open admin port
would re-trip that policy).

## Before you apply

You need an EC2 key pair to decrypt the instance's initial Administrator
password (Windows AMIs require this). If you don't have one:

```bash
aws ec2 create-key-pair --key-name kyc-rdp-bastion --query 'KeyMaterial' --output text > kyc-rdp-bastion.pem
chmod 400 kyc-rdp-bastion.pem   # keep this out of git
```

> **Heads-up:** the role you use to `terraform apply` may hit the same
> `ec2:RunInstances` explicit deny from the org SCP (`p-bz8sxtos`) you saw
> launching from the console — SCPs apply to Terraform the same as the
> console, since they gate the calling IAM principal, not the tool. If it's
> denied here too, that confirms it isn't a "manual vs. IaC" distinction;
> check with whoever owns that SCP whether Windows instances (or
> `RunInstances` generally) need a specific approved role/path in this
> account.

## Apply

```bash
cd bastion
terraform init
terraform apply -var="key_pair_name=kyc-rdp-bastion"
```

## Connect

```bash
# 1. Open the tunnel (needs the Session Manager plugin installed locally)
terraform output -raw ssm_port_forward_command | bash   # leave running

# 2. In another terminal, get the initial Administrator password
terraform output -raw get_password_command   # edit in your .pem path, then run

# 3. RDP to localhost:13389 with user Administrator + the decrypted password
```

Once connected, open a browser on the Windows desktop and hit the internal
ALB's DNS name directly — it resolves and routes fine from inside the VPC.

## Cleanup

```bash
terraform destroy
```

This is a bastion for occasional access, not a long-running workload — destroy
it when you're done rather than leaving it up.
