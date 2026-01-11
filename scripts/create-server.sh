#!/bin/bash
set -e

# All-in-One App Store Server Creation Script for OpenStack
# Installs: Frontend (Nginx) + Backend (FastAPI) + Database (PostgreSQL) + Redis

# Configuration
VM_NAME="appstore-server"
IMAGE_NAME="Ubuntu 22.04"
FLAVOR_NAME="gp1.large"  # Needs resources for Frontend + Backend + DB
NETWORK_NAME="DHBW"
KEY_NAME="appstore-server-key"
SECURITY_GROUP="appstore-sg"

echo "🚀 Creating All-in-One App Store Server on OpenStack..."

# Check OpenStack CLI
if ! openstack --version &> /dev/null; then
    echo "❌ OpenStack CLI not found. Install: pip install python-openstackclient"
    exit 1
fi

# Check authentication
if ! openstack token issue &> /dev/null; then
    echo "❌ Not authenticated. Please source your openrc file."
    exit 1
fi

# Create security group if not exists
if ! openstack security group show "$SECURITY_GROUP" &> /dev/null; then
    echo "📋 Creating security group: $SECURITY_GROUP"
    openstack security group create "$SECURITY_GROUP" \
        --description "Security group for All-in-One App Store Server"
    
    # SSH access
    openstack security group rule create "$SECURITY_GROUP" \
        --protocol tcp --dst-port 22 --remote-ip 0.0.0.0/0
    
    # HTTP (Frontend via Nginx)
    openstack security group rule create "$SECURITY_GROUP" \
        --protocol tcp --dst-port 80 --remote-ip 0.0.0.0/0
    
    # HTTPS (Frontend via Nginx)
    openstack security group rule create "$SECURITY_GROUP" \
        --protocol tcp --dst-port 443 --remote-ip 0.0.0.0/0
    
    # API access (FastAPI - optional, can be proxied through Nginx)
    openstack security group rule create "$SECURITY_GROUP" \
        --protocol tcp --dst-port 8000 --remote-ip 0.0.0.0/0
    
    # Outbound traffic
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

# Create cloud-init configuration
cat > cloud-init-server.yaml <<EOF
#cloud-config
package_update: true
package_upgrade: true

packages:
  - docker.io
  - docker-compose
  - nginx
  - git
  - curl
  - jq
  - python3
  - python3-pip
  - postgresql
  - postgresql-contrib
  - redis-tools
  - certbot
  - python3-certbot-nginx

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
  
  # Create application directory
  - mkdir -p /home/ubuntu/app-store
  - mkdir -p /home/ubuntu/app-store/frontend
  - chown -R ubuntu:ubuntu /home/ubuntu/app-store
  
  # Create backend .env template
  - |
    cat > /home/ubuntu/app-store/.env.template <<ENVEOF
    # Database Configuration
    DB_HOST=localhost
    DB_PORT=5432
    DB_NAME=appstore
    DB_USER=appstore_user
    DB_PASSWORD=CHANGE_ME_SECURE_PASSWORD
    
    # Redis Configuration
    REDIS_URL=redis://localhost:6379/0
    
    # Application Configuration
    SECRET_KEY=CHANGE_ME_GENERATE_SECURE_KEY
    DEBUG=false
    
    # OpenStack Configuration (if needed)
    OS_AUTH_URL=https://your-openstack-url.com:5000/v3
    OS_USERNAME=your-username
    OS_PASSWORD=your-password
    OS_PROJECT_NAME=your-project
    OS_USER_DOMAIN_NAME=Default
    OS_PROJECT_DOMAIN_NAME=Default
    ENVEOF
  
  - chown ubuntu:ubuntu /home/ubuntu/app-store/.env.template
  
  # Create frontend .env template
  - |
    cat > /home/ubuntu/app-store/frontend/.env.template <<FRONTENVEOF
    # Backend API Configuration (localhost since everything is on same server)
    VITE_API_BASE_URL=http://localhost:8000
    VITE_API_TIMEOUT=30000
    
    # Application Configuration
    VITE_APP_NAME=Teaching App Store
    VITE_APP_ENV=production
    FRONTENVEOF
  
  - chown ubuntu:ubuntu /home/ubuntu/app-store/frontend/.env.template
  
  # Create Nginx configuration for Frontend + API Proxy
  - |
    cat > /etc/nginx/sites-available/appstore <<'NGINXEOF'
    # Upstream for Backend API
    upstream backend_api {
        server localhost:8000;
    }
    
    server {
        listen 80;
        server_name _;
        
        # Frontend - served from /home/ubuntu/app-store/frontend/dist
        root /home/ubuntu/app-store/frontend/dist;
        index index.html;
        
        # Gzip compression
        gzip on;
        gzip_vary on;
        gzip_min_length 1024;
        gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml+rss application/json application/javascript;
        
        # API requests - proxy to FastAPI backend
        location /api/ {
            proxy_pass http://backend_api/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host \$host;
            proxy_cache_bypass \$http_upgrade;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
            
            # CORS headers (if needed)
            add_header 'Access-Control-Allow-Origin' '*' always;
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS' always;
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
            
            if (\$request_method = 'OPTIONS') {
                return 204;
            }
        }
        
        # Frontend routes - SPA fallback
        location / {
            try_files \$uri \$uri/ /index.html;
        }
        
        # Security headers
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;
        
        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
    NGINXEOF
  
  # Enable Nginx site
  - ln -sf /etc/nginx/sites-available/appstore /etc/nginx/sites-enabled/
  - rm -f /etc/nginx/sites-enabled/default
  - systemctl reload nginx || true
  
  # Create setup script
  - |
    cat > /home/ubuntu/setup-server.sh <<'SETUPEOF'
    #!/bin/bash
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║   App Store All-in-One Server Setup                       ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    echo "📝 Next steps to complete setup:"
    echo ""
    echo "1️⃣  Configure backend environment:"
    echo "   cd /home/ubuntu/app-store"
    echo "   cp .env.template .env"
    echo "   nano .env  # Set secure DB_PASSWORD and SECRET_KEY"
    echo ""
    echo "2️⃣  Configure frontend environment:"
    echo "   cd /home/ubuntu/app-store/frontend"
    echo "   cp .env.template .env"
    echo "   # (Already configured for localhost)"
    echo ""
    echo "3️⃣  Deploy backend + database:"
    echo "   cd /home/ubuntu/app-store"
    echo "   docker compose up -d"
    echo "   docker compose exec api alembic upgrade head"
    echo ""
    echo "4️⃣  Deploy frontend:"
    echo "   cd /home/ubuntu/app-store/frontend"
    echo "   # Option A: Docker"
    echo "   docker compose up -d"
    echo "   # Option B: Build and serve with Nginx"
    echo "   npm install && npm run build"
    echo "   sudo systemctl reload nginx"
    echo ""
    echo "5️⃣  Test the setup:"
    echo "   curl http://localhost:8000/health  # Backend"
    echo "   curl http://localhost              # Frontend"
    echo ""
    echo "📊 View logs:"
    echo "   # Backend logs"
    echo "   cd /home/ubuntu/app-store && docker compose logs -f"
    echo "   # Nginx logs"
    echo "   sudo tail -f /var/log/nginx/access.log"
    echo ""
    echo "🔍 Useful commands:"
    echo "   docker ps                          # List containers"
    echo "   sudo systemctl status nginx        # Nginx status"
    echo "   sudo nginx -t && sudo nginx -s reload  # Reload Nginx"
    echo ""
    SETUPEOF
  
  - chmod +x /home/ubuntu/setup-server.sh
  - chown ubuntu:ubuntu /home/ubuntu/setup-server.sh
  
  # Create PostgreSQL user and database (will be configured later)
  - sudo -u postgres psql -c "CREATE USER appstore_user WITH PASSWORD 'temp_password';" || true
  - sudo -u postgres psql -c "CREATE DATABASE appstore OWNER appstore_user;" || true
  - sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE appstore TO appstore_user;" || true

final_message: "All-in-One App Store server ready! SSH in and run ./setup-server.sh"
EOF

# Create the VM
echo "🖥️  Creating VM: $VM_NAME"
openstack server create \
    --image "$IMAGE_NAME" \
    --flavor "$FLAVOR_NAME" \
    --network "$NETWORK_NAME" \
    --key-name "$KEY_NAME" \
    --security-group "$SECURITY_GROUP" \
    --user-data cloud-init-server.yaml \
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
echo "✅ All-in-One App Store Server created successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "VM Name:       $VM_NAME"
echo "VM IP:         $VM_IP"
echo "SSH Key:       ${KEY_NAME}.pem"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 Next steps:"
echo "1. Wait ~2 minutes for cloud-init to complete"
echo ""
echo "2. SSH into the server:"
echo "   ssh -i ${KEY_NAME}.pem ubuntu@${VM_IP}"
echo ""
echo "3. Run setup instructions:"
echo "   ./setup-server.sh"
echo ""
echo "4. Configure backend environment:"
echo "   cd /home/ubuntu/app-store"
echo "   cp .env.template .env"
echo "   nano .env  # Set DB_PASSWORD and SECRET_KEY"
echo ""
echo "5. Configure frontend (optional - already set for localhost):"
echo "   cd /home/ubuntu/app-store/frontend"
echo "   cp .env.template .env"
echo ""
echo "6. Access your app:"
echo "   Frontend: http://${VM_IP}"
echo "   Backend:  http://${VM_IP}:8000"
echo "   API via Nginx: http://${VM_IP}/api/"
echo ""
echo "7. Add to your local ~/.ssh/config:"
echo "   Host appstore"
echo "       HostName ${VM_IP}"
echo "       User ubuntu"
echo "       IdentityFile $(pwd)/${KEY_NAME}.pem"
echo ""
echo "🔐 Security checklist:"
echo "   - Set secure DB_PASSWORD in .env"
echo "   - Generate SECRET_KEY: openssl rand -hex 32"
echo "   - Update PostgreSQL password: sudo -u postgres psql"
echo "   - (Optional) Setup SSL: sudo certbot --nginx"
