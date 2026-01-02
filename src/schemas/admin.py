from pydantic import BaseModel
from typing import Optional

class ProjectResource(BaseModel):
    dozent: str
    email: str
    aktiveDeployments: int
    vCPUs: int
    RAM: int
    Storage: int
    VMs: int
    letzteAktivitaet: Optional[str]
    status: str
