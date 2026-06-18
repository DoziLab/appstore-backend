# OpenStack Projects API - Bruno Collection

## Setup

1. **Select Environment:**
   - `local` - Local development environment
   - `production` - Production environment

2. **Configure Secrets:**
   All sensitive credentials are stored as secret variables. Set these in Bruno:
   - `username` - Keycloak user email
   - `password` - Keycloak user password
   - `openstack_username` 
   - `openstack_password` 
   - `openstack_project_id` - **Keystone tenant UUID** from your `clouds.yaml` (the OpenStack-side project id)
   - `openstack_project_name` 
   - `openstack_auth_url`
   - `openstack_user_domain_name`
   - `openstack_region_name`
   - `openstack_project_local_id` - **Local DB primary key** of your OpenStack project row (from `GET /openstack-projects`). Used by all Deployment requests as the `openstack_project_id` query parameter / body field. NOT the same as `openstack_project_id` above — the backend tracks both.

   **These secrets will NOT be committed to Git** - Bruno automatically excludes `vars:secret` from version control.

3. **Login Flow:**
   - Go to `Auth/Keycloak Login`
   - Execute request
   - Access token is automatically saved to `access_token` variable

4. **Use the API:**
   - All requests use `{{access_token}}` automatically
   - `openstack_project_local_id` is automatically saved after creating an OpenStack project

## Environments

### Local Environment (`local.bru`)
- `base_url`: http://localhost:8000
- `keycloak_url`: http://141.72.13.139:8080
- `realm`: Dozilab
- `client_id`: appstore-frontend
- `openstack_auth_url`: https://stack.dhbw.cloud:5000
- Pre-configured OpenStack project details for local testing

### Production Environment (`production.bru`)
- `base_url`: https://appstore-api.dhbw.cloud
- `keycloak_url`: https://keycloak.dhbw.cloud
- `realm`: Dozilab
- `client_id`: appstore-frontend
- OpenStack credentials must be set as secrets

## API Endpoints

### Auth
- **Keycloak Login** - Get access token and save automatically

### OpenStack Projects (Admin/Lecturer only)
- **List Projects** - Get all projects for current user
- **Create Project** - Create new project with encrypted credentials
- **Get Project** - Retrieve project with masked credentials
- **Update Project** - Update project credentials (re-encrypted)
- **Delete Project** - Delete project and credentials
- **Test Student Access** - Verify students are denied access (403)

## Security Features

✅ **Secret Variables** - Credentials stored as secrets (not committed to Git)  
✅ **Automatic Encryption** - Backend encrypts credentials with Fernet  
✅ **Masked Responses** - Password always `********`, username partially masked  
✅ **Role-Based Access** - Only Admin/Lecturer can manage projects  
✅ **Ownership Checks** - Only owner can access/modify their projects  
✅ **Audit Logging** - All access logged with request_id

## Workflow Example

1. Switch to `local` environment
2. Configure secret variables in Bruno (right-click environment → Edit)
3. Run `Auth/Keycloak Login` → saves access_token
4. Run `Create Project` → saves openstack_project_local_id
5. Run `Get Project` → see masked credentials
6. Run `Update Project` → update credentials
7. Run `Delete Project` → cleanup

## Testing Different Roles

Test with different users by changing the `username` and `password` secret variables:
- Admin user: Full access
- Lecturer user: Can manage own projects
- Student user: 403 Forbidden on project endpoints
