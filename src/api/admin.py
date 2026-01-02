# src/api/admin.py
from fastapi import APIRouter
from src.core.openstack_client import get_openstack_connection

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/projects")
def list_projects():
    """
    List projects with aggregated resource usage
    """
    conn = get_openstack_connection()
    
    # Alle VMs abrufen, die der Benutzer sehen darf
    vms = list(conn.compute.servers())
    
    # Aggregation: pro Projekt Ressourcen zusammenfassen
    projects = {}
    for vm in vms:
        proj_id = vm.project_id
        if proj_id not in projects:
            projects[proj_id] = {
                "project_id": proj_id,
                "project_name": vm.project_id,  # Fallback, da kein Name ohne Admin
                "vms": [],
                "vcpus": 0,
                "ram": 0,
                "storage": 0,
            }
        flavor = conn.compute.get_flavor(vm.flavor["id"])
        projects[proj_id]["vms"].append(vm.name)
        projects[proj_id]["vcpus"] += flavor.vcpus
        projects[proj_id]["ram"] += flavor.ram
        projects[proj_id]["storage"] += flavor.disk
    
    # Optional: in Liste umwandeln
    return list(projects.values())
