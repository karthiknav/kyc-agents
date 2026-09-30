output "instance_id" {
  description = "Instance ID of the Windows bastion"
  value       = aws_instance.rdp_bastion.id
}

output "ssm_port_forward_command" {
  description = "Run this locally, then RDP to localhost:13389"
  value       = "aws ssm start-session --target ${aws_instance.rdp_bastion.id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"3389\"],\"localPortNumber\":[\"13389\"]}'"
}

output "get_password_command" {
  description = "Run this locally with your key pair's .pem to retrieve the initial Administrator password"
  value       = "aws ec2 get-password-data --instance-id ${aws_instance.rdp_bastion.id} --priv-launch-key /path/to/${var.key_pair_name}.pem"
}
