output "instance_id" {
  description = "Instance ID of the Windows bastion"
  value       = aws_instance.rdp_bastion.id
}

output "ssm_port_forward_command" {
  description = "Run this locally, then RDP to localhost:13389"
  value       = "aws ssm start-session --target ${aws_instance.rdp_bastion.id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"3389\"],\"localPortNumber\":[\"13389\"]}'"
}

output "admin_password" {
  description = "Windows Administrator password, set via user_data. Retrieve with: terraform output -raw admin_password"
  value       = random_password.admin.result
  sensitive   = true
}

output "admin_password_secret_arn" {
  description = "Secrets Manager secret ARN holding the same password. Retrieve with: aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text"
  value       = aws_secretsmanager_secret.admin_password.arn
}
