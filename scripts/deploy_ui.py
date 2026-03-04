#!/usr/bin/env python3
"""
After the UI CloudFormation stack is deployed (from deploy.sh): package frontend, sync to S3, invalidate CloudFront.
Expects stack {infra}-ui to exist. Uses ApiEndpoint from {infra}-api for build.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import boto3

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

DEFAULT_INFRA_STACK = "kyc-agent"
DEFAULT_REGION = "us-east-1"


def get_stack_output(cfn, stack_name: str, output_key: str) -> str | None:
    try:
        resp = cfn.describe_stacks(StackName=stack_name)
        for o in resp["Stacks"][0].get("Outputs", []):
            if o["OutputKey"] == output_key:
                return o["OutputValue"]
    except Exception:
        pass
    return None


def get_frontend_dist(region: str, api_stack: str, infra_stack: str) -> Path:
    """Build or get frontend dist path: run package_frontend.sh, or build in frontend/ with API URL."""
    package_script = SCRIPT_DIR / "package_frontend.sh"
    if package_script.exists():
        try:
            result = subprocess.run(
                [str(package_script)],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
            if result.returncode == 0 and result.stdout:
                raw = result.stdout.strip().splitlines()[-1].strip()
                p = Path(raw)
                if p.is_absolute():
                    dist = p
                else:
                    dist = (SCRIPT_DIR / raw).resolve()
                if dist.is_dir():
                    return dist
        except Exception:
            pass

    # Fallback: build frontend ourselves using API stack endpoint
    frontend_dir = REPO_ROOT / "frontend"
    if not frontend_dir.is_dir():
        print("❌ frontend/ not found", file=sys.stderr)
        sys.exit(1)
    cfn = boto3.client("cloudformation", region_name=region)
    api_endpoint = get_stack_output(cfn, api_stack, "ApiEndpoint")
    if not api_endpoint:
        print(f"❌ ApiEndpoint not found in stack {api_stack}. Deploy API stack first.", file=sys.stderr)
        sys.exit(1)
    api_base = api_endpoint.rstrip("/")
    env = os.environ.copy()
    env["VITE_API_BASE_URL"] = api_base
    npm = "npm.cmd" if os.name == "nt" else "npm"
    for cmd in [["install"], ["run", "build"]]:
        r = subprocess.run([npm] + cmd, cwd=frontend_dir, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr or r.stdout, file=sys.stderr)
            sys.exit(1)
    dist = frontend_dir / "dist"
    if not dist.is_dir():
        print("❌ frontend/dist not found after build", file=sys.stderr)
        sys.exit(1)
    return dist


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy KYC UI stack and sync frontend")
    parser.add_argument(
        "infra_stack",
        nargs="?",
        default=os.environ.get("INFRA_STACK_NAME", DEFAULT_INFRA_STACK),
        help=f"Infra stack name (default: {DEFAULT_INFRA_STACK})",
    )
    parser.add_argument(
        "region",
        nargs="?",
        default=os.environ.get("AWS_DEFAULT_REGION", DEFAULT_REGION),
        help=f"AWS region (default: {DEFAULT_REGION})",
    )
    args = parser.parse_args()

    infra = args.infra_stack.strip()
    region = args.region.strip()
    ui_stack = f"{infra}-ui"
    api_stack = f"{infra}-api"
    print(f"[1/4] Packaging frontend (stack: {ui_stack}, region: {region})...")
    dist_dir = get_frontend_dist(region, api_stack, infra)
    print(f"  Frontend dist: {dist_dir}")

    cfn = boto3.client("cloudformation", region_name=region)
    bucket = get_stack_output(cfn, ui_stack, "StaticBucketName")
    if not bucket:
        print("❌ StaticBucketName not found in UI stack", file=sys.stderr)
        sys.exit(1)
    print("[2/4] Syncing frontend to S3...")
    subprocess.run(
        ["aws", "s3", "sync", str(dist_dir), f"s3://{bucket}/", "--delete", "--region", region],
        cwd=REPO_ROOT,
        check=True,
    )
    print("  ✓ Frontend synced")

    dist_id = get_stack_output(cfn, ui_stack, "DistributionId")
    if dist_id:
        print("[3/4] Invalidating CloudFront cache...")
        subprocess.run(
            ["aws", "cloudfront", "create-invalidation", "--distribution-id", dist_id, "--paths", "/*"],
            capture_output=True,
        )
        print("  ✓ Invalidation requested")

    ui_url = get_stack_output(cfn, ui_stack, "WebsiteUrl")
    print("[4/4] Done.")
    if ui_url:
        print(f"  KYC UI: {ui_url}")


if __name__ == "__main__":
    main()
