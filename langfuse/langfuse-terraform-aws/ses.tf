# SES domain identity + IAM SMTP user, used so Langfuse can send transactional
# email (e.g. "Missing environment variables for sending membership invitation
# email" is fixed by wiring SMTP_CONNECTION_URL / EMAIL_FROM_ADDRESS below).
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

resource "aws_iam_user" "ses_smtp" {
  count = var.enable_ses_smtp ? 1 : 0
  name  = "${var.name}-ses-smtp"
  path  = "/system/"

  tags = {
    Name = local.tag_name
  }
}

resource "aws_iam_access_key" "ses_smtp" {
  count = var.enable_ses_smtp ? 1 : 0
  user  = aws_iam_user.ses_smtp[0].name
}

resource "aws_iam_user_policy" "ses_smtp_send" {
  count = var.enable_ses_smtp ? 1 : 0
  name  = "${var.name}-ses-send"
  user  = aws_iam_user.ses_smtp[0].name

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

# Derives the SES SMTP password from the IAM secret access key. SES SMTP
# credentials are NOT the same as IAM access keys - see scripts/ses_smtp_password.py.
# Requires python3 on the machine running `terraform apply`.
data "external" "ses_smtp_password" {
  count = var.enable_ses_smtp ? 1 : 0

  program = ["python3", "${path.module}/scripts/ses_smtp_password.py"]

  query = {
    secret_access_key = aws_iam_access_key.ses_smtp[0].secret
  }
}

locals {
  ses_smtp_endpoint       = "email-smtp.${data.aws_region.current.id}.amazonaws.com"
  ses_smtp_connection_url = var.enable_ses_smtp ? "smtp://${urlencode(aws_iam_access_key.ses_smtp[0].id)}:${urlencode(data.external.ses_smtp_password[0].result.password)}@${local.ses_smtp_endpoint}:587" : ""
  ses_from_address        = coalesce(var.ses_from_address, "Langfuse <noreply@${var.domain}>")

  # Merged into local.additional_env_values in langfuse.tf so it survives even
  # if the caller also supplies their own var.additional_env (Helm replaces,
  # rather than merges, a values array across -f files).
  #
  # Built with a single `for ... if` expression rather than a `cond ? [...] : []`
  # ternary: the two list entries below have different-shaped "value"/"valueFrom"
  # attributes, and Terraform can't unify that tuple's type against the empty-list
  # false-branch of a conditional ("Inconsistent conditional result types"). A
  # for-expression doesn't need to unify branch types, so it doesn't hit that.
  ses_additional_env = [
    for entry in [
      {
        name  = "SMTP_CONNECTION_URL"
        value = null
        valueFrom = {
          secretKeyRef = {
            name = "langfuse"
            key  = "smtp-connection-url"
          }
          configMapKeyRef = null
        }
      },
      {
        name      = "EMAIL_FROM_ADDRESS"
        value     = local.ses_from_address
        valueFrom = null
      },
    ] : entry if var.enable_ses_smtp
  ]
}
