from openstack import connection
from datetime import datetime, timezone

class OpenStackService:
    def __init__(self):
        # Verbindung zu OpenStack herstellen (Admin-Credentials)
        self.conn = connection.Connection(
            auth_url="https://openstack.example.com:5000/v3",
            project_name="admin",
            username="admin",
            password="SECRET_PASSWORD",
            user_domain_id="default",
            project_domain_id="default"
        )

    def list_projects_with_resources(self):
        """Gibt alle Projekte mit Deployments & Ressourcen zurück."""
        projects_info = []

        # Alle Projekte abrufen
        for project in self.conn.identity.projects():
            # Alle VMs/Server für dieses Projekt abrufen
            servers = list(self.conn.compute.servers(all_tenants=True, project_id=project.id))
            
            # Ressourcen summieren
            total_vcpus = sum(s.flavor["vcpus"] for s in servers)
            total_ram = sum(s.flavor["ram"] for s in servers)
            total_storage = sum(s.flavor["disk"] for s in servers)

            # Letzte Aktivität ermitteln (letzte VM-Erstellung oder Update)
            letzte_aktivitaet = None
            if servers:
                letzte_aktivitaet = max(
                    s.created_at for s in servers
                )
                letzte_aktivitaet = datetime.fromisoformat(letzte_aktivitaet.replace("Z", "+00:00"))

            # Status: z.B. aktiv, inaktiv, warnung
            status = "aktiv" if servers else "inaktiv"

            projects_info.append({
                "dozent": project.name,
                "email": project.description or "N/A",  # E-Mail ggf. im OpenStack-Projekt gespeichert
                "aktiveDeployments": len(servers),
                "vCPUs": total_vcpus,
                "RAM": total_ram,
                "Storage": total_storage,
                "VMs": len(servers),
                "letzteAktivitaet": letzte_aktivitaet.isoformat() if letzte_aktivitaet else None,
                "status": status
            })

        return projects_info
