"""Seed mock data for development and testing.

Seeds two templates pulled directly from appstore-apps/:
  * Multi-User Ubuntu           (from appstore-apps/ansible_multiuser)
  * PostgreSQL Group DB         (from appstore-apps/ansible_postgres_group_db)

The file contents below are inlined at generation time (see scripts that
build this file). To refresh them after editing an app file on disk,
re-run the embed step or use scripts/sync_app_files_to_db.py to push the
disk version into an already-seeded DB without restarting.

Legacy templates (older names from earlier iterations) are deleted on
seeder run so the dashboard stays clean.
"""
import logging
from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import User

logger = logging.getLogger(__name__)


# ============================================================================
# File contents — inlined from appstore-apps/. Regenerate to pick up changes.
# ============================================================================

MULTIUSER_APP_YAML = r'''
app:
  name: ansible-multiuser
  label: Ansible Multi-User Ubuntu
  version: 2.1.0
  description: >
    Ubuntu VM mit mehreren Benutzerkonten, verwaltet durch Ansible.
    Pro Gruppe wird ein Linux-Account mit eigenem Arbeitsverzeichnis erstellt.
    Root disk is a Cinder volume (Boot from Volume) so "Speicher" can be configured.
  owner_team: dozilab-app-team

  allow_user_files: true

# Maps each role-bearing file in this folder to its FileType so the backend's
# GitHub-import wiring picks them up at deploy time. Without this block every
# file is imported as OTHER and the deploy pipeline finds no Heat template
# and no playbook. ``heat_template`` is also marked as the primary file
# (deployment entrypoint).
#
# ``shell_scripts`` and ``config_files`` accept a list of paths so that
# multiple helper scripts (scripts/) and configuration files (files/) get
# their FileType set correctly — without that, the deploy-side copy step
# would skip them and the playbook would fail with "file not found" when
# trying to read /opt/dozilab/files/bashrc or /opt/dozilab/scripts/*.
artifacts:
  heat_template:    heat/main.yaml
  ansible_playbook: playbooks/main.yml
  shell_scripts:
    - scripts/check_student_setup.sh
    - scripts/reset_password.sh
  config_files:
    - files/bashrc
    - files/motd

parameters:
  - name: stack_label
    label: Stack-Label
    step: template
    type: string
    default: ansible
    required: true
    description: >
      Kurzes Label für diesen Stack (z.B. kurs-ws2026).
      Muss passen zu: ^[a-z0-9][a-z0-9-]{0,30}$

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

  - name: ssh_cidr
    label: SSH-Zugriff (CIDR)
    step: netzwerk
    type: string
    default: "141.72.0.0/16"
    required: true
    description: >
      Nur dieses Netz darf per SSH zugreifen.
      Standard: DHBW/VPN. Beispiel: 141.72.0.0/16 oder 1.2.3.4/32.

  - name: force_password_change
    label: Passwort-Änderung beim ersten Login erzwingen
    step: zugriff
    type: boolean
    default: true
    required: true

  - name: workdir
    label: Arbeitsordner
    step: zugriff
    type: string
    default: "work"
    required: true
    description: "Directory created under each group user's home and used as default login directory."

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

credentials:
  per_group:
    - linux:
        username: "{{ username }}"
        password: generate
        ssh_key: generate

  teacher:
    # teacher.linux automatisch vorhanden — kein Eintrag nötig

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

  - name: ssh_hint
    label: SSH Hinweis
    from_heat_output: ssh_hint

  - name: root_volume_id
    label: Root Volume ID
    from_heat_output: root_volume_id
'''

MULTIUSER_HEAT_TEMPLATE = r'''
heat_template_version: 2018-08-31

description: >
  DoziLab Ansible Multi-User VM.
  Nur Infrastruktur — keine user_data, keine cloud-init.
  Konfiguration übernimmt Ansible vom Backend aus per SSH.
  Root disk is provisioned as a Cinder volume (Boot from Volume) so "Speicher" can be configured.

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

  volume_size:
    type: number
    default: 8
    constraints:
      - range: { min: 8, max: 200 }
    description: "Root volume size in GB."

  ssh_cidr:
    type: string
    default: "141.72.0.0/16"
    constraints:
      - allowed_pattern: '^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$'
    description: "IPv4 CIDR allowed to SSH and ICMP."

  stack_label:
    type: string
    default: "ansible"
    constraints:
      - allowed_pattern: '^[a-z0-9][a-z0-9-]{0,30}$'
    description: "Internal label used for resource names/metadata."

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
    description: "Admin/support SSH keypair. Backend should set this from ANSIBLE_SSH_KEY_NAME."

resources:
  secgroup:
    type: OS::Neutron::SecurityGroup
    properties:
      description: SSH + ICMP aus erlaubtem CIDR
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

  root_volume:
    type: OS::Cinder::Volume
    properties:
      name:
        str_replace:
          template: "dozilab-STACK-root"
          params:
            STACK: { get_param: stack_label }
      size: { get_param: volume_size }
      image: { get_param: image }
      metadata:
        dozilab_stack_label: { get_param: stack_label }

  server:
    type: OS::Nova::Server
    properties:
      name:
        str_replace:
          template: "dozilab-STACK"
          params:
            STACK: { get_param: stack_label }

      flavor: { get_param: flavor }
      key_name: { get_param: key_name }

      block_device_mapping_v2:
        - boot_index: 0
          volume_id: { get_resource: root_volume }
          delete_on_termination: true

      networks:
        - port: { get_resource: port }

      metadata:
        dozilab_stack_label: { get_param: stack_label }
        dozilab_config_method: "ansible"

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
    description: "Public floating IP address."
    value: { get_attr: [fip, floating_ip_address] }

  server_id:
    description: "Nova server ID."
    value: { get_resource: server }

  ssh_hint:
    description: "Students login like: ssh <username>@<floating_ip>"
    value:
      str_replace:
        template: "ssh <username>@FIP"
        params:
          FIP: { get_attr: [fip, floating_ip_address] }

  root_volume_id:
    description: "Cinder root volume ID."
    value: { get_resource: root_volume }'''

MULTIUSER_PLAYBOOK = r'''
---
# DoziLab Ansible Playbook: Multi-User Ubuntu
#
# Variablen (vom Backend):
#   deployment_groups[].username                         # sanitized Linux-User pro Gruppe
#   deployment_groups[].linux.password
#   deployment_groups[].linux.ssh_key.public_key         # optional (nur wenn app.yaml: ssh_key: generate)
#   deployment_groups[].linux.ssh_key.private_key        # optional, nur informativ — wird NICHT auf die VM kopiert
#   deployment_groups[].group_name                       # Original-Gruppenname (für user_files-Lookup)
#   stack_label
#   force_password_change
#   workdir
#   pw_min_length
#   pw_require_digit
#   pw_require_upper
#   pw_require_special
#   user_files.aufgabe_pdf.exists
#   user_files.material_gruppe[group_name].exists
#
# Hinweis: ``deployment_groups`` heißt NICHT ``groups`` — letzteres ist eine
# reservierte Ansible-Magic-Variable (Inventory-Dict). Würden wir unsere
# Group-Liste so nennen, würde Ansible sie mit dem Inventory-Dict
# überschreiben und alle loop-Tasks unten würden über etwas ganz anderes
# iterieren.

- name: DoziLab Multi-User Setup
  hosts: all
  remote_user: ubuntu
  become: true

  vars:
    dozilab_workdir: "{{ workdir | default('work') }}"
    dozilab_pw_min_length: "{{ pw_min_length | default(12) }}"
    dozilab_pw_require_digit: "{{ pw_require_digit | default(true) }}"
    dozilab_pw_require_upper: "{{ pw_require_upper | default(true) }}"
    dozilab_pw_require_special: "{{ pw_require_special | default(true) }}"

  tasks:
    - name: Arbeitsordner-Parameter validieren
      assert:
        that:
          - dozilab_workdir is match('^[A-Za-z0-9._-]{1,32}$')
        fail_msg: "Invalid workdir. Allowed pattern: ^[A-Za-z0-9._-]{1,32}$"

    - name: Passwort-Mindestlänge validieren
      assert:
        that:
          - (dozilab_pw_min_length | int) >= 4
          - (dozilab_pw_min_length | int) <= 128
        fail_msg: "pw_min_length must be between 4 and 128."

    - name: Benötigte Pakete installieren
      apt:
        name:
          - libpam-pwquality
          - python3
          - cloud-guest-utils
        state: present
        update_cache: true

    - name: Passwort-Policy Variablen berechnen
      set_fact:
        pw_dcredit: "{{ '-1' if (dozilab_pw_require_digit | bool) else '0' }}"
        pw_ucredit: "{{ '-1' if (dozilab_pw_require_upper | bool) else '0' }}"
        pw_ocredit: "{{ '-1' if (dozilab_pw_require_special | bool) else '0' }}"

    - name: pwquality.conf schreiben
      copy:
        dest: /etc/security/pwquality.conf
        owner: root
        group: root
        mode: "0644"
        content: |
          # Managed by DoziLab (Ansible). NOTE: PAM options override this file.
          minlen = {{ dozilab_pw_min_length | int }}
          dcredit = {{ pw_dcredit }}
          ucredit = {{ pw_ucredit }}
          ocredit = {{ pw_ocredit }}
          dictcheck = 0
          usercheck = 0
          gecoscheck = 0
          difok = 0
          maxrepeat = 0
          minclass = 0

    - name: Prüfen ob pam_pwquality bereits konfiguriert ist
      command: grep -qE '^\s*password\s+requisite\s+pam_pwquality\.so' /etc/pam.d/common-password
      register: pam_pwquality_check
      changed_when: false
      failed_when: false

    - name: Bestehende pam_pwquality Zeile ersetzen
      replace:
        path: /etc/pam.d/common-password
        regexp: '^\s*password\s+requisite\s+pam_pwquality\.so.*$'
        replace: "password requisite pam_pwquality.so retry=3 enforce_for_root minlen={{ dozilab_pw_min_length | int }} dcredit={{ pw_dcredit }} ucredit={{ pw_ucredit }} ocredit={{ pw_ocredit }} dictcheck=0 usercheck=0 gecoscheck=0 difok=0 maxrepeat=0 minclass=0"
      when: pam_pwquality_check.rc == 0

    - name: pam_pwquality vor pam_unix einfügen
      lineinfile:
        path: /etc/pam.d/common-password
        insertbefore: '^\s*password\s+.*pam_unix\.so'
        line: "password requisite pam_pwquality.so retry=3 enforce_for_root minlen={{ dozilab_pw_min_length | int }} dcredit={{ pw_dcredit }} ucredit={{ pw_ucredit }} ocredit={{ pw_ocredit }} dictcheck=0 usercheck=0 gecoscheck=0 difok=0 maxrepeat=0 minclass=0"
      when: pam_pwquality_check.rc != 0

    - name: /opt/dozilab nur für root zugänglich machen
      file:
        path: /opt/dozilab
        state: directory
        owner: root
        group: root
        mode: "0700"

    - name: Gruppen-Linux-Accounts erstellen
      user:
        name: "{{ item.username }}"
        shell: /bin/bash
        create_home: true
        state: present
      loop: "{{ deployment_groups }}"
      no_log: true

    - name: Passwörter setzen
      user:
        name: "{{ item.username }}"
        password: "{{ item.linux.password | password_hash('sha512') }}"
        update_password: always
      loop: "{{ deployment_groups }}"
      no_log: true

    - name: Gruppen-SSH-Public-Key in authorized_keys installieren
      # Backend generiert per app.yaml `ssh_key: generate` ein Ed25519-Keypair
      # pro Gruppe. Der Public-Key landet hier in ~/.ssh/authorized_keys des
      # Gruppen-Linux-Users, der Private-Key bleibt in der Backend-DB und wird
      # via /student-API zum Download bereitgestellt. Task ist no-op für
      # Gruppen ohne Keypair (z.B. Apps die `ssh_key: generate` nicht setzen).
      ansible.posix.authorized_key:
        user:  "{{ item.username }}"
        key:   "{{ item.linux.ssh_key.public_key }}"
        state: present
      loop: "{{ deployment_groups }}"
      when: item.linux.ssh_key is defined and item.linux.ssh_key.public_key is defined
      no_log: true

    - name: Passwort-Änderung beim ersten Login erzwingen
      command: chage -d 0 {{ item.username }}
      loop: "{{ deployment_groups }}"
      no_log: true
      when: force_password_change | bool

    - name: Home-Verzeichnis absichern
      file:
        path: "/home/{{ item.username }}"
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode: "0700"
      loop: "{{ deployment_groups }}"
      no_log: true

    - name: Arbeitsverzeichnis erstellen
      file:
        path: "/home/{{ item.username }}/{{ dozilab_workdir }}"
        state: directory
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode: "0700"
      loop: "{{ deployment_groups }}"
      no_log: true

    - name: Standard-Login-Verzeichnis in .profile setzen
      lineinfile:
        path: "/home/{{ item.username }}/.profile"
        line: 'cd "$HOME/{{ dozilab_workdir }}"'
        create: true
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode: "0644"
      loop: "{{ deployment_groups }}"
      no_log: true

    - name: .bashrc für jeden Gruppen-User setzen
      copy:
        src: /opt/dozilab/files/bashrc
        dest: "/home/{{ item.username }}/.bashrc"
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode: "0644"
        remote_src: true
      loop: "{{ deployment_groups }}"
      no_log: true

    - name: Arbeitsordner in .bashrc ersetzen
      replace:
        path: "/home/{{ item.username }}/.bashrc"
        regexp: "__WORKDIR__"
        replace: "{{ dozilab_workdir }}"
      loop: "{{ deployment_groups }}"
      no_log: true

    - name: MOTD setzen
      shell: |
        sed 's/__STACK_LABEL__/{{ stack_label }}/g' \
          /opt/dozilab/files/motd > /etc/update-motd.d/99-dozilab
        chmod +x /etc/update-motd.d/99-dozilab

    - name: Scripts ausführbar machen
      file:
        path: "{{ item }}"
        mode: "0755"
      loop:
        - /opt/dozilab/scripts/check_student_setup.sh
        - /opt/dozilab/scripts/reset_password.sh

    - name: Gruppen-Setup verifizieren
      command: /opt/dozilab/scripts/check_student_setup.sh {{ item.username }} {{ dozilab_workdir }}
      loop: "{{ deployment_groups }}"
      register: check_result
      changed_when: false
      no_log: true

    - name: Aufgabenstellung in Arbeitsverzeichnis kopieren
      copy:
        src: /opt/dozilab/user-files/aufgabe.pdf
        dest: "/home/{{ item.username }}/{{ dozilab_workdir }}/aufgabe.pdf"
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode: "0644"
        remote_src: true
      loop: "{{ deployment_groups }}"
      no_log: true
      when: user_files.aufgabe_pdf.exists | default(false)

    - name: Gruppenverzeichnis für Material erstellen
      file:
        path: "/home/{{ item.username }}/{{ dozilab_workdir }}/material"
        state: directory
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode: "0700"
      loop: "{{ deployment_groups }}"
      no_log: true
      when: user_files.material_gruppe[item.group_name].exists | default(false)

    - name: Gruppenmaterial in Arbeitsverzeichnis kopieren
      copy:
        src: "/opt/dozilab/user-files/{{ item.group_name }}/material"
        dest: "/home/{{ item.username }}/{{ dozilab_workdir }}/material/"
        owner: "{{ item.username }}"
        group: "{{ item.username }}"
        mode: "0600"
        remote_src: true
      loop: "{{ deployment_groups }}"
      no_log: true
      when: user_files.material_gruppe[item.group_name].exists | default(false)
'''

MULTIUSER_BASHRC = r'''
# ==============================================================================
# DoziLab: .bashrc für Student-Accounts
# Wird von Ansible in jeden Home-Ordner kopiert.
# ==============================================================================

# Basis
export HISTSIZE=1000
export HISTFILESIZE=2000
export EDITOR=nano

# Farben im Terminal
force_color_prompt=yes
PS1='\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '

# Praktische Aliase
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias ..='cd ..'
alias work='cd ~/__WORKDIR__'

# Begrüßung beim Login
echo ""
echo "  Willkommen, $(whoami)!"
echo "  Dein Arbeitsverzeichnis: ~/__WORKDIR__"
echo ""
'''

MULTIUSER_MOTD = r'''
#!/usr/bin/env bash
# ==============================================================================
# DoziLab: Message of the Day — wird beim SSH-Login angezeigt.
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
'''

MULTIUSER_CHECK_SCRIPT = r'''
#!/usr/bin/env bash
# ==============================================================================
# DoziLab: Check ob ein Student-Account korrekt eingerichtet ist.
# Wird vom Playbook nach dem Setup aufgerufen.
#
# Usage: check_student_setup.sh <username> [workdir]
# Gibt 0 zurück wenn alles OK, 1 wenn etwas fehlt.
# ==============================================================================
set -euo pipefail

USERNAME="${1:?Usage: check_student_setup.sh <username> [workdir]}"
WORKDIR="${2:-work}"
ERRORS=0

check() {
    local desc="$1"
    local result="$2"
    if [[ "$result" == "ok" ]]; then
        echo "  ✓ $desc"
    else
        echo "  ✗ $desc → $result"
        ERRORS=$((ERRORS + 1))
    fi
}

echo "Checking setup for: $USERNAME"
echo "Expected workdir: $WORKDIR"

id "$USERNAME" &>/dev/null \
    && check "Account existiert" "ok" \
    || check "Account existiert" "nicht gefunden"

[[ -d "/home/$USERNAME" ]] \
    && check "Home-Verzeichnis /home/$USERNAME" "ok" \
    || check "Home-Verzeichnis /home/$USERNAME" "fehlt"

[[ -d "/home/$USERNAME/$WORKDIR" ]] \
    && check "Arbeitsverzeichnis /home/$USERNAME/$WORKDIR" "ok" \
    || check "Arbeitsverzeichnis /home/$USERNAME/$WORKDIR" "fehlt"

passwd -S "$USERNAME" 2>/dev/null | grep -qv " L " \
    && check "Passwort gesetzt" "ok" \
    || check "Passwort gesetzt" "Account gesperrt oder kein Passwort"

USER_SHELL=$(getent passwd "$USERNAME" | cut -d: -f7)
[[ "$USER_SHELL" == "/bin/bash" ]] \
    && check "Shell ist /bin/bash" "ok" \
    || check "Shell ist /bin/bash" "ist $USER_SHELL"

echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo "✓ Setup OK für $USERNAME"
    exit 0
else
    echo "✗ $ERRORS Fehler gefunden für $USERNAME"
    exit 1
fi
'''

MULTIUSER_RESET_SCRIPT = r'''
#!/usr/bin/env bash
# ==============================================================================
# DoziLab: Passwort eines Student-Accounts zurücksetzen.
# Kann vom Lehrer manuell aufgerufen werden.
#
# Usage: reset_password.sh <username> <new_password>
# ==============================================================================
set -euo pipefail

USERNAME="${1:?Usage: reset_password.sh <username> <new_password>}"
NEW_PASSWORD="${2:?Usage: reset_password.sh <username> <new_password>}"

# Prüfen ob Account existiert
if ! id "$USERNAME" &>/dev/null; then
    echo "ERROR: Account '$USERNAME' nicht gefunden" >&2
    exit 1
fi

# Passwort setzen
echo "${USERNAME}:${NEW_PASSWORD}" | chpasswd
echo "✓ Passwort für '$USERNAME' zurückgesetzt"

# Passwort-Änderung beim nächsten Login erzwingen
chage -d 0 "$USERNAME"
echo "✓ Passwort-Änderung beim nächsten Login erzwungen"
'''

POSTGRES_APP_YAML = r'''
app:
  name: ansible-postgres-group-db
  label: Ansible PostgreSQL Group DB
  version: 2.0.0
  description: >
    Ubuntu VM mit PostgreSQL, Gruppen-Datenbanken, Teacher-Zugriff und optionalem pgAdmin.
    Infrastruktur wird per Heat erstellt, Konfiguration läuft per Ansible.
  owner_team: dozilab-app-team

artifacts:
  heat_template: heat/main.yaml
  ansible_playbook: playbooks/main.yml

# ------------------------------------------------------------------------------
# Parameter
# ------------------------------------------------------------------------------
parameters:

  # --- Schritt 1: Template ---

  - name: stack_label
    label: Stack-Label
    step: template
    type: string
    default: sql
    required: true
    description: "Kurzes Label für diesen Stack, z.B. sql-2026-01."

  # --- Schritt 2: Konfiguration ---

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
      - "gp1.large"
      - "mb1.small"
      - "mb1.medium"
      - "mb1.large"
    description: >
      VM-Größe für PostgreSQL und optional pgAdmin.
      gp1.small reicht für kleine Kurse und Tests.
      Für größere Kurse oder pgAdmin-Nutzung sind gp1.medium, gp1.large oder mb1.* sinnvoll.

  - name: volume_size
    label: Speicher (GB)
    step: konfiguration
    type: number
    default: 8
    required: true
    enum:
      - 8
      - 16
      - 32
      - 64
      - 128
    description: "Größe der Root-Disk als Cinder-Volume."

  # --- Schritt 3: Netzwerk ---

  - name: ssh_cidr
    label: SSH-Zugriff (CIDR)
    step: netzwerk
    type: string
    default: "141.72.0.0/16"
    required: true
    description: "Nur dieses Netz darf per SSH zugreifen. Standard: DHBW/VPN."

  - name: web_cidr
    label: pgAdmin-Zugriff (CIDR)
    step: netzwerk
    type: string
    default: "141.72.0.0/16"
    required: true
    description: "Nur dieses Netz darf pgAdmin über HTTP Port 80 erreichen."

  # --- Plattform-fest / hidden ---

  - name: network
    label: Internes Netzwerk
    step: netzwerk
    type: string
    default: "NAT"
    hidden: true
    description: "Internes OpenStack-Netzwerk."

  - name: external_network
    label: Externes Netzwerk
    step: netzwerk
    type: string
    default: "DHBW"
    hidden: true
    description: "Floating-IP-Netzwerk."


# ------------------------------------------------------------------------------
# Credentials
# ------------------------------------------------------------------------------
credentials:
  per_group:
    - postgres:
        database_name: "db_{{ username }}"
        db_user: "{{ username }}"
        password: generate

    - pgadmin:
        email: "{{ email }}"
        password: generate

  teacher:
    - postgres:
        db_user: teacher
        password: generate

    - pgadmin:
        email: "{{ email }}"
        password: generate

# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------
outputs:
  - name: ssh_user
    label: SSH User
    from_heat_output: ssh_user

  - name: floating_ip
    label: Floating IP
    from_heat_output: floating_ip

  - name: pgadmin_url
    label: pgAdmin URL
    from_heat_output: pgadmin_url'''

POSTGRES_HEAT_TEMPLATE = r'''
heat_template_version: 2018-08-31

description: >
  DoziLab Ansible PostgreSQL Group DB VM.
  Nur Infrastruktur — keine user_data, keine cloud-init.
  Konfiguration übernimmt Ansible vom Backend aus per SSH.
  Root disk is a Cinder volume (Boot from Volume) so "Speicher" can be configured.

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
          - "gp1.large"
          - "mb1.small"
          - "mb1.medium"
          - "mb1.large"
    description: "VM size for PostgreSQL and optional pgAdmin."

  volume_size:
    type: number
    default: 8
    constraints:
      - range: { min: 8, max: 200 }
    description: "Root volume size in GB."

  ssh_cidr:
    type: string
    default: "141.72.0.0/16"
    constraints:
      - allowed_pattern: '^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$'
    description: "IPv4 CIDR allowed to SSH and ICMP."

  web_cidr:
    type: string
    default: "141.72.0.0/16"
    constraints:
      - allowed_pattern: '^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$'
    description: "IPv4 CIDR allowed to reach pgAdmin over HTTP."

  stack_label:
    type: string
    default: "sql"
    constraints:
      - allowed_pattern: '^[a-z0-9][a-z0-9-]{0,30}$'
    description: "Internal label used for resource names/metadata."

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
    description: "Admin/support SSH keypair. Backend should set this from ANSIBLE_SSH_KEY_NAME."

resources:
  secgroup:
    type: OS::Neutron::SecurityGroup
    properties:
      description: SSH, ICMP und pgAdmin HTTP aus erlaubten CIDRs
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

        - direction: ingress
          ethertype: IPv4
          protocol: tcp
          port_range_min: 80
          port_range_max: 80
          remote_ip_prefix: { get_param: web_cidr }

        - direction: egress
          ethertype: IPv4

  port:
    type: OS::Neutron::Port
    properties:
      network: { get_param: network }
      security_groups:
        - { get_resource: secgroup }

  root_volume:
    type: OS::Cinder::Volume
    properties:
      name:
        str_replace:
          template: "dozilab-pg-STACK-root"
          params:
            STACK: { get_param: stack_label }
      size: { get_param: volume_size }
      image: { get_param: image }
      metadata:
        dozilab_stack_label: { get_param: stack_label }
        dozilab_app: "ansible-postgres-group-db"

  server:
    type: OS::Nova::Server
    properties:
      name:
        str_replace:
          template: "dozilab-pg-STACK"
          params:
            STACK: { get_param: stack_label }

      flavor: { get_param: flavor }
      key_name: { get_param: key_name }

      block_device_mapping_v2:
        - boot_index: 0
          volume_id: { get_resource: root_volume }
          delete_on_termination: true

      networks:
        - port: { get_resource: port }

      metadata:
        dozilab_stack_label: { get_param: stack_label }
        dozilab_config_method: "ansible"
        dozilab_app: "ansible-postgres-group-db"

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
    description: "SSH username."
    value: ubuntu

  floating_ip:
    description: "Public floating IP address."
    value: { get_attr: [fip, floating_ip_address] }

  private_ip:
    description: "Private IP on tenant network."
    value: { get_attr: [port, fixed_ips, 0, ip_address] }

  server_id:
    description: "Nova server ID."
    value: { get_resource: server }

  pgadmin_url:
    description: "pgAdmin4 URL."
    value:
      str_replace:
        template: "http://FIP/pgadmin4/"
        params:
          FIP: { get_attr: [fip, floating_ip_address] }

  ssh_hint:
    description: "Admin SSH command."
    value:
      str_replace:
        template: "ssh -i ~/.ssh/heat-bastion-key.pem ubuntu@FIP"
        params:
          FIP: { get_attr: [fip, floating_ip_address] }

  ssh_tunnel_hint:
    description: "PostgreSQL SSH tunnel command."
    value:
      str_replace:
        template: "ssh -i ~/.ssh/heat-bastion-key.pem -L 5432:127.0.0.1:5432 ubuntu@FIP"
        params:
          FIP: { get_attr: [fip, floating_ip_address] }

  root_volume_id:
    description: "Cinder root volume ID."
    value: { get_resource: root_volume }'''

POSTGRES_PLAYBOOK = r'''
---
- name: DoziLab Ansible PostgreSQL Group DB Setup
  hosts: all
  remote_user: ubuntu
  become: true

  vars:
    dozilab_stack_label: "{{ stack_label | default('sql') }}"
    dozilab_mark_dir: /var/lib/dozilab
    dozilab_user_json_path: /etc/dozilab/user.json
    dozilab_postgres_log: /var/log/dozilab-postgres-ansible.log

  tasks:
    - name: Stack-Label validieren
      assert:
        that:
          - dozilab_stack_label is match('^[a-z0-9][a-z0-9-]{0,30}$')
        fail_msg: "stack_label muss ^[a-z0-9][a-z0-9-]{0,30}$ erfüllen."

    - name: DoziLab Verzeichnisse erstellen
      file:
        path: "{{ item.path }}"
        state: directory
        owner: root
        group: root
        mode: "{{ item.mode }}"
      loop:
        - { path: "/etc/dozilab", mode: "0700" }
        - { path: "{{ dozilab_mark_dir }}", mode: "0755" }

    - name: Backend-Credentials validieren
      assert:
        that:
          - deployment_groups is defined
          - deployment_groups | length > 0
          - teacher is defined
          - teacher.postgres is defined
          - teacher.postgres.db_user is defined
          - teacher.postgres.password is defined
          - teacher.pgadmin is defined
          - teacher.pgadmin.email is defined
          - teacher.pgadmin.password is defined
        fail_msg: "Backend-Credentials fehlen. Erwartet werden deployment_groups[].postgres/pgadmin und teacher.postgres/pgadmin."
      no_log: true

    - name: Gruppen-Credentials validieren
      assert:
        that:
          - item.username is defined
          - item.username is match('^[a-z_][a-z0-9_]{0,62}$')
          - item.postgres is defined
          - item.postgres.database_name is defined
          - item.postgres.database_name is match('^[a-z_][a-z0-9_]{0,62}$')
          - item.postgres.db_user is defined
          - item.postgres.db_user is match('^[a-z_][a-z0-9_]{0,62}$')
          - item.postgres.password is defined
          - item.postgres.password | length >= 6
          - item.pgadmin is defined
          - item.pgadmin.email is defined
          - "'@' in item.pgadmin.email"
          - item.pgadmin.password is defined
          - item.pgadmin.password | length >= 6
        fail_msg: "Ungültige Gruppen-Credentials für PostgreSQL/pgAdmin."
      loop: "{{ deployment_groups }}"
      no_log: true

    - name: user_json aus Backend-Credentials erzeugen
      copy:
        dest: "{{ dozilab_user_json_path }}"
        owner: root
        group: root
        mode: "0600"
        content: |
          {
            "course_label": {{ dozilab_stack_label | to_json }},
            "instance": {},
            "applications": [
              {
                "name": "postgres",
                "credentials": [
          {% for g in deployment_groups %}
                  {
                    "group": {{ g.username | to_json }},
                    "database_name": {{ g.postgres.database_name | to_json }},
                    "db_user": {{ g.postgres.db_user | to_json }},
                    "password": {{ g.postgres.password | to_json }}
                  }{% if not loop.last %},{% endif %}
          {% endfor %}
                ],
                "admin_credentials": {
                  "db_user": {{ teacher.postgres.db_user | to_json }},
                  "password": {{ teacher.postgres.password | to_json }}
                }
              },
              {
                "name": "pgadmin",
                "credentials": [
          {% for g in deployment_groups %}
                  {
                    "group": {{ g.username | to_json }},
                    "email": {{ g.pgadmin.email | to_json }},
                    "password": {{ g.pgadmin.password | to_json }}
                  }{% if not loop.last %},{% endif %}
          {% endfor %}
                ],
                "admin_credentials": {
                  "email": {{ teacher.pgadmin.email | to_json }},
                  "password": {{ teacher.pgadmin.password | to_json }}
                }
              }
            ]
          }
      no_log: true

    - name: Erzeugtes user_json validieren
      shell: |
        set -euo pipefail

        python3 - <<'PY'
        import json
        import re
        import sys
        from pathlib import Path

        out_path = Path("/etc/dozilab/user.json")

        if not out_path.exists() or out_path.stat().st_size == 0:
            sys.exit("generated user_json missing/empty")

        obj = json.loads(out_path.read_text(encoding="utf-8"))

        if not isinstance(obj, dict):
            sys.exit("user_json must be an object")

        apps = obj.get("applications")
        if not isinstance(apps, list):
            sys.exit("user_json.applications must be a list")

        def find_app(name: str):
            for a in apps:
                if isinstance(a, dict) and str(a.get("name", "")).lower() == name:
                    return a
            return None

        pg = find_app("postgres") or find_app("postgresql")
        if not pg:
            sys.exit("Missing applications[name=postgres]")

        pg_creds = pg.get("credentials")
        if not isinstance(pg_creds, list) or not pg_creds:
            sys.exit("postgres.credentials must be a non-empty list")

        ident = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
        group_token = re.compile(r"^[A-Za-z0-9_]{1,32}$")

        used_db_users = set()
        used_groups = set()

        for c in pg_creds:
            if not isinstance(c, dict):
                sys.exit("postgres.credentials entries must be objects")

            gid = c.get("group")
            if gid is None:
                sys.exit("postgres credential missing group")

            gid_s = str(gid).strip()
            if not gid_s or not group_token.match(gid_s):
                sys.exit(f"postgres credential group invalid: {gid!r}")

            if gid_s in used_groups:
                sys.exit(f"duplicate postgres group not allowed: {gid_s!r}")
            used_groups.add(gid_s)

            dbn = c.get("database_name") or c.get("db_name")
            if not isinstance(dbn, str) or not ident.match(dbn):
                sys.exit(f"postgres credential database_name invalid: {dbn!r}")

            db_user = c.get("db_user")
            if not isinstance(db_user, str) or not ident.match(db_user):
                sys.exit(f"postgres credential db_user invalid: {db_user!r}")

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
                sys.exit(f"postgres admin db_user invalid: {a_user!r}")

            if a_user in used_db_users:
                sys.exit(f"postgres admin db_user collides with group user: {a_user!r}")

            if not isinstance(a_pw, str) or len(a_pw) < 6:
                sys.exit("postgres admin password too short (min 6)")

        pga = find_app("pgadmin")
        if pga:
            pga_admin = pga.get("admin_credentials") or {}
            if not isinstance(pga_admin, dict) or not pga_admin.get("email") or not pga_admin.get("password"):
                sys.exit("pgadmin.admin_credentials must contain email+password when pgadmin app is present")

            if "@" not in str(pga_admin.get("email")):
                sys.exit("pgadmin admin email invalid")

            if len(str(pga_admin.get("password"))) < 6:
                sys.exit("pgadmin admin password too short (min 6)")

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
                    sys.exit(f"pgadmin credential group invalid: {gid!r}")

                email = c.get("email")
                pw = c.get("password")

                if not isinstance(email, str) or "@" not in email:
                    sys.exit(f"pgadmin credential email invalid: {email!r}")

                if not isinstance(pw, str) or len(pw) < 6:
                    sys.exit(f"pgadmin credential password too short for {email!r} (min 6)")

                if email in seen_emails:
                    sys.exit(f"duplicate pgadmin email not allowed: {email!r}")

                seen_emails.add(email)

        print("generated user_json validated OK")
        PY
      args:
        executable: /bin/bash
      no_log: true

    - name: PostgreSQL Version aus user_json lesen
      shell: |
        set -euo pipefail
        python3 - <<'PY'
        import json

        data = json.load(open("/etc/dozilab/user.json", "r", encoding="utf-8"))
        pgver = data.get("postgres_version")
        if pgver is None:
            pgver = data.get("postgresVersion")

        apps = data.get("applications") or []
        for a in apps:
            if isinstance(a, dict) and str(a.get("name", "")).lower() in ("postgres", "postgresql"):
                if a.get("postgres_version") is not None:
                    pgver = a.get("postgres_version")
                if a.get("postgresVersion") is not None:
                    pgver = a.get("postgresVersion")

        if pgver is None or str(pgver).strip() == "":
            print("")
        else:
            print(int(pgver))
        PY
      args:
        executable: /bin/bash
      register: postgres_version_result
      changed_when: false

    - name: APT Cache aktualisieren
      apt:
        update_cache: true
        cache_valid_time: 3600

    - name: PostgreSQL distro default installieren
      apt:
        name:
          - postgresql
          - postgresql-client
          - python3
        state: present
      when: postgres_version_result.stdout | trim == ""

    - name: PostgreSQL gewünschte Major-Version installieren
      apt:
        name:
          - "postgresql-{{ postgres_version_result.stdout | trim }}"
          - postgresql-client
          - python3
        state: present
      when: postgres_version_result.stdout | trim != ""

    - name: Installierte PostgreSQL Major-Version erkennen
      shell: |
        set -euo pipefail
        pg_lsclusters --no-header | awk 'NR==1{print $1}'
      args:
        executable: /bin/bash
      register: detected_pgver
      changed_when: false

    - name: PostgreSQL Version validieren
      assert:
        that:
          - detected_pgver.stdout | trim | length > 0
        fail_msg: "Konnte installierte PostgreSQL-Version nicht erkennen."

    - name: PostgreSQL nur auf localhost binden
      lineinfile:
        path: "/etc/postgresql/{{ detected_pgver.stdout | trim }}/main/postgresql.conf"
        regexp: "^#?listen_addresses\\s*="
        line: "listen_addresses = '127.0.0.1'"
        backup: true

    - name: pg_hba IPv4 localhost scram sicherstellen
      lineinfile:
        path: "/etc/postgresql/{{ detected_pgver.stdout | trim }}/main/pg_hba.conf"
        line: "host all all 127.0.0.1/32 scram-sha-256"
        state: present

    - name: pg_hba IPv6 localhost scram sicherstellen
      lineinfile:
        path: "/etc/postgresql/{{ detected_pgver.stdout | trim }}/main/pg_hba.conf"
        line: "host all all ::1/128 scram-sha-256"
        state: present

    - name: PostgreSQL aktivieren und starten
      service:
        name: postgresql
        enabled: true
        state: restarted

    - name: Auf PostgreSQL warten
      shell: |
        set -euo pipefail
        for i in $(seq 1 60); do
          if sudo -u postgres psql -d postgres -Atc "SELECT 1" >/dev/null 2>&1; then
            exit 0
          fi
          sleep 1
        done
        exit 1
      args:
        executable: /bin/bash
      changed_when: false

    - name: PostgreSQL Rollen, Datenbanken und Rechte provisionieren
      shell: |
        set -euo pipefail

        python3 - <<'PY'
        import json
        import re
        import subprocess
        import sys

        spec = json.load(open("/etc/dozilab/user.json", "r", encoding="utf-8"))
        apps = spec.get("applications") or []

        def find_app(name: str):
            for a in apps:
                if isinstance(a, dict) and str(a.get("name", "")).lower() == name:
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

            groups[gid] = {
                "dbname": dbname,
                "db_user": db_user,
                "password": pw,
            }

        for gid, info in groups.items():
            grp_role = f"grp_{gid}"
            ensure_group_role(grp_role)
            ensure_db(info["dbname"], grp_role)
            lock_down_db(info["dbname"], grp_role)

        for gid, info in groups.items():
            grp_role = f"grp_{gid}"
            db_user = info["db_user"]
            ensure_login_role(db_user, info["password"])
            grant_role(grp_role, db_user)
            grant_group_defaults(info["dbname"], db_user, grp_role)

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

        print(f"Provisioned postgres groups: {len(groups)}")
        PY
      args:
        executable: /bin/bash
      no_log: true

    - name: Prüfen ob pgAdmin in user_json vorhanden ist
      shell: |
        set -euo pipefail
        python3 - <<'PY'
        import json

        spec = json.load(open("/etc/dozilab/user.json", "r", encoding="utf-8"))
        apps = spec.get("applications") or []

        present = any(
            isinstance(a, dict) and str(a.get("name", "")).lower() == "pgadmin"
            for a in apps
        )

        print("true" if present else "false")
        PY
      args:
        executable: /bin/bash
      register: pgadmin_present_result
      changed_when: false

    - name: pgAdmin Basis-Pakete installieren
      apt:
        name:
          - curl
          - ca-certificates
          - gnupg
          - apache2
          - libapache2-mod-wsgi-py3
          - lsb-release
        state: present
      when: pgadmin_present_result.stdout | trim == "true"

    - name: Ubuntu Codename ermitteln
      command: lsb_release -cs
      register: ubuntu_codename
      changed_when: false
      when: pgadmin_present_result.stdout | trim == "true"

    - name: pgAdmin APT Key und Repository konfigurieren
      shell: |
        set -euo pipefail

        install -d -m 0755 /etc/apt/keyrings

        if [ ! -f /etc/apt/keyrings/pgadmin.gpg ]; then
          curl -fsS https://www.pgadmin.org/static/packages_pgadmin_org.pub \
            | gpg --dearmor -o /etc/apt/keyrings/pgadmin.gpg
        fi

        echo "deb [signed-by=/etc/apt/keyrings/pgadmin.gpg] https://ftp.postgresql.org/pub/pgadmin/pgadmin4/apt/{{ ubuntu_codename.stdout | trim }} pgadmin4 main" \
          > /etc/apt/sources.list.d/pgadmin4.list
      args:
        executable: /bin/bash
      when: pgadmin_present_result.stdout | trim == "true"

    - name: APT Cache nach pgAdmin Repository aktualisieren
      apt:
        update_cache: true
      when: pgadmin_present_result.stdout | trim == "true"

    - name: pgAdmin Web installieren
      apt:
        name: pgadmin4-web
        state: present
      when: pgadmin_present_result.stdout | trim == "true"

    - name: pgAdmin Admin Credentials schreiben
      shell: |
        set -euo pipefail

        python3 - <<'PY'
        import json
        import shlex
        import sys

        spec = json.load(open("/etc/dozilab/user.json", "r", encoding="utf-8"))
        apps = spec.get("applications") or []

        def get_app(name):
            for a in apps:
                if isinstance(a, dict) and str(a.get("name", "")).lower() == name:
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

        with open("/etc/default/pgadmin4", "w", encoding="utf-8") as f:
            print(f"PGADMIN_SETUP_EMAIL={shlex.quote(email)}", file=f)
            print(f"PGADMIN_SETUP_PASSWORD={shlex.quote(pw)}", file=f)

        print("pgAdmin admin email:", email)
        PY

        chmod 600 /etc/default/pgadmin4
      args:
        executable: /bin/bash
      no_log: true
      when: pgadmin_present_result.stdout | trim == "true"

    - name: pgAdmin Web Setup ausführen
      shell: |
        set -euo pipefail

        rm -f /var/lib/pgadmin/pgadmin4.db
        rm -rf /var/lib/pgadmin/sessions /var/lib/pgadmin/storage
        install -d -m 0750 -o www-data -g www-data /var/lib/pgadmin

        set -a
        . /etc/default/pgadmin4
        set +a

        PGADMIN_SETUP_EMAIL="$PGADMIN_SETUP_EMAIL" \
        PGADMIN_SETUP_PASSWORD="$PGADMIN_SETUP_PASSWORD" \
          /usr/pgadmin4/bin/setup-web.sh --yes

        a2enconf pgadmin4 || true
        systemctl reload apache2 || true
      args:
        executable: /bin/bash
      no_log: true
      when: pgadmin_present_result.stdout | trim == "true"

    - name: pgAdmin User aus user_json anlegen
      shell: |
        set -euo pipefail

        python3 - <<'PY'
        import json
        import subprocess
        import sys

        spec = json.load(open("/etc/dozilab/user.json", "r", encoding="utf-8"))
        apps = spec.get("applications") or []

        def get_app(name):
            for a in apps:
                if isinstance(a, dict) and str(a.get("name", "")).lower() == name:
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

            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            out = (res.stdout or "").strip()
            if res.returncode == 0:
                created += 1
                print(f"created pgAdmin user: {email}")
            elif "already exists" in out.lower():
                print(f"pgAdmin user already exists: {email}")
            else:
                print(f"WARNING: failed to create pgAdmin user {email} rc={res.returncode} out={out}")

        print(f"pgAdmin accounts processed: {len(accounts)}, created: {created}")
        PY
      args:
        executable: /bin/bash
      no_log: true
      when: pgadmin_present_result.stdout | trim == "true"

    - name: pgAdmin Server-Eintraege pro User registrieren
      # load-servers importiert eine JSON-Datei mit Server-Definitionen
      # in den Pgadmin-Account eines Users. Passwoerter werden bewusst NICHT
      # mitimportiert — pgAdmin lehnt das aus Sicherheitsgruenden ab.
      # Studenten geben das Postgres-Passwort beim ersten Connect ein.
      # Teacher sieht alle Gruppen-DBs als separate Eintraege.
      shell: |
        set -euo pipefail

        python3 - <<'PY'
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        spec = json.load(open("/etc/dozilab/user.json", "r", encoding="utf-8"))
        apps = spec.get("applications") or []

        def get_app(name):
            for a in apps:
                if isinstance(a, dict) and str(a.get("name", "")).lower() == name:
                    return a
            return None

        pg = get_app("postgres") or get_app("postgresql") or {}
        pga = get_app("pgadmin") or {}

        pg_creds = pg.get("credentials") or []
        pga_creds = pga.get("credentials") or []
        pga_admin = pga.get("admin_credentials") or {}

        # Build group_index -> {db_user, database_name} from postgres creds
        groups_by_gid = {}
        for c in pg_creds:
            gid = str(c.get("group") or "").strip()
            if not gid:
                continue
            groups_by_gid[gid] = {
                "db_user": c.get("db_user"),
                "database_name": c.get("database_name") or c.get("db_name"),
            }

        def load_servers_for_user(email: str, servers: dict) -> None:
            """Run pgAdmin's load-servers CLI for a single user."""
            payload = {"Servers": servers}
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(payload, f)
                tmp_path = f.name
            try:
                # Make sure www-data can read it
                Path(tmp_path).chmod(0o644)
                cmd = [
                    "sudo", "-u", "www-data",
                    "/usr/pgadmin4/venv/bin/python",
                    "/usr/pgadmin4/web/setup.py",
                    "load-servers", tmp_path,
                    "--user", email,
                ]
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                out = (res.stdout or "").strip()
                if res.returncode == 0:
                    print(f"loaded {len(servers)} server(s) for {email}")
                else:
                    print(f"WARNING: load-servers failed for {email} rc={res.returncode} out={out}")
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        # --- Student / group accounts: one server entry per pgAdmin user ---
        for c in pga_creds:
            email = c.get("email")
            gid = str(c.get("group") or "").strip()
            if not email or not gid:
                continue
            group_info = groups_by_gid.get(gid)
            if not group_info:
                print(f"WARNING: no postgres credential for group {gid} — skipping {email}")
                continue
            servers = {
                "1": {
                    "Name": f"Gruppe {gid} DB",
                    "Group": "Servers",
                    "Host": "127.0.0.1",
                    "Port": 5432,
                    "MaintenanceDB": group_info["database_name"],
                    "Username": group_info["db_user"],
                    "SSLMode": "prefer",
                },
            }
            load_servers_for_user(email, servers)

        # --- Teacher: one server entry per group, all with teacher db_user ---
        teacher_email = pga_admin.get("email")
        pg_admin = pg.get("admin_credentials") or {}
        teacher_db_user = pg_admin.get("db_user")
        if teacher_email and teacher_db_user and groups_by_gid:
            teacher_servers = {}
            for i, (gid, info) in enumerate(sorted(groups_by_gid.items()), start=1):
                teacher_servers[str(i)] = {
                    "Name": f"Gruppe {gid} DB (teacher)",
                    "Group": "Gruppen",
                    "Host": "127.0.0.1",
                    "Port": 5432,
                    "MaintenanceDB": info["database_name"],
                    "Username": teacher_db_user,
                    "SSLMode": "prefer",
                }
            load_servers_for_user(teacher_email, teacher_servers)
        PY
      args:
        executable: /bin/bash
      no_log: true
      when: pgadmin_present_result.stdout | trim == "true"

    - name: Apache aktivieren und starten
      service:
        name: apache2
        enabled: true
        state: started
      when: pgadmin_present_result.stdout | trim == "true"

    - name: Auf pgAdmin Login-Seite warten
      # Pollt die pgAdmin-Login-Seite ueber Apache.
      # Erst wenn HTTP 200 zurueck kommt, gilt pgAdmin als wirklich bereit —
      # vorher wuerde der Ready-Marker den Frontend-Status faelschlich auf
      # "bereit" setzen, obwohl Apache noch 503/404 wirft.
      uri:
        url: "http://127.0.0.1/pgadmin4/login"
        method: GET
        status_code: 200
        return_content: false
      register: pgadmin_ready_check
      retries: 120
      delay: 5
      until: pgadmin_ready_check.status == 200
      when: pgadmin_present_result.stdout | trim == "true"

    - name: Ready Marker schreiben
      copy:
        dest: "{{ dozilab_mark_dir }}/ready"
        owner: root
        group: root
        mode: "0644"
        content: "DOZILAB_READY stack={{ dozilab_stack_label }} time={{ ansible_facts.date_time.iso8601 }}\n"

    - name: Fail Marker entfernen falls vorhanden
      file:
        path: "{{ dozilab_mark_dir }}/failed"
        state: absent

    - name: Abschluss anzeigen
      debug:
        msg:
          - "DoziLab PostgreSQL Setup OK"
          - "Stack: {{ dozilab_stack_label }}"
          - "PostgreSQL Version: {{ detected_pgver.stdout | trim }}"
          - "pgAdmin enabled: {{ pgadmin_present_result.stdout | trim }}"'''


# ============================================================================
# Template definitions
# ============================================================================

# Each app describes a template + its version files. Files are loaded in
# the order listed (only matters for the 'order' column in the DB).
APPS = [
    {
        "name": "Multi-User Ubuntu",
        "description": (
            "Ubuntu VM mit mehreren Benutzerkonten, verwaltet durch Ansible. "
            "Pro Gruppe wird ein Linux-Account mit eigenem Arbeitsverzeichnis erstellt."
        ),
        "icon_url": "mdi:server-network",
        "version": "2.1.0",
        "files": [
            {"name": "app.yaml",                "type": FileType.APP_MANIFEST,    "path": "app.yaml",                       "content": MULTIUSER_APP_YAML,         "primary": False},
            {"name": "main.yaml",               "type": FileType.HEAT_TEMPLATE,   "path": "heat/main.yaml",                 "content": MULTIUSER_HEAT_TEMPLATE,    "primary": True},
            {"name": "main.yml",                "type": FileType.ANSIBLE_PLAYBOOK,"path": "playbooks/main.yml",             "content": MULTIUSER_PLAYBOOK,         "primary": False},
            {"name": "bashrc",                  "type": FileType.CONFIG_FILE,     "path": "files/bashrc",                   "content": MULTIUSER_BASHRC,           "primary": False},
            {"name": "motd",                    "type": FileType.CONFIG_FILE,     "path": "files/motd",                     "content": MULTIUSER_MOTD,             "primary": False},
            {"name": "check_student_setup.sh", "type": FileType.SHELL_SCRIPT,    "path": "scripts/check_student_setup.sh", "content": MULTIUSER_CHECK_SCRIPT,     "primary": False},
            {"name": "reset_password.sh",       "type": FileType.SHELL_SCRIPT,    "path": "scripts/reset_password.sh",      "content": MULTIUSER_RESET_SCRIPT,     "primary": False},
        ],
    },
    {
        "name": "PostgreSQL Group DB",
        "description": (
            "Ubuntu VM mit PostgreSQL und optionalem pgAdmin. Jede Gruppe bekommt "
            "eine eigene Datenbank und einen eigenen DB-Rollen-Account. Der Dozent "
            "hat lesenden/schreibenden Zugriff auf alle Gruppen-DBs."
        ),
        "icon_url": "mdi:database",
        "version": "2.0.0",
        "files": [
            {"name": "app.yaml",   "type": FileType.APP_MANIFEST,    "path": "app.yaml",            "content": POSTGRES_APP_YAML,     "primary": False},
            {"name": "main.yaml",  "type": FileType.HEAT_TEMPLATE,   "path": "heat/main.yaml",      "content": POSTGRES_HEAT_TEMPLATE,"primary": True},
            {"name": "main.yml",   "type": FileType.ANSIBLE_PLAYBOOK,"path": "playbooks/main.yml",  "content": POSTGRES_PLAYBOOK,     "primary": False},
        ],
    },
]


# Old template names from earlier iterations. Removed by the seeder so the
# UI doesn't show stale entries. Add new entries here if you rename a template.
_LEGACY_TEMPLATE_NAMES = [
    "Ansible Multi-User Ubuntu",
    "Ansible PostgreSQL Group DB",
    "PostgreSQL Group Database",
]


def create_lecturer_user(db: Session) -> User:
    """Create or get mock development user."""
    existing_user = db.query(User).filter(User.external_id == "40a38818-552d-4ee0-a3fd-a2a1c434a862").first()
    if existing_user:
        return existing_user

    user = User(
        id="5c1c8363-ff6a-4d7f-946a-0221aaf21fb5",
        external_id="40a38818-552d-4ee0-a3fd-a2a1c434a862",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"Created mock user with external_id: {user.external_id}")
    return user


def _delete_legacy_templates(db: Session) -> None:
    """Delete templates from earlier iterations whose names we've since changed.

    Cascades via the ORM relationships: template -> versions -> files. If a
    legacy template has deployments hanging off it the DELETE will fail with
    a FK violation — that's intentional, you'll need to remove those first.
    """
    removed = 0
    for name in _LEGACY_TEMPLATE_NAMES:
        existing = db.query(Template).filter(Template.name == name).all()
        for t in existing:
            try:
                db.delete(t)
                db.commit()
                removed += 1
                logger.info(f"Removed legacy template: {name} (id={t.id})")
            except Exception as e:
                db.rollback()
                logger.warning(
                    f"Could not remove legacy template {name!r} (id={t.id}): {e}. "
                    "Likely has deployments referencing it — delete those first."
                )
    if removed:
        logger.info(f"Removed {removed} legacy template(s).")


def _seed_one_app(db: Session, owner_id: str, app: dict) -> None:
    """Create or update a single app (template + version + files).

    Idempotent: existing template/version is reused; files are upserted
    by file_path so re-running picks up content changes.
    """
    template = db.query(Template).filter(Template.name == app["name"]).first()
    if not template:
        template = Template(
            owner_id=owner_id,
            name=app["name"],
            description=app["description"],
            repo_url="https://github.com/dozilab/appstore-templates",
            icon_url=app["icon_url"],
            visibility=TemplateVisibility.PUBLIC,
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        logger.info(f"Created template: {template.name} (id={template.id})")
    else:
        logger.info(f"Template exists: {template.name} (id={template.id})")

    version = (
        db.query(TemplateVersion)
        .filter(TemplateVersion.template_id == template.id)
        .order_by(TemplateVersion.created_at.desc())
        .first()
    )
    if not version:
        version = TemplateVersion(
            template_id=template.id,
            version=app["version"],
            git_commit_sha=f"v{app['version']}-{template.name.lower().replace(' ', '-')}",
            is_active=True,
        )
        db.add(version)
        db.commit()
        db.refresh(version)
        logger.info(f"  Created version {version.version} (id={version.id})")
    else:
        logger.info(f"  Version exists: {version.version} (id={version.id})")

    # Upsert files by file_path within the version.
    existing_files = {
        f.file_path: f
        for f in db.query(TemplateVersionFile)
        .filter(TemplateVersionFile.template_version_id == version.id)
        .all()
    }

    for order, file_spec in enumerate(app["files"]):
        content = file_spec["content"].lstrip("\n")  # strip leading newline from our r''' indentation
        existing = existing_files.get(file_spec["path"])
        if existing:
            if existing.content != content:
                existing.content = content
                existing.file_size = len(content.encode())
                logger.info(f"    Updated {file_spec['path']} ({existing.file_size} bytes)")
            continue

        f = TemplateVersionFile(
            template_version_id=version.id,
            file_name=file_spec["name"],
            file_type=file_spec["type"],
            file_path=file_spec["path"],
            content=content,
            file_size=len(content.encode()),
            is_primary=file_spec["primary"],
            order=order,
        )
        db.add(f)
        logger.info(f"    Added   {file_spec['path']} ({f.file_size} bytes)")

    db.commit()


def seed_mock_data(db: Session) -> None:
    """Seed all mock data for development. Idempotent."""
    try:
        logger.info("Starting mock data seeding...")

        user = create_lecturer_user(db)
        logger.info(f"User ready: {user.id} (external_id: {user.external_id})")

        _delete_legacy_templates(db)

        for app in APPS:
            _seed_one_app(db, user.id, app)

        logger.info("Mock data seeding completed successfully!")

    except Exception as e:
        logger.error(f"Failed to seed mock data: {e}", exc_info=True)
        db.rollback()
        raise
