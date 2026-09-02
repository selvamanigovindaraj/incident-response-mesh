#!/usr/bin/env bash
set -e

KEY_NAME="irm-sandbox-key"
SG_NAME="irm-sandbox-sg"

echo "==> 1. Terminating IRM Sandbox Instances..."
INSTANCE_IDS=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=irm-sandbox" "Name=instance-state-name,Values=pending,running,stopping,stopped" --query 'Reservations[*].Instances[*].InstanceId' --output text)

if [ -n "$INSTANCE_IDS" ]; then
    aws ec2 terminate-instances --instance-ids $INSTANCE_IDS >/dev/null
    echo "Terminating instances: $INSTANCE_IDS"
    echo "Waiting for instances to fully terminate before deleting Security Group..."
    aws ec2 wait instance-terminated --instance-ids $INSTANCE_IDS
else
    echo "No instances found with tag Name=irm-sandbox."
fi

echo "==> 2. Deleting Security Group..."
SG_ID=$(aws ec2 describe-security-groups --group-names "$SG_NAME" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [ -n "$SG_ID" ]; then
    aws ec2 delete-security-group --group-id "$SG_ID"
    echo "Deleted Security Group: $SG_ID ($SG_NAME)"
else
    echo "Security Group $SG_NAME not found."
fi

echo "==> 3. Deleting Key Pair from AWS (Local file kept at ~/.ssh/)..."
aws ec2 delete-key-pair --key-name "$KEY_NAME"
    rm -f "~/.ssh/$KEY_NAME.pem" 2>/dev/null || true
echo "Deleted Key Pair: $KEY_NAME"

echo "✅ Teardown complete!"
