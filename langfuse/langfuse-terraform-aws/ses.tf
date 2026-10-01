# SES domain identity, used so Langfuse can send transactional email (e.g.
# "Missing environment variables for sending membership invitation email" is
# fixed by wiring SMTP_CONNECTION_URL / EMAIL_FROM_ADDRESS below).
#
# Langfuse's SMTP_CONNECTION_URL accepts a ses://<region> scheme in addition to
# smtp://. In that mode it sends via the AWS SDK's normal credential chain
# instead of an SMTP username/password, so no IAM user or static access key is
# needed - the existing IRSA role (aws_iam_role.langfuse_irsa, already trusted
# by the "langfuse" k8s service account) just needs SES send permissions. This
# also avoids the iam:CreateUser SCP deny some orgs enforce.
#
# NOTE: new AWS accounts start in the SES sandbox, where you can only send to
# verified recipient addresses. Request production access in the SES console
# before relying on this for inviting arbitrary teammates.

resource "aws_sesv2_email_identity" "this" {
  count          = var.enable_ses_smtp ? 1 : 0
  email_identity = var.domain

  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }

  tags = {
    Name = local.tag_name
  }
}

resource "aws_route53_record" "ses_dkim" {
  # Easy DKIM always issues exactly 3 tokens. for_each needs a plan-time-known
  # key set, and the tokens themselves are only known after apply, so index
  # into them by a static position (0, 1, 2) instead of using the tokens as keys.
  for_each = var.enable_ses_smtp ? toset(["0", "1", "2"]) : []

  zone_id = aws_route53_zone.zone.zone_id
  name    = "${aws_sesv2_email_identity.this[0].dkim_signing_attributes[0].tokens[tonumber(each.value)]}._domainkey.${var.domain}"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_sesv2_email_identity.this[0].dkim_signing_attributes[0].tokens[tonumber(each.value)]}.dkim.amazonses.com"]
}

# SES send permission for the IRSA role Langfuse's pods already assume -
# no IAM user/access key involved.
resource "aws_iam_role_policy" "langfuse_ses_send" {
  count = var.enable_ses_smtp ? 1 : 0
  name  = "ses-send"
  role  = aws_iam_role.langfuse_irsa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendRawEmail", "ses:SendEmail"]
      Resource = "*"
      Condition = {
        StringLike = {
          "ses:FromAddress" = "*@${var.domain}"
        }
      }
    }]
  })
}

locals {
  ses_connection_url = var.enable_ses_smtp ? "ses://${data.aws_region.current.id}" : ""
  ses_from_address   = coalesce(var.ses_from_address, "Langfuse <noreply@${var.domain}>")

  # Merged into local.additional_env_values in langfuse.tf so it survives even
  # if the caller also supplies their own var.additional_env (Helm replaces,
  # rather than merges, a values array across -f files).
  #
  # Both values are plain (non-secret) now that SMTP_CONNECTION_URL carries no
  # credentials - it's just "ses://<region>", with auth handled by the IRSA role.
  ses_additional_env = var.enable_ses_smtp ? [
    {
      name      = "SMTP_CONNECTION_URL"
      value     = local.ses_connection_url
      valueFrom = null
    },
    {
      name      = "EMAIL_FROM_ADDRESS"
      value     = local.ses_from_address
      valueFrom = null
    },
  ] : []
}
