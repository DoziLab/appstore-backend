from src.core.openstack_client import get_openstack_connection

# Verbindung zu OpenStack herstellen
conn = get_openstack_connection()

# Liste aller Server (VMs), die du sehen darfst
servers = list(conn.compute.servers())
for s in servers:
    print(f"VM: {s.name}, Projekt-ID: {s.project_id}")
