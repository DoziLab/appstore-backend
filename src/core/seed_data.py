"""Seed mock data for development and testing."""
import logging
from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import User

logger = logging.getLogger(__name__)


MULTISTUDENT_APP_YAML = """
app:
  name: multiuser-ubuntu
  label: Multi-User Ubuntu
  version: 1.0.0
  description: >
    Deploy one Ubuntu VM for a course with multiple local student accounts (username/password),
    SSH allowed only from DHBW/VPN CIDR, and a Floating IP on DHBW.
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
    description: "Marker string that appears in Nova console log when provisioning is done. Auch nach was müsst ihr im log ausschau halten dass ihr wisst dass die VM Ready ist"
"""

POSTGRES_APP_YAML = """
app:
  name: postgres-group-db
  label: PostgreSQL Group DB
  version: 1.1.0
  description: >
    Provision one Ubuntu VM with PostgreSQL (localhost-only) and optional pgAdmin.
    Creates group databases, student logins, and teacher access. Backend can wait
    for the DOZILAB_READY marker in the Nova console log.
  owner_team: dozilab-app-team

artifacts:
  heat_template: heat/main.yaml
  cloud_init: cloud-init/user-data.yaml

# Parameters exposed to the AppStore UI.
parameters:
  # --- VM basics ---
  - name: stack_label
    label: Label
    step: template
    type: string
    default: "sql"
    required: true
    description: >
      Short course/stack label used in VM name and log markers (e.g. sql-2026-01).
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

  - name: volume_size
    label: Speicher (GB)
    step: konfiguration
    type: number
    default: 8
    enum:
      - 8
      - 16
      - 32
      - 64
      - 128
    required: true
    description: "Größe der Root-Disk als Cinder-Volume (Boot from Volume)."

  # --- Access control / networking ---
  - name: ssh_cidr
    label: SSH erlaubtes Netz (CIDR)
    step: netzwerk
    type: string
    default: "141.72.0.0/16"
    required: true
    description: >
      IPv4 CIDR allowed to SSH. Default is DHBW/VPN range.
      Examples: 141.72.0.0/16 or 1.2.3.4/32.

  - name: web_cidr
    label: pgAdmin erlaubtes Netz (CIDR)
    step: netzwerk
    type: string
    default: "141.72.0.0/16"
    required: true
    description: "IPv4 CIDR allowed to reach pgAdmin (HTTP port 80)."


  # --- Platform-fixed parameters (not shown in UI) ---
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
    description: "Admin/support SSH keypair (fixed)."

outputs:
  - name: ssh_user
    from_heat_output: ssh_user
    description: "SSH username (ubuntu)."

  - name: floating_ip
    from_heat_output: floating_ip
    description: "Public floating IP address."

  - name: private_ip
    from_heat_output: private_ip
    description: "Private IP on tenant network."

  - name: server_id
    from_heat_output: server_id
    description: "Nova server ID (useful for console-log polling)."

  - name: pgadmin_url
    from_heat_output: pgadmin_url
    description: "pgAdmin4 URL (if enabled)."

  - name: ssh_hint
    from_heat_output: ssh_hint
    description: "Admin SSH command template."

  - name: ssh_tunnel_hint
    from_heat_output: ssh_tunnel_hint
    description: "How to access Postgres securely via SSH tunnel."

  - name: ready_marker
    from_heat_output: ready_marker
    description: "Marker string that appears in Nova console log when provisioning is done."

  - name: root_volume_id
    from_heat_output: root_volume_id
    description: "Cinder root volume ID (debug/traceability)."

"""

MULTISTUDENT_HEAT_TEMPLATE = """
heat_template_version: 2018-08-31

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

  user_json:
    type: string
    default: |
      {"course_label":"","instance":{"credentials":[]},"applications":[]}
    description: "Base64-encoded JSON payload (raw JSON also accepted; multi-line allowed)."
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
            __USER_JSON__: { get_param: user_json }
    
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

description: DoziLab PostgreSQL VM (localhost-only) + optional pgAdmin4 Web UI (boot from Cinder volume)

parameters:
  stack_label:
    type: string
    description: Short label used in hostname/log markers
    default: "sql"

  image:
    type: string
    description: Glance image name or ID

  flavor:
    type: string
    description: Nova flavor name or ID

  volume_size:
    type: number
    description: Root volume size in GB
    default: 8
    constraints:
      - range: { min: 8, max: 200 }

  network:
    type: string
    description: Tenant network name or ID

  external_network:
    type: string
    description: External network name or ID for Floating IP

  key_name:
    type: string
    description: Nova keypair name for SSH
    default: "heat-bastion-key"

  ssh_cidr:
    type: string
    description: Allowed CIDR for SSH
    default: "0.0.0.0/0"

  web_cidr:
    type: string
    description: Allowed CIDR for pgAdmin over HTTP (port 80)
    default: "0.0.0.0/0"

  user_json:
    type: string
    description: Base64-encoded JSON payload from backend (raw JSON also accepted; multi-line allowed)

resources:
  secgroup:
    type: OS::Neutron::SecurityGroup
    properties:
      name: { str_replace: { template: "dozilab-pg-__LABEL__", params: { "__LABEL__": { get_param: stack_label } } } }
      description: Security group for DoziLab Postgres+pgAdmin VM
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
          remote_ip_prefix: { get_param: web_cidr }

        # egress allow all (default in many setups; define explicitly to be safe)
        - direction: egress
          ethertype: IPv4

  port:
    type: OS::Neutron::Port
    properties:
      network: { get_param: network }
      security_groups: [ { get_resource: secgroup } ]

  root_volume:
    type: OS::Cinder::Volume
    properties:
      name:
        str_replace:
          template: "dozilab-pg-__LABEL__-root"
          params:
            "__LABEL__": { get_param: stack_label }
      size: { get_param: volume_size }
      image: { get_param: image }
      metadata:
        dozilab_stack_label: { get_param: stack_label }

  server:
    type: OS::Nova::Server
    properties:
      name: { str_replace: { template: "dozilab-pg-__LABEL__", params: { "__LABEL__": { get_param: stack_label } } } }
      flavor: { get_param: flavor }
      key_name: { get_param: key_name }
      block_device_mapping_v2:
        - boot_index: 0
          volume_id: { get_resource: root_volume }
          delete_on_termination: true
      networks:
        - port: { get_resource: port }
      user_data_format: RAW
      user_data:
        str_replace:
          template: { get_file: ../cloud-init/user-data.yaml }
          params:
            "__STACK_LABEL__": { get_param: stack_label }
            "__USER_JSON__": { get_param: user_json }
                

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
  ssh_user:
    description: SSH username
    value: ubuntu

  floating_ip:
    description: Public Floating IP
    value: { get_attr: [ fip, floating_ip_address ] }

  private_ip:
    description: Private IP on tenant network
    value: { get_attr: [ port, fixed_ips, 0, ip_address ] }

  server_id:
    description: Nova server ID
    value: { get_resource: server }

  pgadmin_url:
    description: pgAdmin4 URL (if enabled)
    value:
      str_replace:
        template: "http://__FIP__/pgadmin4/"
        params:
          "__FIP__": { get_attr: [ fip, floating_ip_address ] }

  ssh_hint:
    description: Admin SSH (key-based)
    value:
      str_replace:
        template: "ssh -i ~/.ssh/heat-bastion-key.pem ubuntu@__FIP__"
        params:
          "__FIP__": { get_attr: [ fip, floating_ip_address ] }

  ssh_tunnel_hint:
    description: How to access Postgres securely via SSH tunnel
    value:
      str_replace:
        template: "ssh -i ~/.ssh/heat-bastion-key.pem -L 5432:127.0.0.1:5432 ubuntu@__FIP__"
        params:
          "__FIP__": { get_attr: [ fip, floating_ip_address ] }

  ready_marker:
    description: Backend should wait until this marker appears in the Nova console log
    value:
      str_replace:
        template: "DOZILAB_READY stack=__LABEL__"
        params:
          "__LABEL__": { get_param: stack_label }

  root_volume_id:
    description: Cinder root volume ID (debug/traceability)
    value: { get_resource: root_volume }

"""

MULTISTUDENT_CLOUD_INIT = """
#cloud-config
package_update: true
package_upgrade: false

packages:
  - libpam-pwquality
  - python3
  - cloud-guest-utils

# Ensure root partition/filesystem grows when booting from larger volume
growpart:
  mode: auto
  devices: ["/"]
  ignore_growroot_disabled: false

resize_rootfs: true

write_files:
  - path: /etc/dozilab/user.json.payload
    owner: root:root
    permissions: "0600"
    content: |
      __USER_JSON__
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

      USER_JSON_PAYLOAD="/etc/dozilab/user.json.payload"
      USER_JSON_PATH="/etc/dozilab/user.json"
      FORCE="__FORCE_CHANGE__"
      WORKDIR="__WORKDIR__"

      PW_MIN_LENGTH="__PW_MIN_LENGTH__"
      PW_REQUIRE_DIGIT="__PW_REQUIRE_DIGIT__"
      PW_REQUIRE_UPPER="__PW_REQUIRE_UPPER__"
      PW_REQUIRE_SPECIAL="__PW_REQUIRE_SPECIAL__"

      mkdir -p "$MARK_DIR"
      # Mirror logs to cloud-init output and our own logfile
      exec > >(tee -a "$LOG" /var/log/cloud-init-output.log) 2>&1
      echo "multiuser setup started $(date -Is)"

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

      # SSH: enable password login (users use passwords)
      cat >/etc/ssh/sshd_config.d/99-dozilab-multiuser.conf <<'EOF'
      PasswordAuthentication yes
      KbdInteractiveAuthentication yes
      ChallengeResponseAuthentication yes
      UsePAM yes
      PermitRootLogin no
      EOF

      export USER_JSON_PATH FORCE WORKDIR

      if [[ ! -s "$USER_JSON_PAYLOAD" ]]; then
        echo "ERROR: $USER_JSON_PAYLOAD missing/empty" >&2
        exit 2
      fi

      # Decode base64 (or accept raw JSON) into /etc/dozilab/user.json
      python3 - <<'PY'
      import ast
      import base64
      import json
      import sys
      from pathlib import Path

      payload_path = Path("/etc/dozilab/user.json.payload")
      out_path = Path("/etc/dozilab/user.json")

      raw = payload_path.read_text(encoding="utf-8").strip()
      if not raw:
          sys.exit("user_json payload missing/empty")

      def parse_obj(txt: str):
          try:
              return json.loads(txt), "json"
          except Exception:
              pass
          try:
              return ast.literal_eval(txt), "python-literal"
          except Exception:
              return None, None

      def decode_b64(s: str):
          compact = "".join(s.split())
          pad = (-len(compact)) % 4
          compact += "=" * pad
          try:
              return base64.b64decode(compact, validate=True).decode("utf-8")
          except Exception:
              try:
                  return base64.b64decode(compact).decode("utf-8")
              except Exception:
                  return None

      obj, kind = parse_obj(raw)
      source = "raw"
      if obj is None:
          decoded = decode_b64(raw)
          if decoded is None:
              sys.exit("user_json payload is neither JSON/literal nor base64-encoded JSON/literal")
          obj, kind = parse_obj(decoded.strip())
          if obj is None:
              sys.exit("user_json base64 decoded, but not valid JSON or python literal")
          source = "base64"

      out_path.write_text(json.dumps(obj, ensure_ascii=True), encoding="utf-8")
      print(f"user_json normalized ({source}, {kind}) -> {out_path}")
      PY

      if [[ ! -s "$USER_JSON_PATH" ]]; then
        echo "ERROR: $USER_JSON_PATH missing/empty after decoding" >&2
        exit 2
      fi

      # Create users from user_json (hard fail on invalid schema)
      python3 - <<'PY'
      import json, os, re, sys, subprocess

      user_json_path = os.environ.get("USER_JSON_PATH", "/etc/dozilab/user.json")
      try:
          user_json = open(user_json_path, "r", encoding="utf-8").read().strip()
      except FileNotFoundError:
          user_json = ""
      force = str(os.environ.get("FORCE", "true")).lower() in ("1","true","yes","on")
      workdir = os.environ.get("WORKDIR","work")

      def fail(msg):
          print(msg, file=sys.stderr)
          sys.exit(1)

      if not re.match(r"^[A-Za-z0-9._-]{1,32}$", workdir or ""):
          print(f"Invalid workdir {workdir!r}, using 'work'")
          workdir = "work"

      if not user_json:
          fail("user_json is empty or missing")

      try:
          data = json.loads(user_json)
      except Exception as e:
          fail(f"user_json invalid: {e}. Must be JSON with double quotes.")

      if not isinstance(data, dict):
          fail("user_json must be a JSON object")

      instance = data.get("instance") or {}
      if not isinstance(instance, dict):
          fail("instance must be an object")

      credentials = instance.get("credentials") or []
      admin = instance.get("admin_credentials")
      apps = data.get("applications") or []

      if not isinstance(credentials, list):
          fail("instance.credentials must be a list")

      if not isinstance(apps, list):
          print("applications is not a list; ignoring")
          apps = []

      course_label = data.get("course_label") or ""
      if course_label:
          print(f"course_label={course_label}")

      if not credentials:
          print("WARNING: instance.credentials empty; no student users will be created")

      rx = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

      def run(cmd, **kw):
          subprocess.run(cmd, check=True, **kw)

      NL = chr(10)

      def ensure_user(u, p, is_admin=False):
          if subprocess.run(["id", u], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
              run(["useradd", "-m", "-s", "/bin/bash", u])

          # This MUST succeed, otherwise we fail the whole setup
          run(["chpasswd"], input=f"{u}:{p}" + NL, text=True)

          if is_admin:
              subprocess.run(["usermod", "-aG", "sudo", u], check=False)

          if force:
              subprocess.run(["chage", "-d", "0", u], check=False)

          run(["chmod", "700", f"/home/{u}"])
          run(["mkdir", "-p", f"/home/{u}/{workdir}"])
          run(["chown", "-R", f"{u}:{u}", f"/home/{u}/{workdir}"])
          run(["chmod", "700", f"/home/{u}/{workdir}"])

          profile = f"/home/{u}/.profile"
          line = f'cd "$HOME/{workdir}"' + NL
          try:
              txt = open(profile, "r", encoding="utf-8", errors="ignore").read()
          except FileNotFoundError:
              txt = ""
          if f'cd "$HOME/{workdir}"' not in txt:
              with open(profile, "a", encoding="utf-8") as f:
                  f.write(line)
          run(["chown", f"{u}:{u}", profile])

      created = []

      # Validate credentials upfront so we don't half-configure
      for idx, item in enumerate(credentials):
          if not isinstance(item, dict):
              fail(f"instance.credentials[{idx}] must be an object")
          u = item.get("username")
          p = item.get("password")
          if not isinstance(u, str) or not rx.match(u):
              fail(f"Invalid username: {u!r}")
          if not isinstance(p, str) or len(p) == 0:
              fail(f"Empty password for {u}")

      for item in credentials:
          u = item["username"]
          p = item["password"]
          ensure_user(u, p, is_admin=False)
          created.append(u)

      admin_user = None
      if admin is not None:
          if not isinstance(admin, dict):
              fail("instance.admin_credentials must be an object")
          au = admin.get("username")
          ap = admin.get("password")
          if not isinstance(au, str) or not rx.match(au):
              fail(f"Invalid admin username: {au!r}")
          if not isinstance(ap, str) or len(ap) == 0:
              fail("Empty password for admin user")
          ensure_user(au, ap, is_admin=True)
          admin_user = au

      # Restrict SSH users: ubuntu (admin key) + created users only
      allow_users = sorted(set(created + ([admin_user] if admin_user else [])))
      allow = "AllowUsers " + " ".join(["ubuntu"] + allow_users) + NL
      with open("/etc/ssh/sshd_config.d/98-dozilab-allowusers.conf", "w", encoding="utf-8") as f:
          f.write(allow)

      if allow_users:
          print("created users:", ", ".join(allow_users))

      if not apps:
          print("applications: none")
      else:
          for idx, app in enumerate(apps):
              if isinstance(app, dict):
                  name = app.get("name") or app.get("app") or f"index-{idx}"
                  version = app.get("version") or app.get("ver") or ""
                  if version:
                      print(f"applications[{idx}]: {name} {version}")
                  else:
                      print(f"applications[{idx}]: {name}")
              else:
                  print(f"applications[{idx}]: {app!r}")
      PY

      # Restart sshd; if this fails, trap will mark FAILED
      systemctl restart ssh || service ssh restart

      echo "multiuser setup finished $(date -Is)"

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

write_files:
  - path: /etc/dozilab/user.json.payload
    owner: root:root
    permissions: "0600"
    content: |
      __USER_JSON__

  - path: /usr/local/bin/dozilab-postgres-setup.sh
    owner: root:root
    permissions: "0755"
    content: |
      #!/usr/bin/env bash
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive

      LOG="/var/log/dozilab-postgres.log"
      MARK_DIR="/var/lib/dozilab"
      READY_FILE="${MARK_DIR}/ready"
      FAIL_FILE="${MARK_DIR}/failed"

      STACK_LABEL="__STACK_LABEL__"
      USER_JSON_PAYLOAD="/etc/dozilab/user.json.payload"
      USER_JSON_PATH="/etc/dozilab/user.json"

      mkdir -p "$MARK_DIR"
      exec > >(tee -a "$LOG") 2>&1

      on_fail() {
        rc=$?
        msg="DOZILAB_FAILED stack=${STACK_LABEL} rc=${rc} time=$(date -Is)"
        echo "$msg" | tee -a "$LOG" | tee /dev/console > "$FAIL_FILE"
        chmod 644 "$FAIL_FILE" || true
        exit "$rc"
      }
      trap on_fail ERR

      echo "DoziLab setup started $(date -Is)"
      echo "Stack label: ${STACK_LABEL}"
      echo "Using user_json payload: ${USER_JSON_PAYLOAD}"

      if [[ ! -s "$USER_JSON_PAYLOAD" ]]; then
        echo "ERROR: $USER_JSON_PAYLOAD missing/empty" >&2
        exit 2
      fi

      # ------------------------------------------------------------
      # Decode wrapper (base64 or raw) into JSON file, then validate payload.
      # Backend must send final db_user + database_name etc. (no sanitizing)
      # ------------------------------------------------------------
      python3 - <<'PY'
      import ast
      import base64
      import json
      import sys
      from pathlib import Path

      payload_path = Path("/etc/dozilab/user.json.payload")
      out_path = Path("/etc/dozilab/user.json")

      raw = payload_path.read_text(encoding="utf-8").strip()
      if not raw:
          sys.exit("user_json payload missing/empty")

      def parse_obj(txt: str):
          try:
              return json.loads(txt), "json"
          except Exception:
              pass
          try:
              return ast.literal_eval(txt), "python-literal"
          except Exception:
              return None, None

      def decode_b64(s: str):
          compact = "".join(s.split())
          pad = (-len(compact)) % 4
          compact += "=" * pad
          try:
              return base64.b64decode(compact, validate=True).decode("utf-8")
          except Exception:
              try:
                  return base64.b64decode(compact).decode("utf-8")
              except Exception:
                  return None

      obj, kind = parse_obj(raw)
      source = "raw"
      if obj is None:
          decoded = decode_b64(raw)
          if decoded is None:
              sys.exit("user_json payload is neither JSON/literal nor base64-encoded JSON/literal")
          obj, kind = parse_obj(decoded.strip())
          if obj is None:
              sys.exit("user_json base64 decoded, but not valid JSON or python literal")
          source = "base64"

      out_path.write_text(json.dumps(obj, ensure_ascii=True), encoding="utf-8")
      print(f"user_json normalized ({source}, {kind}) -> {out_path}")
      PY

      if [[ ! -s "$USER_JSON_PATH" ]]; then
        echo "ERROR: $USER_JSON_PATH missing/empty after decoding" >&2
        exit 2
      fi

      echo "Validating user_json schema (direct) ..."
      python3 - <<'PY'
      import json, re, sys

      p = "/etc/dozilab/user.json"
      data = json.load(open(p, "r", encoding="utf-8"))
      if not isinstance(data, dict):
          sys.exit("user_json must be an object")

      apps = data.get("applications")
      if not isinstance(apps, list):
          sys.exit("user_json.applications must be a list")

      def find_app(name: str):
          for a in apps:
              if isinstance(a, dict) and str(a.get("name","")).lower() == name:
                  return a
          return None

      pg = find_app("postgres") or find_app("postgresql")
      if not pg:
          sys.exit("Missing applications[name=postgres]")

      pg_creds = pg.get("credentials")
      if not isinstance(pg_creds, list) or not pg_creds:
          sys.exit("postgres.credentials must be a non-empty list")

      # strict identifiers to avoid surprises
      ident = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
      group_token = re.compile(r"^[A-Za-z0-9_]{1,32}$")

      used_db_users = set()

      for c in pg_creds:
          if not isinstance(c, dict):
              sys.exit("postgres.credentials entries must be objects")

          gid = c.get("group")
          if gid is None:
              sys.exit("postgres credential missing group")
          gid_s = str(gid).strip()
          if not gid_s or not group_token.match(gid_s):
              sys.exit(f"postgres credential group must be [A-Za-z0-9_], 1..32 chars, got: {gid!r}")

          dbn = c.get("database_name") or c.get("db_name")
          if not isinstance(dbn, str) or not ident.match(dbn):
              sys.exit(f"postgres credential database_name invalid (must match {ident.pattern}): {dbn!r}")

          db_user = c.get("db_user")
          if not isinstance(db_user, str) or not ident.match(db_user):
              sys.exit(f"postgres credential db_user invalid (must match {ident.pattern}): {db_user!r}")

          if db_user in used_db_users:
              sys.exit(f"duplicate postgres db_user not allowed: {db_user!r}")
          used_db_users.add(db_user)

          pw = c.get("password")
          if not isinstance(pw, str) or len(pw) < 6:
              sys.exit(f"postgres credential password too short for {db_user!r} (min 6)")

      admin = pg.get("admin_credentials") or {}
      if admin:
          if not isinstance(admin, dict):
              sys.exit("postgres.admin_credentials must be an object")
          a_user = admin.get("db_user")
          a_pw = admin.get("password")
          if not isinstance(a_user, str) or not ident.match(a_user):
              sys.exit(f"postgres admin db_user invalid (must match {ident.pattern}): {a_user!r}")
          if a_user in used_db_users:
              sys.exit(f"postgres admin db_user collides with group user: {a_user!r}")
          if not isinstance(a_pw, str) or len(a_pw) < 6:
              sys.exit("postgres admin password too short (min 6)")

      # pgadmin is optional; if present we validate only what it explicitly sends (no fallback)
      pga = find_app("pgadmin")
      if pga:
          pga_admin = pga.get("admin_credentials") or {}
          if not isinstance(pga_admin, dict) or not pga_admin.get("email") or not pga_admin.get("password"):
              sys.exit("pgadmin.admin_credentials must contain email+password when pgadmin app is present")

          pga_creds = pga.get("credentials")
          if not isinstance(pga_creds, list) or not pga_creds:
              sys.exit("pgadmin.credentials must be a non-empty list when pgadmin app is present")

          seen_emails = set()
          for c in pga_creds:
              if not isinstance(c, dict):
                  sys.exit("pgadmin.credentials entries must be objects")
              gid = c.get("group")
              if gid is None:
                  sys.exit("pgadmin credential missing group")
              gid_s = str(gid).strip()
              if not gid_s or not group_token.match(gid_s):
                  sys.exit(f"pgadmin credential group must be [A-Za-z0-9_], got: {gid!r}")

              email = c.get("email")
              pw = c.get("password")
              if not isinstance(email, str) or "@" not in email:
                  sys.exit(f"pgadmin credential email invalid: {email!r}")
              if not isinstance(pw, str) or len(pw) < 6:
                  sys.exit(f"pgadmin credential password too short for {email!r} (min 6)")
              if email in seen_emails:
                  sys.exit(f"duplicate pgadmin email not allowed: {email!r}")
              seen_emails.add(email)

      print("user_json validated OK (direct mode)")
      PY

      # ------------------------------------------------------------
      # Install PostgreSQL
      # - If user_json contains postgres_version -> install that major
      # - else install distro default (postgresql meta)
      # ------------------------------------------------------------
      PGVER="$(python3 - <<'PY'
      import json
      data = json.load(open("/etc/dozilab/user.json"))
      pgver = data.get("postgres_version")
      if pgver is None:
          pgver = data.get("postgresVersion")
      apps = data.get("applications") or []
      for a in apps:
          if isinstance(a, dict) and str(a.get("name","")).lower() in ("postgres","postgresql"):
              if a.get("postgres_version") is not None:
                  pgver = a.get("postgres_version")
              if a.get("postgresVersion") is not None:
                  pgver = a.get("postgresVersion")
      if pgver is None:
          print("")
      else:
          print(int(pgver))
      PY
      )"

      apt-get update -y
      if [[ -n "${PGVER}" ]]; then
        echo "Installing PostgreSQL ${PGVER} ..."
        apt-get install -y "postgresql-${PGVER}" postgresql-client
      else
        echo "Installing distro default PostgreSQL ..."
        apt-get install -y postgresql postgresql-client
      fi

      # Detect installed major version
      DETECTED_PGVER="$(pg_lsclusters --no-header 2>/dev/null | awk 'NR==1{print $1}')"
      if [[ -z "${DETECTED_PGVER:-}" ]]; then
        echo "ERROR: Could not detect Postgres version (pg_lsclusters empty)" >&2
        exit 3
      fi
      PGVER="${DETECTED_PGVER}"
      echo "Detected PostgreSQL major version: ${PGVER}"

      echo "Configuring Postgres to listen on localhost only ..."
      CONF="/etc/postgresql/${PGVER}/main/postgresql.conf"
      HBA="/etc/postgresql/${PGVER}/main/pg_hba.conf"

      sed -i "s/^#\\?listen_addresses\\s*=.*/listen_addresses = '127.0.0.1'/" "$CONF"

      grep -qE "^[[:space:]]*host[[:space:]]+all[[:space:]]+all[[:space:]]+127\\.0\\.0\\.1/32" "$HBA" \
        || echo "host all all 127.0.0.1/32 scram-sha-256" >> "$HBA"
      grep -qE "^[[:space:]]*host[[:space:]]+all[[:space:]]+all[[:space:]]+::1/128" "$HBA" \
        || echo "host all all ::1/128 scram-sha-256" >> "$HBA"

      systemctl enable --now postgresql
      systemctl restart postgresql

      for i in {1..60}; do
        if sudo -u postgres psql -d postgres -Atc "SELECT 1" >/dev/null 2>&1; then
          break
        fi
        sleep 1
      done

      # ------------------------------------------------------------
      # Provision DB roles & databases from user_json DIRECTLY
      # (robust quoting; no psql :var substitution)
      # ------------------------------------------------------------
      echo "Provisioning roles & databases (direct from user_json) ..."
      python3 - <<'PY'
      import json, subprocess, sys, re

      spec = json.load(open("/etc/dozilab/user.json"))
      apps = spec.get("applications") or []

      def find_app(name: str):
          for a in apps:
              if isinstance(a, dict) and str(a.get("name","")).lower() == name:
                  return a
          return None

      pg = find_app("postgres") or find_app("postgresql")
      pg_creds = pg.get("credentials") or []
      pg_admin = pg.get("admin_credentials") or {}

      ident = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
      group_token = re.compile(r"^[A-Za-z0-9_]{1,32}$")

      def run(sql: str, db: str = "postgres", capture: bool = True) -> str:
          cmd = ["sudo", "-u", "postgres", "psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-Atc", sql]
          if capture:
              return subprocess.check_output(cmd, text=True, cwd="/").strip()
          subprocess.check_call(cmd, cwd="/")
          return ""

      def q_ident(s: str) -> str:
          return '"' + s.replace('"', '""') + '"'

      def q_lit(s: str) -> str:
          return "'" + s.replace("'", "''") + "'"

      def role_exists(name: str) -> bool:
          return run(f"SELECT 1 FROM pg_roles WHERE rolname={q_lit(name)};") == "1"

      def db_exists(name: str) -> bool:
          return run(f"SELECT 1 FROM pg_database WHERE datname={q_lit(name)};") == "1"

      def ensure_group_role(role: str) -> None:
          if not role_exists(role):
              run(f"CREATE ROLE {q_ident(role)} NOLOGIN;", capture=False)

      def ensure_login_role(role: str, password: str) -> None:
          if not role_exists(role):
              run(f"CREATE ROLE {q_ident(role)} LOGIN PASSWORD {q_lit(password)};", capture=False)
          else:
              run(f"ALTER ROLE {q_ident(role)} LOGIN PASSWORD {q_lit(password)};", capture=False)

      def ensure_db(dbname: str, owner: str) -> None:
          if not db_exists(dbname):
              run(f"CREATE DATABASE {q_ident(dbname)} OWNER {q_ident(owner)};", capture=False)
          run(f"ALTER DATABASE {q_ident(dbname)} OWNER TO {q_ident(owner)};", capture=False)

      def lock_down_db(dbname: str, grp_role: str) -> None:
          run(f"REVOKE ALL ON DATABASE {q_ident(dbname)} FROM PUBLIC;", capture=False)
          run(f"GRANT CONNECT, TEMPORARY ON DATABASE {q_ident(dbname)} TO {q_ident(grp_role)};", capture=False)
          run("REVOKE CREATE ON SCHEMA public FROM PUBLIC;", db=dbname, capture=False)
          run("REVOKE USAGE ON SCHEMA public FROM PUBLIC;", db=dbname, capture=False)
          run(f"GRANT USAGE, CREATE ON SCHEMA public TO {q_ident(grp_role)};", db=dbname, capture=False)

      def grant_group_defaults(dbname: str, creator_role: str, grp_role: str) -> None:
          run(
              f"ALTER DEFAULT PRIVILEGES FOR ROLE {q_ident(creator_role)} IN SCHEMA public "
              f"GRANT ALL PRIVILEGES ON TABLES TO {q_ident(grp_role)};",
              db=dbname,
              capture=False,
          )
          run(
              f"ALTER DEFAULT PRIVILEGES FOR ROLE {q_ident(creator_role)} IN SCHEMA public "
              f"GRANT ALL PRIVILEGES ON SEQUENCES TO {q_ident(grp_role)};",
              db=dbname,
              capture=False,
          )

      def grant_role(grp_role: str, user: str) -> None:
          run(f"GRANT {q_ident(grp_role)} TO {q_ident(user)};", capture=False)

      # Build group map (DIRECT): group -> {dbname, db_user, password}
      groups = {}
      for c in pg_creds:
          gid = str(c.get("group")).strip()
          if not gid or not group_token.match(gid):
              sys.exit(f"Invalid group token: {gid!r}")

          dbname = c.get("database_name") or c.get("db_name")
          db_user = c.get("db_user")
          pw = c.get("password")

          if not isinstance(dbname, str) or not ident.match(dbname):
              sys.exit(f"Invalid database_name for group {gid}: {dbname!r}")
          if not isinstance(db_user, str) or not ident.match(db_user):
              sys.exit(f"Invalid db_user for group {gid}: {db_user!r}")
          if not isinstance(pw, str) or len(pw) < 6:
              sys.exit(f"Invalid password for db_user {db_user!r} (min 6)")

          if gid in groups:
              sys.exit(f"Duplicate group in postgres.credentials: {gid!r}")
          groups[gid] = {"dbname": dbname, "db_user": db_user, "password": pw}

      # 1) group roles + dbs
      for gid, info in groups.items():
          grp_role = f"grp_{gid}"
          ensure_group_role(grp_role)
          ensure_db(info["dbname"], grp_role)
          lock_down_db(info["dbname"], grp_role)

      # 2) group login users
      for gid, info in groups.items():
          grp_role = f"grp_{gid}"
          db_user = info["db_user"]
          ensure_login_role(db_user, info["password"])
          grant_role(grp_role, db_user)
          grant_group_defaults(info["dbname"], db_user, grp_role)

      # 3) optional admin (teacher)
      if isinstance(pg_admin, dict) and pg_admin:
          a_user = pg_admin.get("db_user")
          a_pw = pg_admin.get("password")
          if a_user and a_pw:
              if not isinstance(a_user, str) or not ident.match(a_user):
                  sys.exit(f"Invalid postgres admin db_user: {a_user!r}")
              if not isinstance(a_pw, str) or len(a_pw) < 6:
                  sys.exit("Invalid postgres admin password (min 6)")
              ensure_login_role(a_user, a_pw)
              for gid, info in groups.items():
                  grp_role = f"grp_{gid}"
                  grant_role(grp_role, a_user)
                  grant_group_defaults(info["dbname"], a_user, grp_role)

      print(f"Provisioned groups: {len(groups)}")
      PY

      # ------------------------------------------------------------
      # pgAdmin (optional; only if applications includes pgadmin)
      # NO fallback, NO deriving from postgres.
      # ------------------------------------------------------------
      PGADMIN_PRESENT="$(python3 - <<'PY'
      import json
      spec = json.load(open("/etc/dozilab/user.json"))
      apps = spec.get("applications") or []
      def find(name):
          for a in apps:
              if isinstance(a, dict) and str(a.get("name","")).lower() == name:
                  return True
          return False
      print("true" if find("pgadmin") else "false")
      PY
      )"

      if [[ "$PGADMIN_PRESENT" == "true" ]]; then
        echo "Installing pgAdmin4 ..."
        apt-get install -y curl ca-certificates gnupg apache2 libapache2-mod-wsgi-py3
        install -d -m 0755 /etc/apt/keyrings
        curl -fsS https://www.pgadmin.org/static/packages_pgadmin_org.pub | gpg --dearmor -o /etc/apt/keyrings/pgadmin.gpg
        echo "deb [signed-by=/etc/apt/keyrings/pgadmin.gpg] https://ftp.postgresql.org/pub/pgadmin/pgadmin4/apt/jammy pgadmin4 main" > /etc/apt/sources.list.d/pgadmin4.list
        apt-get update -y
        apt-get install -y pgadmin4-web

        echo "Configuring pgAdmin admin account (direct) ..."
        python3 - <<'PY'
      import json, shlex, sys

      spec = json.load(open("/etc/dozilab/user.json"))
      apps = spec.get("applications") or []

      def get_app(name):
          for a in apps:
              if isinstance(a, dict) and str(a.get("name","")).lower() == name:
                  return a
          return None

      pga = get_app("pgadmin") or {}
      admin = pga.get("admin_credentials") or {}
      email = admin.get("email")
      pw = admin.get("password")

      if not email or not pw:
          sys.exit("pgadmin.admin_credentials missing email/password")
      if "@" not in email:
          sys.exit(f"pgAdmin admin email invalid: {email!r}")
      if len(pw) < 6:
          sys.exit("pgAdmin admin password too short (min 6)")

      with open("/etc/default/pgadmin4", "w") as f:
          print(f"PGADMIN_SETUP_EMAIL={shlex.quote(email)}", file=f)
          print(f"PGADMIN_SETUP_PASSWORD={shlex.quote(pw)}", file=f)
      print("pgAdmin admin email:", email)
      PY

        chmod 600 /etc/default/pgadmin4
        rm -f /var/lib/pgadmin/pgadmin4.db
        rm -rf /var/lib/pgadmin/sessions /var/lib/pgadmin/storage
        install -d -m 0750 -o www-data -g www-data /var/lib/pgadmin

        set -a
        source /etc/default/pgadmin4
        set +a
        PGADMIN_SETUP_EMAIL="$PGADMIN_SETUP_EMAIL" \
        PGADMIN_SETUP_PASSWORD="$PGADMIN_SETUP_PASSWORD" \
          /usr/pgadmin4/bin/setup-web.sh --yes

        a2enconf pgadmin4 || true
        systemctl reload apache2 || true

        echo "Creating pgAdmin users (direct from pgadmin.credentials) ..."
        python3 - <<'PY'
      import json, subprocess, sys

      spec = json.load(open("/etc/dozilab/user.json"))
      apps = spec.get("applications") or []

      def get_app(name):
          for a in apps:
              if isinstance(a, dict) and str(a.get("name","")).lower() == name:
                  return a
          return None

      pga = get_app("pgadmin") or {}
      creds = pga.get("credentials") or []
      if not isinstance(creds, list):
          sys.exit("pgadmin.credentials must be a list")

      accounts = []
      seen = set()
      for c in creds:
          if not isinstance(c, dict):
              continue
          email = c.get("email")
          pw = c.get("password")
          if not email or not pw:
              continue
          if email in seen:
              continue
          seen.add(email)
          accounts.append((email, pw))

      created = 0
      for email, pw in accounts:
          cmd = [
              "sudo",
              "-u",
              "www-data",
              "/usr/pgadmin4/venv/bin/python",
              "/usr/pgadmin4/web/setup.py",
              "add-user",
              email,
              pw,
              "--role",
              "User",
              "--active",
          ]
          res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
          out = (res.stdout or "").strip()
          if res.returncode == 0:
              created += 1
              print(f"created pgAdmin user: {email}")
          elif "already exists" in out.lower():
              print(f"pgAdmin user already exists: {email}")
          else:
              print(f"WARNING: failed to create pgAdmin user {email} rc={res.returncode} {out}")

      print(f"pgAdmin accounts processed: {len(accounts)}, created: {created}")
      PY
      fi

      msg="DOZILAB_READY stack=${STACK_LABEL} time=$(date -Is)"
      echo "$msg" | tee /dev/console > "$READY_FILE"
      chmod 644 "$READY_FILE"

      echo "DoziLab setup finished successfully"

runcmd:
  - [ bash, -lc, "/usr/local/bin/dozilab-postgres-setup.sh" ]

final_message: "DoziLab Postgres + pgAdmin VM: cloud-init finished"


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


ANSIBLE_MULTIUSER_APP_YAML = """
app:
  name: ansible-multiuser
  label: Ansible Multi-User Ubuntu
  version: 2.0.0
  description: >
    Ubuntu VM mit mehreren Benutzerkonten, verwaltet durch Ansible.
    Pro Gruppe wird ein Linux-Account mit eigenem Arbeitsverzeichnis erstellt.
  owner_team: dozilab-app-team

  allow_user_files: true

parameters:

  - name: stack_label
    label: Stack-Label
    step: template
    type: string
    default: ansible
    required: true
    description: "Kurzes Label für diesen Stack (z.B. kurs-ws2026)."

  - name: image
    label: Betriebssystem-Image
    step: konfiguration
    type: string
    default: "Ubuntu 22.04 2025-01"
    required: true
    enum:
      - "Ubuntu 22.04 2025-01"
      - "Ubuntu 24.04 2025-01"
      - "Ubuntu 24.04 2026-01"

  - name: flavor
    label: VM-Größe (Flavor)
    step: konfiguration
    type: string
    default: "gp1.small"
    required: true
    enum:
      - "gp1.small"
      - "gp1.medium"

  - name: ssh_cidr
    label: SSH-Zugriff (CIDR)
    step: netzwerk
    type: string
    default: "141.72.0.0/16"
    required: true
    description: "Nur dieses Netz darf per SSH zugreifen. Standard: DHBW/VPN."

  - name: force_password_change
    label: Passwort-Änderung beim ersten Login erzwingen
    step: zugriff
    type: boolean
    default: true
    required: true

credentials:

  per_group:
    - linux:
        username: "{{ username }}"
        password: generate

  teacher:

user_files:
  - name:        aufgabe_pdf
    label:       "Aufgabenstellung (PDF)"
    description: "Wird auf alle VMs kopiert — gleiche Aufgabe für alle Gruppen."
    required:    false
    accept:      "*.pdf"
    destination: /opt/dozilab/user-files/aufgabe.pdf
    mode:        all_stacks

  - name:        material_gruppe
    label:       "Gruppenmaterial"
    description: "Pro Gruppe eigene Dateien — z.B. unterschiedliche Datensätze oder Aufgaben."
    required:    false
    accept:      "*"
    destination: /opt/dozilab/user-files/{{ group_name }}/material
    mode:        per_group

outputs:
  - name: floating_ip
    label: Floating IP
    from_heat_output: floating_ip

  - name: server_id
    label: Server ID
    from_heat_output: server_id
"""

ANSIBLE_MULTIUSER_HEAT_TEMPLATE = """
heat_template_version: 2018-08-31

description: >
  DoziLab Ansible Multi-User VM.
  Nur Infrastruktur — keine user_data, keine cloud-init.
  Konfiguration übernimmt Ansible vom Backend aus per SSH.

parameters:
  image:
    type: string
    default: "Ubuntu 22.04 2025-01"
    constraints:
      - allowed_values:
          - "Ubuntu 22.04 2025-01"
          - "Ubuntu 24.04 2025-01"
          - "Ubuntu 24.04 2026-01"

  flavor:
    type: string
    default: "gp1.small"
    constraints:
      - allowed_values: ["gp1.small", "gp1.medium"]

  ssh_cidr:
    type: string
    default: "141.72.0.0/16"
    constraints:
      - allowed_pattern: '^(\\d{1,3}\\.){3}\\d{1,3}/\\d{1,2}$'

  stack_label:
    type: string
    default: "ansible"
    constraints:
      - allowed_pattern: '^[a-z0-9][a-z0-9-]{0,30}$'

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

resources:
  secgroup:
    type: OS::Neutron::SecurityGroup
    properties:
      description: SSH + ICMP aus erlaubtem CIDR
      rules:
        - direction: ingress
          protocol: tcp
          port_range_min: 22
          port_range_max: 22
          remote_ip_prefix: { get_param: ssh_cidr }
        - direction: ingress
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
          template: "dozilab-LABEL"
          params:
            LABEL: { get_param: stack_label }
      image:    { get_param: image }
      flavor:   { get_param: flavor }
      key_name: { get_param: key_name }
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
      port_id:       { get_resource: port }

outputs:
  floating_ip:
    value: { get_attr: [fip, floating_ip_address] }

  server_id:
    value: { get_resource: server }
"""

ANSIBLE_MULTIUSER_PLAYBOOK = """
---
- name: DoziLab Multi-User Setup
  hosts: all
  remote_user: ubuntu
  become: true

  tasks:

    - name: /opt/dozilab nur für root zugänglich machen
      file:
        path:  /opt/dozilab
        state: directory
        owner: root
        group: root
        mode:  "0700"

    - name: Student Accounts erstellen
      user:
        name:        "{{ item.username }}"
        shell:       /bin/bash
        create_home: true
        state:       present
      loop: "{{ students }}"
      no_log: true

    - name: Passwörter setzen
      user:
        name:     "{{ item.username }}"
        password: "{{ item.linux.password | password_hash('sha512') }}"
        update_password: always
      loop: "{{ students }}"
      no_log: true

    - name: Passwort-Änderung beim ersten Login erzwingen
      command: chage -d 0 {{ item.username }}
      loop: "{{ students }}"
      no_log: true
      when: force_password_change | bool

    - name: Arbeitsverzeichnis erstellen
      file:
        path:  "/home/{{ item.username }}/work"
        state: directory
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode:  "0700"
      loop: "{{ students }}"
      no_log: true

    - name: .bashrc für jeden Student setzen
      copy:
        src:   /opt/dozilab/files/bashrc
        dest:  "/home/{{ item.username }}/.bashrc"
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode:  "0644"
        remote_src: true
      loop: "{{ students }}"
      no_log: true

    - name: MOTD setzen
      shell: |
        sed 's/__STACK_LABEL__/{{ stack_label }}/g' \\
          /opt/dozilab/files/motd > /etc/update-motd.d/99-dozilab
        chmod +x /etc/update-motd.d/99-dozilab

    - name: Scripts ausführbar machen
      file:
        path:  "{{ item }}"
        mode:  "0755"
      loop:
        - /opt/dozilab/scripts/check_student_setup.sh
        - /opt/dozilab/scripts/reset_password.sh

    - name: Student-Setup verifizieren
      command: /opt/dozilab/scripts/check_student_setup.sh {{ item.username }}
      loop: "{{ students }}"
      register: check_result
      changed_when: false
      no_log: true

    - name: Aufgabenstellung in Arbeitsverzeichnis kopieren
      copy:
        src:   /opt/dozilab/user-files/aufgabe.pdf
        dest:  "/home/{{ item.username }}/work/aufgabe.pdf"
        owner: "{{ item.username }}"
        mode:  "0644"
        remote_src: true
      loop: "{{ students }}"
      no_log: true
      when: user_files.aufgabe_pdf.exists | default(false)

    - name: Gruppenverzeichnis für Material erstellen
      file:
        path:  "/home/{{ item.username }}/work/material"
        state: directory
        owner: "{{ item.username }}"
        mode:  "0700"
      loop: "{{ students }}"
      no_log: true
      when: user_files.material_gruppe[item.group_name].exists | default(false)

    - name: Gruppenmaterial in Arbeitsverzeichnis kopieren
      copy:
        src:   "/opt/dozilab/user-files/{{ item.group_name }}/material"
        dest:  "/home/{{ item.username }}/work/material/"
        owner: "{{ item.username }}"
        mode:  "0600"
        remote_src: true
      loop: "{{ students }}"
      no_log: true
      when: user_files.material_gruppe[item.group_name].exists | default(false)
"""


ANSIBLE_MULTIUSER_BASHRC = """# ==============================================================================
# DoziLab: .bashrc für Student-Accounts
# ==============================================================================
export HISTSIZE=1000
export HISTFILESIZE=2000
export EDITOR=nano

force_color_prompt=yes
PS1='\\[\\033[01;32m\\]\\u@\\h\\[\\033[00m\\]:\\[\\033[01;34m\\]\\w\\[\\033[00m\\]\\$ '

alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias ..='cd ..'
alias work='cd ~/work'

echo ""
echo "  Willkommen, $(whoami)!"
echo "  Dein Arbeitsverzeichnis: ~/work"
echo ""
"""

ANSIBLE_MULTIUSER_MOTD = """#!/usr/bin/env bash
# ==============================================================================
# DoziLab: Message of the Day
# Platzhalter __STACK_LABEL__ wird vom Playbook ersetzt.
# ==============================================================================
echo ""
echo "  ██████╗  ██████╗ ███████╗██╗██╗      █████╗ ██████╗ "
echo "  ██╔══██╗██╔═══██╗╚══███╔╝██║██║     ██╔══██╗██╔══██╗"
echo "  ██║  ██║██║   ██║  ███╔╝ ██║██║     ███████║██████╔╝"
echo "  ██║  ██║██║   ██║ ███╔╝  ██║██║     ██╔══██║██╔══██╗"
echo "  ██████╔╝╚██████╔╝███████╗██║███████╗██║  ██║██████╔╝"
echo "  ╚═════╝  ╚═════╝ ╚══════╝╚═╝╚══════╝╚═╝  ╚═╝╚═════╝ "
echo ""
echo "  Kurs:    __STACK_LABEL__"
echo "  Support: Wende dich an deinen Dozenten"
echo ""
"""

ANSIBLE_MULTIUSER_CHECK_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
USERNAME="${1:?Usage: check_student_setup.sh <username>}"
ERRORS=0

check() {
    local desc="$1"; local result="$2"
    if [[ "$result" == "ok" ]]; then echo "  ✓ $desc"
    else echo "  ✗ $desc → $result"; ERRORS=$((ERRORS + 1)); fi
}

echo "Checking setup for: $USERNAME"
id "$USERNAME" &>/dev/null && check "Account existiert" "ok" || check "Account existiert" "nicht gefunden"
[[ -d "/home/$USERNAME" ]] && check "Home-Verzeichnis" "ok" || check "Home-Verzeichnis" "fehlt"
[[ -d "/home/$USERNAME/work" ]] && check "Arbeitsverzeichnis" "ok" || check "Arbeitsverzeichnis" "fehlt"
passwd -S "$USERNAME" 2>/dev/null | grep -qv " L " && check "Passwort gesetzt" "ok" || check "Passwort gesetzt" "gesperrt"
SHELL=$(getent passwd "$USERNAME" | cut -d: -f7)
[[ "$SHELL" == "/bin/bash" ]] && check "Shell ist /bin/bash" "ok" || check "Shell ist /bin/bash" "ist $SHELL"

echo ""
if [[ $ERRORS -eq 0 ]]; then echo "✓ Setup OK für $USERNAME"; exit 0
else echo "✗ $ERRORS Fehler für $USERNAME"; exit 1; fi
"""

ANSIBLE_MULTIUSER_RESET_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
USERNAME="${1:?Usage: reset_password.sh <username> <new_password>}"
NEW_PASSWORD="${2:?Usage: reset_password.sh <username> <new_password>}"
if ! id "$USERNAME" &>/dev/null; then echo "ERROR: Account '$USERNAME' nicht gefunden" >&2; exit 1; fi
echo "${USERNAME}:${NEW_PASSWORD}" | chpasswd
echo "✓ Passwort für '$USERNAME' zurückgesetzt"
chage -d 0 "$USERNAME"
echo "✓ Passwort-Änderung beim nächsten Login erzwungen"
"""


def create_mock_templates(db: Session, owner_id: str) -> list[Template]:
    """Create mock templates."""
    templates_data = [
        {
            "name": "Ansible Multi-User Ubuntu",
            "description": "Ubuntu VM mit mehreren Benutzerkonten, verwaltet durch Ansible. Pro Gruppe wird ein Linux-Account mit eigenem Arbeitsverzeichnis erstellt.",
            "repo_url": "https://github.com/dozilab/appstore-templates",
            "icon_url": "mdi:server-network",
            "visibility": TemplateVisibility.PUBLIC,
        },
        {
            "name": "PostgreSQL Group Database",
            "description": "Deploy a PostgreSQL database server where each student group gets its own database and role. Optional pgAdmin4 web interface for database management",
            "repo_url": "https://github.com/dozilab/appstore-templates",
            "icon_url": "mdi:database",
            "visibility": TemplateVisibility.PUBLIC,
        }
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
            if template.name == "Ansible Multi-User Ubuntu":
                app_yaml_content = ANSIBLE_MULTIUSER_APP_YAML
                heat_template_content = ANSIBLE_MULTIUSER_HEAT_TEMPLATE
                cloud_init_content = None
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

            files_in_version = 2

            # Create cloud-init user-data (only for templates that use it)
            if cloud_init_content is not None:
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
                files_in_version += 1

            # Create ansible playbook (only for ansible-based templates)
            if template.name == "Ansible Multi-User Ubuntu":
                playbook = TemplateVersionFile(
                    template_version_id=version.id,
                    file_name="main.yml",
                    file_type=FileType.ANSIBLE_PLAYBOOK,
                    file_path="playbooks/main.yml",
                    content=ANSIBLE_MULTIUSER_PLAYBOOK,
                    is_primary=False
                )
                db.add(playbook)
                files_in_version += 1

                for name, content in [("bashrc", ANSIBLE_MULTIUSER_BASHRC), ("motd", ANSIBLE_MULTIUSER_MOTD)]:
                    db.add(TemplateVersionFile(
                        template_version_id=version.id,
                        file_name=name,
                        file_type=FileType.CONFIG_FILE,
                        file_path=f"files/{name}",
                        content=content,
                        is_primary=False
                    ))
                    files_in_version += 1

                for name, content in [
                    ("check_student_setup.sh", ANSIBLE_MULTIUSER_CHECK_SCRIPT),
                    ("reset_password.sh", ANSIBLE_MULTIUSER_RESET_SCRIPT),
                ]:
                    db.add(TemplateVersionFile(
                        template_version_id=version.id,
                        file_name=name,
                        file_type=FileType.SHELL_SCRIPT,
                        file_path=f"scripts/{name}",
                        content=content,
                        is_primary=False
                    ))
                    files_in_version += 1

            db.commit()
            files_created += 1
            logger.info(f"✅ Created {files_in_version} files for version: {version.id} (template: {template.name})")
            
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
