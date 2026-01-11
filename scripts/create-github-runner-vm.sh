#!/bin/bash
set -e

# OpenStack GitHub Runner VM Creation Script
# This script creates a lightweight Ubuntu VM for GitHub self-hosted runner

# Configuration
VM_NAME="github-runner"
IMAGE_NAME="Ubuntu 22.04"
FLAVOR_NAME="gp1.small"  # Adjust based on your OpenStack flavors
NETWORK_NAME="DHBW"   # Adjust based on your network setup
KEY_NAME="github-runner-key"
SECURITY_GROUP="github-runner-sg"

echo "🚀 Creating GitHub Runner VM on OpenStack..."

# Check if OpenStack CLI is configured
if ! openstack --version &> /dev/null; then
    echo "❌ OpenStack CLI not found. Please install: pip install python-openstackclient"
    exit 1
fi

# Check authentication
if ! openstack token issue &> /dev/null; then
    echo "❌ Not authenticated with OpenStack. Please source your openrc file."
    exit 1
fi

# Create security group if not exists
if ! openstack security group show "$SECURITY_GROUP" &> /dev/null; then
    echo "📋 Creating security group: $SECURITY_GROUP"
    openstack security group create "$SECURITY_GROUP" \
        --description "Security group for GitHub runner"
    
    # Allow SSH
    openstack security group rule create "$SECURITY_GROUP" \
        --protocol tcp --dst-port 22 --remote-ip 0.0.0.0/0
    
    # Allow outbound traffic
    openstack security group rule create "$SECURITY_GROUP" \
        --protocol tcp --egress
    
    openstack security group rule create "$SECURITY_GROUP" \
        --protocol udp --egress
    
    echo "✅ Security group created"
else
    echo "✅ Security group already exists"
fi

# Create SSH key pair if not exists
if ! openstack keypair show "$KEY_NAME" &> /dev/null; then
    echo "🔑 Creating SSH key pair: $KEY_NAME"
    openstack keypair create "$KEY_NAME" > "${KEY_NAME}.pem"
    chmod 600 "${KEY_NAME}.pem"
    echo "✅ SSH key saved to: ${KEY_NAME}.pem"
else
    echo "✅ SSH key pair already exists"
fi

# Create cloud-init user data
cat > cloud-init-runner.yaml <<EOF
#cloud-config
package_update: true
package_upgrade: true

packages:
  - docker.io
  - docker-compose
  - git
  - curl
  - jq
  - python3
  - python3-pip
  - postgresql-client
  - redis-tools

runcmd:
  # Add ubuntu user to docker group
  - usermod -aG docker ubuntu
  
  # Enable and start Docker
  - systemctl enable docker
  - systemctl start docker
  
  # Install Docker Compose v2
  - mkdir -p /usr/local/lib/docker/cli-plugins
  - curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
  - chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  
  # Create runner directory
  - mkdir -p /home/ubuntu/actions-runner
  - chown -R ubuntu:ubuntu /home/ubuntu/actions-runner
  
  # Download and extract GitHub Actions runner
  - cd /home/ubuntu/actions-runner
  - export RUNNER_VERSION=\$(curl -s https://api.github.com/repos/actions/runner/releases/latest | jq -r '.tag_name' | sed 's/v//')
  - curl -o actions-runner-linux-x64-\${RUNNER_VERSION}.tar.gz -L https://github.com/actions/runner/releases/download/v\${RUNNER_VERSION}/actions-runner-linux-x64-\${RUNNER_VERSION}.tar.gz
  - tar xzf actions-runner-linux-x64-\${RUNNER_VERSION}.tar.gz
  - chown -R ubuntu:ubuntu /home/ubuntu/actions-runner
  - rm actions-runner-linux-x64-\${RUNNER_VERSION}.tar.gz
  
  # Install runner dependencies
  - cd /home/ubuntu/actions-runner
  - sudo -u ubuntu ./bin/installdependencies.sh
  
  # Create startup script
  - echo '#!/bin/bash' > /home/ubuntu/setup-runner.sh
  - echo 'cd /home/ubuntu/actions-runner' >> /home/ubuntu/setup-runner.sh
  - echo 'echo "Configure the runner with:"' >> /home/ubuntu/setup-runner.sh
  - echo 'echo "./config.sh --url https://github.com/YOUR_ORG/appstore-backend --token YOUR_TOKEN"' >> /home/ubuntu/setup-runner.sh
  - echo 'echo "./run.sh"' >> /home/ubuntu/setup-runner.sh
  - chmod +x /home/ubuntu/setup-runner.sh
  - chown ubuntu:ubuntu /home/ubuntu/setup-runner.sh

final_message: "GitHub Runner VM setup complete! SSH in and run /home/ubuntu/setup-runner.sh"
EOF

# Create the VM
echo "🖥️  Creating VM: $VM_NAME"
openstack server create \
    --image "$IMAGE_NAME" \
    --flavor "$FLAVOR_NAME" \
    --network "$NETWORK_NAME" \
    --key-name "$KEY_NAME" \
    --security-group "$SECURITY_GROUP" \
    --user-data cloud-init-runner.yaml \
    "$VM_NAME"

# Wait for VM to be active
echo "⏳ Waiting for VM to become active..."
while [ "$(openstack server show "$VM_NAME" -f value -c status)" != "ACTIVE" ]; do
    sleep 5
    echo -n "."
done
echo ""

# Get VM IP address
VM_IP=$(openstack server show "$VM_NAME" -f value -c addresses | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)

echo ""
echo "✅ VM created successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "VM Name:       $VM_NAME"
echo "VM IP:         $VM_IP"
echo "SSH Key:       ${KEY_NAME}.pem"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 Next steps:"
echo "1. Wait ~2 minutes for cloud-init to complete"
echo "2. SSH into the VM:"
echo "   ssh -i ${KEY_NAME}.pem ubuntu@${VM_IP}"
echo ""
echo "3. Get GitHub runner token from:"
echo "   https://github.com/YOUR_ORG/appstore-backend/settings/actions/runners/new"
echo ""
echo "4. Configure the runner:"
echo "   cd /home/ubuntu/actions-runner"
echo "   ./config.sh --url https://github.com/YOUR_ORG/appstore-backend --token YOUR_TOKEN"
echo "   ./run.sh"
echo ""
echo "5. (Optional) Install as a service:"
echo "   sudo ./svc.sh install"
echo "   sudo ./svc.sh start"
echo ""
echo "🔐 Security group: $SECURITY_GROUP"
echo "🔑 SSH Key saved to: ${KEY_NAME}.pem (keep this secure!)"
