```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI Entrypoint (Startet die API)
│   ├── celery_app.py          # Celery Konfiguration & Instanz
│   │
│   ├── api/                   # API-Endpunkte (Routes)
│   │   ├── auth.py          # Login / User
│   │   ├── deployments.py   # Stacks starten/stoppen
│   │
│   ├── core/                  # Globale Config & Security
│   │   ├── config.py          # Environment Variablen (Pydantic Settings)
│   │   ├── security.py        # Fernet Verschlüsselung & Token Logic
│   │   └── database.py        # DB Session Management
│   │
│   ├── models/                # Datenbank-Tabellen (SQLModel)
│   │   ├── user.py            # User & Credentials (Verschlüsselt)
│   │   ├── catalog.py         # CatalogItem, TemplateVersion
│   │   └── deployment.py      # Deployment Status, Logs
│   │
│   ├── schemas/               # Pydantic Modelle (Request/Response Validation)
│   │   ├── template.py        # Validierung für Uploads
│   │   └── deployment.py      # Input-Schema für "Deploy App"
│   │
│   ├── services/              # Die Geschäftslogik (Das "Gehirn")
│   │   ├── openstack_client.py # Wrapper für python-openstackclient
│   │   ├── git_service.py     # Klont Repos, holt File-Content
│   │   └── template_parser.py # YAML-Validierung & 'get_file' Resolver
│   │
│   └── tasks/                 # Asynchrone Jobs (Celery)
│       ├── __init__.py
│       ├── deploy_tasks.py    # Logik für "Heat Stack Create"
│       └── sync_tasks.py      # Logik für "Git Sync" & "Validierung"
│
├── alembic/                   # DB Migrationen (wie Git für DB-Struktur)
├── tests/                     # Pytest Tests
├── .env                       # Secrets (Nicht ins Git!)
├── docker-compose.yml         # Startet API, Worker, Redis, Postgres
├── Dockerfile
├── pyproject.toml             # Dependencies (Poetry) oder requirements.txt
└── README.md

```