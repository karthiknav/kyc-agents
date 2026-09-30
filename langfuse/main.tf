terraform {
  backend "s3" {
    bucket  = "kyc-agent-artifacts-360946915124-us-east-1"
    key     = "langfuse/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = "us-east-1"
}

module "langfuse" {
  source = "./langfuse-terraform-aws"

  name   = "langfuse"
  domain = "langfuse.gen-ai-designs.com"

  # 👇 your existing VPC
  vpc_id             = "vpc-047cc3057ce1bf76f"
  private_subnet_ids = ["subnet-07ca4afcf672d8520", "subnet-03fec9b5914db68ff"]
  public_subnet_ids  = ["subnet-0d1fb58fd1f9c49dc", "subnet-0a16166ebd67199fb"]

  private_route_table_ids = ["rtb-0a6f230d58b1d860c"]

  # SES SMTP for transactional email (fixes "Missing environment variables for
  # sending membership invitation email"). Requires python3 on the machine
  # running terraform apply, and SES production access for inviting anyone
  # other than a pre-verified recipient (new accounts start in the SES sandbox).
  enable_ses_smtp = true
}

provider "kubernetes" {
  host                   = module.langfuse.cluster_host
  cluster_ca_certificate = module.langfuse.cluster_ca_certificate
  token                  = module.langfuse.cluster_token

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.langfuse.cluster_name]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.langfuse.cluster_host
    cluster_ca_certificate = module.langfuse.cluster_ca_certificate
    token                  = module.langfuse.cluster_token

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.langfuse.cluster_name]
    }
  }
}

