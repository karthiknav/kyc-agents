#!/usr/bin/env python3
"""Terraform `external` data source program: derives an SES SMTP password
from an IAM secret access key.

Algorithm per https://docs.aws.amazon.com/ses/latest/dg/smtp-credentials.html
(version 0x04, region-independent).
"""
import base64
import hashlib
import hmac
import json
import sys

SMTP_PASSWORD_VERSION = b"\x04"
SIGNING_MESSAGE = b"SendRawEmail"


def main() -> None:
    query = json.load(sys.stdin)
    secret_access_key = query["secret_access_key"].encode("utf-8")
    signature = hmac.new(secret_access_key, SIGNING_MESSAGE, hashlib.sha256).digest()
    smtp_password = base64.b64encode(SMTP_PASSWORD_VERSION + signature).decode("utf-8")
    json.dump({"password": smtp_password}, sys.stdout)


if __name__ == "__main__":
    main()
