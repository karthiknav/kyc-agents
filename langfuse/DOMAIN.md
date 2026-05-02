# Domain Setup for Langfuse

The Terraform module requires a `domain` that you control. If your domain lives in a different AWS account than where Langfuse is deployed, you can use NS delegation to wire them together.

## Cross-account NS delegation

### How it works

An NS record tells DNS: **"for this subdomain, ask these nameservers instead of me."**

When someone visits `langfuse.yourdomain.com`:

1. DNS resolves `yourdomain.com` to Account A's Route 53
2. Account A has an NS record pointing `langfuse.yourdomain.com` → Account B's nameservers
3. Account B's Route 53 resolves the actual IP (ALB, ACM validation records, etc.)

### Step by step

1. Run `terraform apply` in Account B — it creates a hosted zone for `langfuse.yourdomain.com`
2. In Route 53 (Account B), find that hosted zone and copy its 4 NS records
3. In Route 53 (Account A), open the `yourdomain.com` hosted zone and add a new NS record:

```
langfuse.yourdomain.com    NS    ns-123.awsdns-12.com
                                 ns-456.awsdns-34.net
                                 ns-789.awsdns-56.org
                                 ns-012.awsdns-78.co.uk
```

4. Done — DNS for `langfuse.yourdomain.com` now resolves via Account B

### Why this works

Account A remains the authority for `yourdomain.com` — it simply delegates the `langfuse` subdomain to Account B. Account B's Route 53 then handles all records under that subdomain (A record for the ALB, CNAME for ACM certificate validation, etc.).

You do not need to transfer or duplicate the domain — only the NS delegation record needs to be added.
