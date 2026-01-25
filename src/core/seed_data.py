"""Seed mock data for development and testing."""
import logging
from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import User
from src.models.openstack_project import OpenstackProject

logger = logging.getLogger(__name__)


MULTISTUDENT_APP_YAML = """app:
  name: multiuser-ubuntu
  label: Multi-User Ubuntu
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
  # --- VM basics ---
  - name: stack_label
    label: Label
    step: template
    type: string
    default: multistudent
    required: true
    description: >
      Short course/stack label used in VM name and metadata (e.g. kurs-01).
      Must match: ^[a-z0-9][a-z0-9-]{0,30}$

  - name: image
    label: Image
    step: konfiguration
    type: string
    default: "Ubuntu 22.04 2025-01"
    enum:
      - "Ubuntu 22.04 2025-01"
      - "Ubuntu 24.04 2025-01"
      - "Ubuntu 24.04 2026-01"
    required: true
    description: "Base image for the VM (restricted to known good images)."

  - name: flavor
    label: Flavor
    step: konfiguration
    type: string
    default: "gp1.small"
    enum:
      - "gp1.small"
      - "gp1.medium"
    required: true
    description: "VM size. Keep small/medium for student workloads."

  # --- Access control / networking ---
  - name: ssh_cidr
    label: SSH erlaubtes Netz (CIDR)
    step: netzwerk
    type: string
    default: "141.72.0.0/16"
    required: true
    description: >
      IPv4 CIDR allowed to SSH and ICMP (ping). Default is DHBW/VPN range.
      Examples: 141.72.0.0/16 (VPN/Campus) or 1.2.3.4/32 (single IP).


  - name: force_password_change
    label: Passwortwechsel beim ersten Login
    step: zugriff
    type: boolean
    default: true
    required: true
    description: "If true, student users must change their password on first login."

  - name: workdir
    label: Arbeitsordner
    step: zugriff
    type: string
    default: "work"
    required: true
    description: "Directory created under each student's home and used as default login directory."

  # --- Password policy (showcase / configurable in V1) ---
  - name: pw_min_length
    label: Minimale Passwortlänge
    step: zugriff
    type: number
    default: 12
    required: true
    description: "Minimum password length enforced via PAM pwquality."

  - name: pw_require_digit
    label: Ziffer erforderlich
    step: zugriff
    type: boolean
    default: true
    required: true
    description: "Require at least one digit."

  - name: pw_require_upper
    label: Großbuchstabe erforderlich
    step: zugriff
    type: boolean
    default: true
    required: true
    description: "Require at least one uppercase letter."

  - name: pw_require_special
    label: Sonderzeichen erforderlich
    step: zugriff
    type: boolean
    default: true
    required: true
    description: "Require at least one special character."

  # --- Platform-fixed parameters (not shown in UI) ---
  # Heat enforces allowed_values for these anyway. Keeping them hidden avoids confusion.
  - name: network
    label: Internes Netzwerk
    step: netzwerk
    type: string
    default: "NAT"
    hidden: true
    description: "Internal network (fixed)."

  - name: external_network
    label: Externes Netzwerk (Floating IP)
    step: netzwerk
    type: string
    default: "DHBW"
    hidden: true
    description: "External/FloatingIP network (fixed)."

  - name: key_name
    label: Admin SSH-Key
    step: zugriff
    type: string
    default: "heat-bastion-key"
    hidden: true
    description: "Admin/support SSH keypair (fixed in v1)."

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

POSTGRES_APP_YAML = """
id: postgres-group-db
name: PostgreSQL Group Database
version: 1.0.0
description: "Provisioniert pro Gruppe eine Ubuntu-VM mit PostgreSQL. Zugriff erfolgt sicher via SSH-Tunnel (Postgres nur localhost)."

parameters:
  instance_name:
    type: string
    required: true
    description: "Eindeutiger Name der Instanz/Stacks (z.B. kursX-grp1-db)."

  image:
    type: string
    required: true
    default: "Ubuntu 22.04 2025-01"
    description: "OpenStack Image Name/ID."

  flavor:
    type: string
    required: true
    default: "gp1.small"
    description: "OpenStack Flavor."

  network:
    type: string
    required: true
    default: "NAT"
    description: "Internes Tenant-Netzwerk."

  external_network:
    type: string
    required: true
    default: "DHBW"
    description: "Externes Netzwerk für Floating IPs."

  group_login:
    type: string
    required: true
    description: "Linux Username für Gruppen-Zugang (SSH)."

  group_public_key:
    type: string
    required: true
    description: "SSH Public Key der Gruppe."

  ssh_cidr:
    type: string
    required: false
    default: "0.0.0.0/0"
    description: "CIDR, von dem aus SSH erreichbar ist (sicherer: deine IP/32)."

  db_name:
    type: string
    required: true
    description: "Name der PostgreSQL Datenbank."

  db_user:
    type: string
    required: true
    description: "Name des PostgreSQL Users."

  db_password:
    type: string
    required: true
    description: "Passwort für den PostgreSQL User (kommt vom Backend)."

  postgres_version:
    type: int
    required: false
    default: 14
    description: "PostgreSQL Major-Version (Ubuntu repo)."

"""

MULTISTUDENT_HEAT_TEMPLATE = """heat_template_version: 2018-08-31

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

POSTGRES_HEAT_TEMPLATE = """
heat_template_version: 2018-08-31
description: PostgreSQL Group DB (Floating IP + SSH tunnel; Postgres localhost only)

parameters:
  instance_name:
    type: string

  image:
    type: string
    default: "Ubuntu 22.04 2025-01"

  flavor:
    type: string
    default: "gp1.small"

  network:
    type: string
    default: "NAT"

  external_network:
    type: string
    default: "DHBW"

  group_login:
    type: string
    constraints:
      - length: { min: 1, max: 32 }

  group_public_key:
    type: string

  ssh_cidr:
    type: string
    default: "0.0.0.0/0"

  db_name:
    type: string

  db_user:
    type: string

  db_password:
    type: string
    hidden: true

  postgres_version:
    type: number
    default: 14

resources:
  secgroup:
    type: OS::Neutron::SecurityGroup
    properties:
      description: Allow SSH + ICMP (Postgres via SSH tunnel only)
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
      name: { get_param: instance_name }
      image: { get_param: image }
      flavor: { get_param: flavor }

      user_data_format: RAW
      user_data:
        str_replace:
          template: { get_file: ../cloud-init/user-data.yaml }
          params:
            __GROUP_LOGIN__: { get_param: group_login }
            __GROUP_PUBKEY__: { get_param: group_public_key }
            __DB_NAME__: { get_param: db_name }
            __DB_USER__: { get_param: db_user }
            __DB_PASS__: { get_param: db_password }
            __PG_VERSION__: { get_param: postgres_version }

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
    description: Public Floating IP
    value: { get_attr: [fip, floating_ip_address] }

  ssh_user:
    description: SSH username for group access
    value: { get_param: group_login }

  ssh_port:
    description: SSH port
    value: 22

  private_ip:
    description: Private IP on tenant network
    value: { get_attr: [port, fixed_ips, 0, ip_address] }

  db_name:
    description: PostgreSQL database name
    value: { get_param: db_name }

  db_user:
    description: PostgreSQL username
    value: { get_param: db_user }

  server_id:
    description: Nova server ID
    value: { get_resource: server }

  ssh_tunnel_hint:
    description: How to access Postgres securely via SSH tunnel
    value:
      str_replace:
        template: "ssh -i <private_key> -L 5432:localhost:5432 USER@FIP  # then: psql -h 127.0.0.1 -p 5432 -U DBUSER DBNAME"
        params:
          USER: { get_param: group_login }
          FIP: { get_attr: [fip, floating_ip_address] }
          DBUSER: { get_param: db_user }
          DBNAME: { get_param: db_name }

"""

MULTISTUDENT_CLOUD_INIT = """#cloud-config
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

POSTGRES_CLOUD_INIT = """
#cloud-config
package_update: true
package_upgrade: false

ssh_pwauth: false
disable_root: true

users:
  - default
  - name: __GROUP_LOGIN__
    gecos: "Group Login"
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - "__GROUP_PUBKEY__"

write_files:
  - path: /usr/local/bin/dozilab-postgres-init.sh
    permissions: "0755"
    content: |
      #!/usr/bin/env bash
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive

      PG_VER="__PG_VERSION__"
      DB_NAME="__DB_NAME__"
      DB_USER="__DB_USER__"
      DB_PASS="__DB_PASS__"

      echo "Installing PostgreSQL ${PG_VER}..."
      apt-get update -y
      apt-get install -y "postgresql-${PG_VER}" "postgresql-client-${PG_VER}"

      # Ensure Postgres listens only on localhost (safe default)
      PG_CONF="/etc/postgresql/${PG_VER}/main/postgresql.conf"
      HBA_CONF="/etc/postgresql/${PG_VER}/main/pg_hba.conf"

      sed -i "s/^#\\?listen_addresses\\s*=.*$/listen_addresses = 'localhost'/" "${PG_CONF}"

      # Ensure local auth is allowed
      # Keep defaults, but we ensure password auth for local connections to the created user
      if ! grep -qE "host\\s+${DB_NAME}\\s+${DB_USER}\\s+127\\.0\\.0\\.1/32\\s+scram-sha-256" "${HBA_CONF}"; then
        echo "host ${DB_NAME} ${DB_USER} 127.0.0.1/32 scram-sha-256" >> "${HBA_CONF}"
      fi

      systemctl enable postgresql
      systemctl restart postgresql

      echo "Creating DB/User..."
      # Create user (idempotent-ish)
      sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
      DO \$\$
      BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}') THEN
          CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}';
        ELSE
          ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASS}';
        END IF;
      END
      \$\$
      ;
      SQL

      # Create database owned by user if not exists
      sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
      DO \$\$
      BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}') THEN
          CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};
        END IF;
      END
      \$\$
      ;
      SQL

      echo "PostgreSQL ready. Access via SSH tunnel only."

runcmd:
  - /usr/local/bin/dozilab-postgres-init.sh

"""


def create_lecturer_user(db: Session) -> User:
    """Create or get mock development user."""
    existing_user = db.query(User).filter(User.external_id == "b2767751-c2d0-4d09-9400-ad520edbfe3c").first()
    if existing_user:
        return existing_user
    
    user = User(
        external_id="b2767751-c2d0-4d09-9400-ad520edbfe3c"
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
            "name": "Multi-User Ubuntu",
            "description": "Deploy one Ubuntu VM for a course with multiple local student accounts (username/password), SSH allowed only from DHBW/VPN CIDR, and a Floating IP on DHBW. Backend can wait for DOZILAB_READY marker in the Nova console log.",
            "repo_url": "https://github.com/dozilab/appstore-templates",
            "icon_url": "mdi:server-network",
            "visibility": TemplateVisibility.PUBLIC,
            "approval_status": TemplateApprovalStatus.APPROVED,
        },
            ]
    
    templates = []
    for data in templates_data:
        # Check if template already exists
        existing = db.query(Template).filter(Template.name == data["name"]).first()
        if existing:
            logger.info(f"Template '{data['name']}' already exists, skipping creation (ID: {existing.id})")
            templates.append(existing)
            continue
        
        try:
            template = Template(
                owner_id=owner_id,
                **data
            )
            db.add(template)
            db.commit()
            db.refresh(template)
            templates.append(template)
            logger.info(f"Created template: {template.name} (ID: {template.id})")
        except Exception as e:
            logger.error(f"Failed to create template '{data['name']}': {e}")
            db.rollback()
            raise
    
    logger.info(f"Total templates: {len(templates)} (created or existing)")
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
            logger.info(f"Template version already exists for '{template.name}', skipping creation (Version ID: {existing.id})")
            versions.append(existing)
            continue
        
        try:
            version = TemplateVersion(
                template_id=template.id,
                version="1.0.0",
                git_commit_sha=f"v1.0.0-{template.name.lower().replace(' ', '-')}",
                is_active=True
            )
            db.add(version)
            db.commit()
            db.refresh(version)
            versions.append(version)
            logger.info(f"Created version for template: {template.name} (Version ID: {version.id})")
        except Exception as e:
            logger.error(f"Failed to create version for template '{template.name}': {e}")
            db.rollback()
            raise
    
    return versions


def create_mock_template_files(db: Session, versions: list[TemplateVersion]) -> None:
    """Create mock template version files."""
    files_created = 0
    files_skipped = 0
    files_failed = 0
    
    for version in versions:
        try:
            # Check if files already exist
            existing_files = db.query(TemplateVersionFile).filter(
                TemplateVersionFile.template_version_id == version.id
            ).count()
            
            if existing_files > 0:
                logger.info(f"Files already exist for version {version.id}, skipping (count: {existing_files})")
                files_skipped += 1
                continue
            
            # Get template to determine which files to create
            template = db.query(Template).filter(Template.id == version.template_id).first()
            if not template:
                logger.warning(f"Template not found for version {version.id} (template_id: {version.template_id})")
                files_failed += 1
                continue
            
            logger.info(f"Creating files for version {version.id} (template: {template.name})")
            
            # Determine which template files to use based on template name
            if template.name == "Multi-User Ubuntu":
                app_yaml_content = MULTISTUDENT_APP_YAML
                heat_template_content = MULTISTUDENT_HEAT_TEMPLATE
                cloud_init_content = MULTISTUDENT_CLOUD_INIT
                heat_file_name = "main.yaml"
                heat_file_path = "heat/main.yaml"
            elif template.name == "PostgreSQL Group Database":
                app_yaml_content = POSTGRES_APP_YAML
                heat_template_content = POSTGRES_HEAT_TEMPLATE
                cloud_init_content = POSTGRES_CLOUD_INIT
                heat_file_name = "main.yaml"
                heat_file_path = "heat/main.yaml"
            else:
                logger.warning(f"Unknown template name '{template.name}' for version {version.id}, skipping file creation")
                files_failed += 1
                continue
            
            # Create app.yaml
            app_yaml = TemplateVersionFile(
                template_version_id=version.id,
                file_name="app.yaml",
                file_type=FileType.APP_MANIFEST,
                file_path="app.yaml",
                content=app_yaml_content,
                is_primary=False
            )
            db.add(app_yaml)
            logger.debug(f"Added app.yaml for version {version.id}")
            
            # Create heat template
            heat_template = TemplateVersionFile(
                template_version_id=version.id,
                file_name=heat_file_name,
                file_type=FileType.HEAT_TEMPLATE,
                file_path=heat_file_path,
                content=heat_template_content,
                is_primary=True
            )
            db.add(heat_template)
            logger.debug(f"Added heat template for version {version.id}")
            
            # Create cloud-init user-data
            cloud_init = TemplateVersionFile(
                template_version_id=version.id,
                file_name="user-data.yaml",
                file_type=FileType.CLOUD_INIT,
                file_path="cloud-init/user-data.yaml",
                content=cloud_init_content,
                is_primary=False
            )
            db.add(cloud_init)
            logger.debug(f"Added cloud-init for version {version.id}")
            
            db.commit()
            files_created += 1
            logger.info(f"✅ Created 3 files for version: {version.id} (template: {template.name})")
            
        except Exception as e:
            logger.error(f"❌ Failed to create files for version {version.id}: {e}", exc_info=True)
            db.rollback()
            files_failed += 1
    
    logger.info(f"Template files summary: {files_created} created, {files_skipped} skipped, {files_failed} failed")


def seed_mock_data(db: Session) -> None:
    """Seed all mock data for development.
    
    Args:
        db: Database session
    """
    try:
        logger.info("Starting mock data seeding...")
        
        # Create mock user
        user = create_lecturer_user(db)
        logger.info(f"User ready: {user.id} (external_id: {user.external_id})")
        
        # Create templates
        templates = create_mock_templates(db, user.id)
        if not templates:
            logger.warning("No templates were created or found!")
            return
        logger.info(f"Templates ready: {len(templates)} templates")
        
        # Create versions
        versions = create_mock_template_versions(db, templates)
        if not versions:
            logger.warning("No template versions were created or found!")
            return
        logger.info(f"Template versions ready: {len(versions)} versions")
        
        # Create files
        create_mock_template_files(db, versions)
        logger.info(f"Template files created for {len(versions)} versions")
        
        logger.info("Mock data seeding completed successfully!")
        
    except Exception as e:
        logger.error(f"Failed to seed mock data: {e}", exc_info=True)
        db.rollback()
        raise
