#!/usr/bin/env bash
set -e

KEY_NAME="irm-sandbox-key"
SG_NAME="irm-sandbox-sg"
INSTANCE_TYPE="t3.xlarge"
AMI_ID="ami-040dc3b259ece28c6" # Ubuntu 22.04 LTS in us-east-1
KEY_PATH="$HOME/.ssh/$KEY_NAME.pem"

echo "==> 1. Setting up SSH Key Pair..."
if [ ! -f "$KEY_PATH" ]; then
    aws ec2 create-key-pair --key-name "$KEY_NAME" --query 'KeyMaterial' --output text > "$KEY_PATH"
    chmod 400 "$KEY_PATH"
    echo "Created key pair: $KEY_NAME"
else
    echo "Key pair already exists locally."
fi

echo "==> 2. Setting up Security Group..."
SG_ID=$(aws ec2 describe-security-groups --group-names "$SG_NAME" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [ -z "$SG_ID" ]; then
    VPC_ID=$(aws ec2 describe-vpcs --filters "Name=is-default,Values=true" --query 'Vpcs[0].VpcId' --output text)
    SG_ID=$(aws ec2 create-security-group --group-name "$SG_NAME" --description "SG for IRM Sandbox" --vpc-id "$VPC_ID" --query 'GroupId' --output text)
    
    # Allow SSH (22), Traefik/App (80), Chaos Dashboard (2333)
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22 --cidr 0.0.0.0/0 >/dev/null
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 2333 --cidr 0.0.0.0/0 >/dev/null
    echo "Created Security Group: $SG_ID"
else
    echo "Security Group already exists: $SG_ID"
fi

echo "==> 3. Requesting EC2 Spot Instance..."
USER_DATA=$(cat << 'UD'
#!/bin/bash
apt-get update
apt-get install -y docker.io make jq

# SAFETY DEAD-MAN SWITCH: Auto-shutdown and terminate instance after 3 hours (180 mins)
shutdown -P +180

systemctl start docker
systemctl enable docker
usermod -aG docker ubuntu
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 && bash get_helm.sh
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
UD
)

INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
    --instance-market-options '{"MarketType":"spot"}' \
    --user-data "$USER_DATA" \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=irm-sandbox}]' \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "Requested Spot Instance: $INSTANCE_ID"

echo "==> 4. Waiting for instance to be running and acquire public IP..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "Instance Public IP: $PUBLIC_IP"

echo "==> 5. Waiting for SSH and cloud-init to finish..."
# Wait for SSH to become available
while ! nc -z -w5 "$PUBLIC_IP" 22; do
  sleep 5
done
echo "SSH is up. Waiting for cloud-init to finish dependencies installation..."

# Ignore strict host key checking for automation
SSH_OPTS="-i $KEY_PATH -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

ssh $SSH_OPTS ubuntu@$PUBLIC_IP "cloud-init status --wait"

echo "==> 6. Syncing code to AWS..."
rsync -avz --exclude '.git' --exclude '.gemini' -e "ssh $SSH_OPTS" ./ ubuntu@$PUBLIC_IP:~/incident-response-mesh/

echo "==> 7. Bootstrapping Cluster on AWS (this will take 5-10 minutes)..."
# We run it in a login shell or with sg docker to ensure group permissions apply without reconnecting
ssh $SSH_OPTS ubuntu@$PUBLIC_IP "cd incident-response-mesh && sg docker -c 'make cluster-up victim-up monitoring-up chaos-up'"

echo "=========================================================="
echo "✅ DEPLOYMENT COMPLETE!"
echo "To SSH into the instance, run:"
echo "ssh -i $KEY_PATH ubuntu@$PUBLIC_IP"
echo "To access the apps from your browser:"
echo "Frontend: http://$PUBLIC_IP"
echo "To terminate the instance and save money, run: ./scripts/aws-teardown.sh"
echo "=========================================================="
