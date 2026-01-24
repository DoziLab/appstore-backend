"""Seed mock data for development and testing."""
import logging
from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import User

logger = logging.getLogger(__name__)


MOCK_APP_YAML = """app:
  name: dozilab-multistudent-ubuntu
  version: 1.0.0
  description: >
    Deploy one Ubuntu VM for a course with multiple local student accounts (username/password),
    SSH allowed only from DHBW/VPN CIDR, and a Floating IP on DHBW.
    Backend can wait for DOZILAB_READY marker in the Nova console log.
  owner_team: dozilab-app-team

artifacts:
  heat_template: heat/main.yaml
  cloud_init: cloud-init/user-data.yaml

# Parameters exposed to the AppStore UI.
# Keep only what is meaningful for users; platform-fixed settings are hidden or fixed via allowed_values in Heat.
parameters:
  stack_label:
    type: string
    default: multistudent
    required: true
    description: Short course/stack label used in VM name and metadata (e.g. kurs-01). Must match ^[a-z0-9][a-z0-9-]{0,30}$

  image:
    type: string
    default: "Ubuntu 22.04 2025-01"
    required: true
    description: "Base image for the VM (restricted to known good images)."

  flavor:
    type: string
    default: "gp1.small"
    required: true
    description: "VM size. Keep small/medium for student workloads."

  ssh_cidr:
    type: string
    default: "141.72.0.0/16"
    required: true
    description: IPv4 CIDR allowed to SSH and ICMP (ping). Default is DHBW/VPN range. Examples 141.72.0.0/16 (VPN/Campus) or 1.2.3.4/32 (single IP).

  students:
    type: string
    required: true
    description: JSON string mapping username to password. Example {"alice":"pw","bob":"pw2"} (must use double quotes).

  force_password_change:
    type: boolean
    default: true
    required: true
    description: "If true, student users must change their password on first login."

  workdir:
    type: string
    default: "work"
    required: true
    description: "Directory created under each student's home and used as default login directory."

  pw_min_length:
    type: number
    default: 12
    required: true
    description: "Minimum password length enforced via PAM pwquality."

  pw_require_digit:
    type: boolean
    default: true
    required: true
    description: "Require at least one digit."

  pw_require_upper:
    type: boolean
    default: true
    required: true
    description: "Require at least one uppercase letter."

  pw_require_special:
    type: boolean
    default: true
    required: true
    description: "Require at least one special character."

outputs:
  - name: floating_ip
    from_heat_output: floating_ip
    description: "Public floating IP address."

  - name: server_id
    from_heat_output: server_id
    description: "Nova server ID (useful for console-log polling)."

  - name: ssh_hint
    from_heat_output: ssh_hint
    description: "How students login (template string)."

  - name: ready_marker
    from_heat_output: ready_marker
    description: "Marker string that appears in Nova console log when provisioning is done. Also nach was müsst ihr im log ausschau halten dass ihr wisst dass die VM Ready ist"
"""

MOCK_HEAT_TEMPLATE = """heat_template_version: 2018-08-31

description: >
  DoziLab Multi-Student VM: Ubuntu VM + Floating IP + password SSH for multiple users.

parameters:
  image:
    type: string
    default: "Ubuntu 22.04 2025-01"
    constraints:
      - allowed_values:
          - "Ubuntu 22.04 2025-01"
          - "Ubuntu 24.04 2025-01"
          - "Ubuntu 24.04 2026-01"
    description: "Base image for the VM."

  flavor:
    type: string
    default: "gp1.small"
    constraints:
      - allowed_values:
          - "gp1.small"
          - "gp1.medium"
    description: "VM size. Keep small/medium for student workloads."

  network:
    type: string
    default: "NAT"
    constraints:
      - allowed_values: ["NAT"]

  external_network:
    type: string
    default: "DHBW"
    constraints:
      - allowed_values: ["DHBW"]

  key_name:
    type: string
    default: "heat-bastion-key"
    constraints:
      - allowed_values: ["heat-bastion-key"]
    description: "Admin/support SSH keypair (später erweiterbar)"

  ssh_cidr:
    type: string
    default: "141.72.0.0/16"
    constraints:
      - allowed_pattern: '^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$'
    description: "IPv4 CIDR allowed to SSH (default DHBW/VPN)."

  students:
    type: string
    description: 'JSON string map username->password. Example: {"alice":"pw","bob":"pw2"}'
    constraints:
      - length: { min: 2 }

  force_password_change:
    type: boolean
    default: true

  workdir:
    type: string
    default: "work"
    constraints:
      - allowed_pattern: '^[A-Za-z0-9._-]{1,32}$'
    description: "Work directory under each user's home (e.g. work)."

  stack_label:
    type: string
    default: "multistudent"
    constraints:
      - allowed_pattern: '^[a-z0-9][a-z0-9-]{0,30}$'
    description: "Internal label used for resource names/metadata."

  pw_min_length:
    type: number
    default: 12
    constraints:
      - range: { min: 4, max: 128 }

  pw_require_digit:
    type: boolean
    default: true

  pw_require_upper:
    type: boolean
    default: true

  pw_require_special:
    type: boolean
    default: true

resources:
  secgroup:
    type: OS::Neutron::SecurityGroup
    properties:
      description: Allow SSH + ICMP (VPN/Campus only)
      rules:
        - direction: ingress
          ethertype: IPv4
          protocol: tcp
          port_range_min: 22
          port_range_max: 22
          remote_ip_prefix: { get_param: ssh_cidr }

        - direction: ingress
          ethertype: IPv4
          protocol: icmp
          remote_ip_prefix: { get_param: ssh_cidr }

  port:
    type: OS::Neutron::Port
    properties:
      network: { get_param: network }
      security_groups:
        - { get_resource: secgroup }

  server:
    type: OS::Nova::Server
    properties:
      name:
        str_replace:
          template: "dozilab-STACK"
          params:
            STACK: { get_param: stack_label }

      image: { get_param: image }
      flavor: { get_param: flavor }
      key_name: { get_param: key_name }

      networks:
        - port: { get_resource: port }

      metadata:
        dozilab_stack_label: { get_param: stack_label }
        dozilab_ready_marker: "DOZILAB_READY"

      user_data_format: RAW
      user_data:
        str_replace:
          template: { get_file: ../cloud-init/user-data.yaml }
          params:
            __STUDENTS_JSON__: { get_param: students }
            __FORCE_CHANGE__: { get_param: force_password_change }
            __WORKDIR__: { get_param: workdir }

            __PW_MIN_LENGTH__: { get_param: pw_min_length }
            __PW_REQUIRE_DIGIT__: { get_param: pw_require_digit }
            __PW_REQUIRE_UPPER__: { get_param: pw_require_upper }
            __PW_REQUIRE_SPECIAL__: { get_param: pw_require_special }

            __STACK_LABEL__: { get_param: stack_label }

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
    value: { get_attr: [fip, floating_ip_address] }

  server_id:
    description: "Nova server ID (useful for console-log polling)"
    value: { get_resource: server }

  ssh_hint:
    description: "Students login like: ssh <username>@<floating_ip>"
    value:
      str_replace:
        template: "ssh <username>@FIP"
        params:
          FIP: { get_attr: [fip, floating_ip_address] }

  ready_marker:
    description: "Backend should wait until this marker appears in the Nova console log"
    value:
      str_replace:
        template: "DOZILAB_READY stack=STACK"
        params:
          STACK: { get_param: stack_label }
"""

MOCK_CLOUD_INIT = """#cloud-config
package_update: true
package_upgrade: false

packages:
  - libpam-pwquality
  - python3

write_files:
  - path: /usr/local/bin/dozilab-multiuser-setup.sh
    permissions: "0755"
    content: |
      #!/usr/bin/env bash
      set -euo pipefail

      LOG="/var/log/dozilab-multiuser.log"
      MARK_DIR="/var/lib/dozilab"
      READY_FILE="${MARK_DIR}/ready"
      FAIL_FILE="${MARK_DIR}/failed"

      STACK_LABEL="__STACK_LABEL__"

      # IMPORTANT: must be valid JSON (double quotes). Keep single quotes around JSON to prevent $ expansion.
      STUDENTS_JSON='__STUDENTS_JSON__'
      FORCE="__FORCE_CHANGE__"
      WORKDIR="__WORKDIR__"

      PW_MIN_LENGTH="__PW_MIN_LENGTH__"
      PW_REQUIRE_DIGIT="__PW_REQUIRE_DIGIT__"
      PW_REQUIRE_UPPER="__PW_REQUIRE_UPPER__"
      PW_REQUIRE_SPECIAL="__PW_REQUIRE_SPECIAL__"

      mkdir -p "$MARK_DIR"
      echo "multiuser setup started $(date -Is)" > "$LOG"

      on_fail() {
        rc=$?
        msg="DOZILAB_FAILED stack=${STACK_LABEL} rc=${rc} time=$(date -Is)"
        echo "$msg" | tee -a "$LOG" | tee /dev/console > "$FAIL_FILE"
        chmod 644 "$FAIL_FILE" || true
        exit "$rc"
      }
      trap on_fail ERR

      to_bool() {
        local v="${1:-}"
        v="$(echo "$v" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
        [[ "$v" == "1" || "$v" == "true" || "$v" == "yes" || "$v" == "on" ]]
      }

      # --- Build deterministic pwquality options from Heat params ---
      DCREDIT=0
      UCREDIT=0
      OCREDIT=0
      if to_bool "$PW_REQUIRE_DIGIT"; then DCREDIT=-1; fi
      if to_bool "$PW_REQUIRE_UPPER"; then UCREDIT=-1; fi
      if to_bool "$PW_REQUIRE_SPECIAL"; then OCREDIT=-1; fi
      if ! [[ "$PW_MIN_LENGTH" =~ ^[0-9]+$ ]]; then PW_MIN_LENGTH=12; fi

      # Enforce exactly what the UI exposes (no dict/diff surprise checks)
      # NOTE: this affects password setting (chpasswd) AND interactive passwd.
      PWQ_OPTS="retry=3 enforce_for_root minlen=${PW_MIN_LENGTH} dcredit=${DCREDIT} ucredit=${UCREDIT} ocredit=${OCREDIT} dictcheck=0 usercheck=0 gecoscheck=0 difok=0 maxrepeat=0 minclass=0"

      # Keep pwquality.conf consistent for debugging/inspection (PAM line is the source of truth)
      cat >/etc/security/pwquality.conf <<EOF
      # Managed by DoziLab (cloud-init). NOTE: PAM options override this file.
      minlen = ${PW_MIN_LENGTH}
      dcredit = ${DCREDIT}
      ucredit = ${UCREDIT}
      ocredit = ${OCREDIT}
      dictcheck = 0
      usercheck = 0
      gecoscheck = 0
      difok = 0
      maxrepeat = 0
      minclass = 0
      EOF

      # --- Enforce our exact policy in PAM (source of truth) ---
      PAM_FILE="/etc/pam.d/common-password"

      if grep -qE '^\s*password\s+requisite\s+pam_pwquality\.so' "$PAM_FILE"; then
        # Replace existing pwquality line
        sed -i -E "s|^\s*password\s+requisite\s+pam_pwquality\.so.*$|password requisite pam_pwquality.so ${PWQ_OPTS}|" "$PAM_FILE"
      else
        # Insert before pam_unix
        sed -i -E "/^\s*password\s+.*pam_unix\.so/ i password requisite pam_pwquality.so ${PWQ_OPTS}" "$PAM_FILE"
      fi

      # SSH: enable password login (students use passwords)
      cat >/etc/ssh/sshd_config.d/99-dozilab-multiuser.conf <<'EOF'
      PasswordAuthentication yes
      KbdInteractiveAuthentication yes
      ChallengeResponseAuthentication yes
      UsePAM yes
      PermitRootLogin no
      EOF

      export STUDENTS_JSON FORCE WORKDIR

      # Create students (hard fail if any user cannot be created or password cannot be set)
      python3 - <<'PY'
      import json, os, re, sys, subprocess

      students_json = os.environ.get("STUDENTS_JSON", "")
      force = str(os.environ.get("FORCE", "true")).lower() in ("1","true","yes","on")
      workdir = os.environ.get("WORKDIR","work")

      try:
          data = json.loads(students_json)
      except Exception as e:
          sys.exit(f"students JSON invalid: {e}. Must be like {{\"alice\":\"pw\"}} (double quotes). Got: {students_json!r}")

      if not isinstance(data, dict) or not data:
          sys.exit("students must be a non-empty JSON object")

      rx = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

      def run(cmd, **kw):
          subprocess.run(cmd, check=True, **kw)

      # Validate all upfront so we don't half-configure
      for u, p in data.items():
          if not isinstance(u, str) or not rx.match(u):
              sys.exit(f"Invalid username: {u!r}")
          if not isinstance(p, str) or len(p) == 0:
              sys.exit(f"Empty password for {u}")

      created = []

      for u, p in data.items():
          if subprocess.run(["id", u], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
              run(["useradd", "-m", "-s", "/bin/bash", u])

          # This MUST succeed, otherwise we fail the whole setup
          run(["chpasswd"], input=f"{u}:{p}\n", text=True)

          if force:
              subprocess.run(["chage", "-d", "0", u], check=False)

          run(["chmod", "700", f"/home/{u}"])
          run(["mkdir", "-p", f"/home/{u}/{workdir}"])
          run(["chown", "-R", f"{u}:{u}", f"/home/{u}/{workdir}"])
          run(["chmod", "700", f"/home/{u}/{workdir}"])

          profile = f"/home/{u}/.profile"
          line = f'cd "$HOME/{workdir}"\n'
          try:
              txt = open(profile, "r", encoding="utf-8", errors="ignore").read()
          except FileNotFoundError:
              txt = ""
          if f'cd "$HOME/{workdir}"' not in txt:
              with open(profile, "a", encoding="utf-8") as f:
                  f.write(line)
          run(["chown", f"{u}:{u}", profile])

          created.append(u)

      # Restrict SSH users: ubuntu (admin key) + created students only
      allow = "AllowUsers ubuntu " + " ".join(sorted(created)) + "\n"
      with open("/etc/ssh/sshd_config.d/98-dozilab-allowusers.conf", "w", encoding="utf-8") as f:
          f.write(allow)

      print("created users:", ", ".join(created))
      PY

      # Restart sshd; if this fails, trap will mark FAILED
      systemctl restart ssh || service ssh restart

      echo "multiuser setup finished $(date -Is)" >> "$LOG"

      # READY marker (ONLY here = success)
      msg="DOZILAB_READY stack=${STACK_LABEL} time=$(date -Is)"
      echo "$msg" | tee -a "$LOG" | tee /dev/console > "$READY_FILE"
      chmod 644 "$READY_FILE"

runcmd:
  - [ bash, -lc, "/usr/local/bin/dozilab-multiuser-setup.sh" ]

final_message: "DoziLab multi-user VM: cloud-init finished"
"""


def create_mock_user(db: Session) -> User:
    """Create or get mock development user."""
    existing_user = db.query(User).filter(User.external_id == "dev-user-mock").first()
    if existing_user:
        return existing_user
    
    user = User(
        external_id="dev-user-mock"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"Created mock user with external_id: {user.external_id}")
    return user


def create_mock_templates(db: Session, owner_id: str) -> list[Template]:
    """Create mock templates."""
    templates_data = [
        {
            "name": "Ubuntu VM",
            "description": "Simple Ubuntu 22.04 VM template for testing and development",
            "repo_url": "https://github.com/example/ubuntu-vm-template",
            "visibility": TemplateVisibility.PUBLIC,
            "approval_status": TemplateApprovalStatus.APPROVED,
        },
        {
            "name": "Docker Host",
            "description": "Ubuntu VM pre-configured with Docker and Docker Compose",
            "repo_url": "https://github.com/example/docker-host-template",
            "visibility": TemplateVisibility.PUBLIC,
            "approval_status": TemplateApprovalStatus.APPROVED,
        },
        {
            "name": "Kubernetes Node",
            "description": "K8s worker node template (private, pending approval)",
            "repo_url": "https://github.com/example/k8s-node-template",
            "visibility": TemplateVisibility.PRIVATE,
            "approval_status": TemplateApprovalStatus.PENDING,
        },
    ]
    
    templates = []
    for data in templates_data:
        # Check if template already exists
        existing = db.query(Template).filter(Template.name == data["name"]).first()
        if existing:
            templates.append(existing)
            continue
        
        template = Template(
            owner_id=owner_id,
            **data
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        templates.append(template)
        logger.info(f"Created template: {template.name}")
    
    return templates


def create_mock_template_versions(db: Session, templates: list[Template]) -> list[TemplateVersion]:
    """Create mock template versions."""
    versions = []
    
    for template in templates:
        # Check if version already exists
        existing = db.query(TemplateVersion).filter(
            TemplateVersion.template_id == template.id
        ).first()
        
        if existing:
            versions.append(existing)
            continue
        
        version = TemplateVersion(
            template_id=template.id,
            git_commit_sha=f"abc123{template.id[:6]}",
            is_active=True
        )
        db.add(version)
        db.commit()
        db.refresh(version)
        versions.append(version)
        logger.info(f"Created version for template: {template.name}")
    
    return versions


def create_mock_template_files(db: Session, versions: list[TemplateVersion]) -> None:
    """Create mock template version files."""
    for version in versions:
        # Check if files already exist
        existing_files = db.query(TemplateVersionFile).filter(
            TemplateVersionFile.template_version_id == version.id
        ).count()
        
        if existing_files > 0:
            continue
        
        # Create app.yaml
        app_yaml = TemplateVersionFile(
            template_version_id=version.id,
            file_name="app.yaml",
            file_type=FileType.CONFIG_FILE,
            file_path="app.yaml",
            content=MOCK_APP_YAML,
            is_primary=False
        )
        db.add(app_yaml)
        
        # Create heat template
        heat_template = TemplateVersionFile(
            template_version_id=version.id,
            file_name="template.yaml",
            file_type=FileType.HEAT_TEMPLATE,
            file_path="heat/template.yaml",
            content=MOCK_HEAT_TEMPLATE,
            is_primary=True
        )
        db.add(heat_template)
        
        # Create cloud-init user-data
        cloud_init = TemplateVersionFile(
            template_version_id=version.id,
            file_name="user-data.yaml",
            file_type=FileType.CLOUD_INIT,
            file_path="cloud-init/user-data.yaml",
            content=MOCK_CLOUD_INIT,
            is_primary=False
        )
        db.add(cloud_init)
        
        db.commit()
        logger.info(f"Created files for version: {version.id}")


def seed_mock_data(db: Session) -> None:
    """Seed all mock data for development.
    
    Args:
        db: Database session
    """
    try:
        logger.info("Starting mock data seeding...")
        
        # Create mock user
        user = create_mock_user(db)
        
        # Create templates
        templates = create_mock_templates(db, user.id)
        
        # Create versions
        versions = create_mock_template_versions(db, templates)
        
        # Create files
        create_mock_template_files(db, versions)
        
        logger.info("Mock data seeding completed successfully!")
        
    except Exception as e:
        logger.error(f"Failed to seed mock data: {e}")
        db.rollback()
        raise
