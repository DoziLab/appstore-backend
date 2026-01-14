#!/usr/bin/env python3
"""Script to add DoziLab Dashboard template with Heat file."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import SessionLocal, init_db
from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import User

# Initialize database models
init_db()


HEAT_TEMPLATE_CONTENT = """heat_template_version: "2018-08-31"
description: VM with Security Group + Floating IP + cloud-init DoziLab Dashboard (SSH + HTTP)

parameters:
  image:
    type: string
    default: "Ubuntu 22.04 2025-01"

  flavor:
    type: string
    default: "gp1.small"

  network:
    type: string
    description: Internal tenant network for the VM
    default: "NAT"

  external_network:
    type: string
    description: Network that provides Floating IPs
    default: "DHBW"

  key_name:
    type: string
    description: OpenStack keypair name to inject into the VM
    default: "heat-bastion-key"

  ssh_cidr:
    type: string
    description: Who may SSH to the VM (use your public IP /32 for safety)
    default: "0.0.0.0/0"

  page_title:
    type: string
    default: "DoziLab — Mini Dashboard"

  stack_label:
    type: string
    default: "heat-vm-fip"

resources:
  secgroup:
    type: OS::Neutron::SecurityGroup
    properties:
      description: Allow SSH + HTTP + ICMP
      rules:
        - direction: ingress
          ethertype: IPv4
          protocol: tcp
          port_range_min: 22
          port_range_max: 22
          remote_ip_prefix: { get_param: ssh_cidr }

        - direction: ingress
          ethertype: IPv4
          protocol: tcp
          port_range_min: 80
          port_range_max: 80
          remote_ip_prefix: 0.0.0.0/0

        - direction: ingress
          ethertype: IPv4
          protocol: icmp
          remote_ip_prefix: 0.0.0.0/0

  port:
    type: OS::Neutron::Port
    properties:
      network: { get_param: network }
      security_groups:
        - { get_resource: secgroup }

  server:
    type: OS::Nova::Server
    properties:
      name: heat-vm-ssh
      image: { get_param: image }
      flavor: { get_param: flavor }
      key_name: { get_param: key_name }

      user_data_format: RAW
      user_data:
        str_replace:
          params:
            __PAGE_TITLE__: { get_param: page_title }
            __STACK_LABEL__: { get_param: stack_label }
          template: |-
            #!/bin/bash
            set -euxo pipefail
            export DEBIAN_FRONTEND=noninteractive

            TITLE="__PAGE_TITLE__"
            LABEL="__STACK_LABEL__"

            echo "cloud-init started $(date -Is)" > /var/log/cloud-init-custom.log

            apt-get update -y
            apt-get install -y nginx curl

            PRIVATE_IP="$(hostname -I | awk '{print $1}')"
            HOST="$(hostname)"
            DEPLOY_TIME="$(date -Is)"
            UPTIME="$(uptime -p || true)"

            # nginx header + hardening
            cat >/etc/nginx/conf.d/dozilab.conf <<EOF
            add_header X-DoziLab-Stack "${LABEL}" always;
            server_tokens off;
            EOF

            # create HTML with placeholders (no command substitutions inside HTML)
            cat >/var/www/html/index.html <<'HTML'
            <!doctype html>
            <html lang="de">
            <head>
              <meta charset="utf-8"/>
              <meta name="viewport" content="width=device-width, initial-scale=1"/>
              <title>__TITLE__</title>
              <style>
                body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Arial; margin: 0; background: #0b1020; color: #e7e9ee; }
                .wrap { max-width: 920px; margin: 0 auto; padding: 28px 18px 60px; }
                .card { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 18px; margin-top: 14px; }
                h1 { margin: 8px 0 0; font-size: 28px; }
                .sub { opacity: .8; margin-top: 6px; }
                .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
                .k { opacity: .75; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
                .v { font-size: 16px; margin-top: 6px; }
                .pill { display: inline-block; padding: 4px 10px; border-radius: 999px; background: rgba(0,255,170,0.12); border: 1px solid rgba(0,255,170,0.25); }
                pre { background: rgba(0,0,0,0.35); padding: 12px; border-radius: 12px; overflow: auto; }
                @media (max-width: 700px){ .grid { grid-template-columns: 1fr; } }
              </style>
            </head>
            <body>
              <div class="wrap">
                <div class="card">
                  <div class="pill">LIVE</div>
                  <h1>__TITLE__</h1>
                  <div class="sub">Deployed via Heat + cloud-init • <b>__DEPLOY_TIME__</b></div>
                </div>

                <div class="grid">
                  <div class="card">
                    <div class="k">Stack / Label</div>
                    <div class="v">__LABEL__</div>
                  </div>
                  <div class="card">
                    <div class="k">Hostname</div>
                    <div class="v">__HOST__</div>
                  </div>
                  <div class="card">
                    <div class="k">Private IP</div>
                    <div class="v">__PRIVATE_IP__</div>
                  </div>
                  <div class="card">
                    <div class="k">Uptime</div>
                    <div class="v">__UPTIME__</div>
                  </div>
                </div>

                <div class="card">
                  <div class="k">Nginx Status</div>
                  <div class="v"><pre>__NGINX_STATUS__</pre></div>
                  <div class="sub">Header check: <code>curl -I http://&lt;FIP&gt;</code> → <code>X-DoziLab-Stack</code></div>
                </div>

                <div class="card">
                  <div class="k">ASCII vibes</div>
                  <pre>
              ____            _ _      _
              |  _ \\  ___  ___(_) | ___| |__
              | | | |/ _ \\/ __| | |/ _ \\ '_ \\
              | |_| | (_) \\__ \\ | |  __/ |_) |
              |____/ \\___/|___/_|_|\\___|_.__/
                  </pre>
                </div>
              </div>
            </body>
            </html>
            HTML

            # compute nginx status after config + before restart
            NGINX_STATUS="$(systemctl is-active nginx || true)"

            # replace placeholders safely
            sed -i \\
              -e "s|__TITLE__|${TITLE}|g" \\
              -e "s|__LABEL__|${LABEL}|g" \\
              -e "s|__HOST__|${HOST}|g" \\
              -e "s|__PRIVATE_IP__|${PRIVATE_IP}|g" \\
              -e "s|__DEPLOY_TIME__|${DEPLOY_TIME}|g" \\
              -e "s|__UPTIME__|${UPTIME}|g" \\
              -e "s|__NGINX_STATUS__|${NGINX_STATUS}|g" \\
              /var/www/html/index.html

            systemctl enable nginx
            systemctl restart nginx

            echo "cloud-init finished $(date -Is)" >> /var/log/cloud-init-custom.log

      networks:
        - port: { get_resource: port }

  fip:
    type: OS::Neutron::FloatingIP
    properties:
      floating_network: { get_param: external_network }

  fip_assoc:
    type: OS::Neutron::FloatingIPAssociation
    properties:
      floatingip_id: { get_resource: fip }
      port_id: { get_resource: port }

outputs:
  floating_ip:
    description: Public Floating IP (reachable from outside)
    value: { get_attr: [fip, floating_ip_address] }

  http_url:
    description: URL of the dashboard (HTTP)
    value:
      str_replace:
        template: "http://FIP/"
        params:
          FIP: { get_attr: [fip, floating_ip_address] }

  ssh_command:
    description: SSH command to connect from your PC
    value:
      str_replace:
        template: "ssh -i ~/.ssh/heat-bastion-key.pem ubuntu@FIP"
        params:
          FIP: { get_attr: [fip, floating_ip_address] }

  private_ip:
    description: Private IP on tenant network (NAT)
    value: { get_attr: [port, fixed_ips, 0, ip_address] }

  server_id:
    description: Nova server (instance) ID
    value: { get_resource: server }

  security_group_id:
    description: Security group ID created by this stack
    value: { get_resource: secgroup }

  port_id:
    description: Neutron port ID of the instance
    value: { get_resource: port }
"""


def main():
    """Add DoziLab Dashboard template to database."""
    db = SessionLocal()
    
    try:
        # Get first user (or create a dummy one)
        user = db.query(User).first()
        if not user:
            print("ERROR: No users found in database. Please create a user first.")
            return
        
        print(f"Using user: {user.id}")
        
        # Create Template
        template = Template(
            name="DoziLab Dashboard VM",
            description="Simple Ubuntu VM with nginx serving a dashboard page. Includes Security Group, Floating IP, and cloud-init configuration.",
            owner_id=user.id,
            repo_url="https://github.com/dozilab/heat-templates",
            visibility=TemplateVisibility.PUBLIC,
            approval_status=TemplateApprovalStatus.APPROVED
        )
        db.add(template)
        db.flush()  # Get ID without committing
        
        print(f"✓ Created template: {template.id}")
        
        # Create Template Version
        version = TemplateVersion(
            template_id=template.id,
            git_commit_sha="v1.0.0-initial",
            is_active=True
        )
        db.add(version)
        db.flush()
        
        print(f"✓ Created version: {version.id}")
        
        # Create Template Version File (Heat Template)
        heat_file = TemplateVersionFile(
            template_version_id=version.id,
            file_name="heat.yaml",
            file_type=FileType.HEAT_TEMPLATE,
            file_path="templates/dozilab-dashboard/heat.yaml",
            content=HEAT_TEMPLATE_CONTENT,
            file_size=len(HEAT_TEMPLATE_CONTENT.encode('utf-8')),
            description="Main Heat template for DoziLab Dashboard VM deployment",
            is_primary=True,
            order=1
        )
        db.add(heat_file)
        
        print(f"✓ Created heat file: {heat_file.id}")
        
        # Commit all changes
        db.commit()
        
        print("\n" + "="*80)
        print("SUCCESS! Template created successfully!")
        print("="*80)
        print(f"\nTemplate ID:  {template.id}")
        print(f"Version ID:   {version.id}")
        print(f"File ID:      {heat_file.id}")
        print("\nYou can now test the print task with:")
        print("  docker compose exec api python -c \"")
        print("  from src.tasks.deploy_tasks import print_template_version_files")
        print(f"  print_template_version_files('{version.id}')\"")
        print()
        
    except Exception as e:
        db.rollback()
        print(f"\n❌ ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
