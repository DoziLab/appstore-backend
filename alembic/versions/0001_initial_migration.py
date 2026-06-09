"""Initial migration

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001_initial'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_id'),
    )
    op.create_index('ix_users_external_id', 'users', ['external_id'], unique=True)

    op.create_table(
        'template_categories',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'templates',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('repo_url', sa.String(length=500), nullable=False),
        sa.Column('icon_url', sa.String(length=500), nullable=True),
        sa.Column('visibility', sa.Enum('private', 'public', name='templatevisibility'), nullable=False),
        sa.Column('approval_status', sa.Enum('pending', 'approved', 'rejected', 'deprecated', name='templateapprovalstatus'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'template_versions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('template_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('git_commit_sha', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'template_version_files',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('template_version_id', sa.String(length=36), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_type', sa.Enum(
            'APP_MANIFEST', 'HEAT_TEMPLATE', 'CLOUD_INIT', 'ANSIBLE_PLAYBOOK',
            'HELM_CHART', 'SHELL_SCRIPT', 'CONFIG_FILE', 'OTHER',
            name='filetype',
        ), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['template_version_id'], ['template_versions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('template_version_id', 'file_path', name='uq_template_version_file_path'),
    )

    op.create_table(
        'template_category_assignments',
        sa.Column('template_id', sa.String(length=36), nullable=False),
        sa.Column('template_categories_id', sa.String(length=36), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['template_categories_id'], ['template_categories.id']),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id']),
        sa.PrimaryKeyConstraint('template_id', 'template_categories_id'),
    )

    op.create_table(
        'courses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('keycloak_course_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('keycloak_course_id'),
    )

    op.create_table(
        'course_members',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('course_id', sa.String(length=36), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.Column('left_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'course_groups',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('course_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'group_members',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('group_id', sa.String(length=36), nullable=False),
        sa.Column('course_member_id', sa.String(length=36), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_member_id'], ['course_members.id']),
        sa.ForeignKeyConstraint(['group_id'], ['course_groups.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'openstack_projects',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('owner_user_id', sa.String(length=36), nullable=False),
        sa.Column('openstack_project_id', sa.String(length=255), nullable=False),
        sa.Column('openstack_project_name', sa.String(length=255), nullable=False),
        sa.Column('auth_url', sa.String(length=500), nullable=False),
        sa.Column('username', sa.String(length=500), nullable=False),
        sa.Column('password', sa.String(length=500), nullable=False),
        sa.Column('user_domain_name', sa.String(length=255), nullable=False),
        sa.Column('region_name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_user_id', 'openstack_project_id', name='uq_openstack_project_user'),
    )

    op.create_table(
        'deployments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('template_version_id', sa.String(length=36), nullable=False),
        sa.Column('course_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.Enum(
            'queued', 'creating', 'running', 'restarting', 'deleting', 'failed', 'deleted',
            name='deploymentstatus',
        ), nullable=False),
        sa.Column('openstack_stack_id', sa.String(length=255), nullable=True),
        sa.Column('deployment_parameters', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id']),
        sa.ForeignKeyConstraint(['template_version_id'], ['template_versions.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'deployment_instances',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deployment_id', sa.String(length=36), nullable=False),
        sa.Column('group_id', sa.String(length=36), nullable=True),
        sa.Column('course_member_id', sa.String(length=36), nullable=True),
        sa.Column('vm_name', sa.String(length=255), nullable=True),
        sa.Column('openstack_server_id', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('status', sa.Enum(
            'creating', 'running', 'failed', 'deleted',
            name='deploymentinstancestatus',
        ), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_member_id'], ['course_members.id']),
        sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id']),
        sa.ForeignKeyConstraint(['group_id'], ['course_groups.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'deployment_instance_access',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deployment_instance_id', sa.String(length=36), nullable=False),
        sa.Column('access_type', sa.Enum(
            'ssh', 'web_url', 'guacamole', 'rdp', 'vnc', 'database',
            name='accesstype',
        ), nullable=False),
        sa.Column('connection_url', sa.String(length=500), nullable=True),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('password', sa.Text(), nullable=True),
        sa.Column('ssh_private_key', sa.Text(), nullable=True),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['deployment_instance_id'], ['deployment_instances.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'deployment_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('deployment_id', sa.String(length=36), nullable=False),
        sa.Column('level', sa.Enum('debug', 'info', 'warning', 'error', name='deploymentloglevel'), nullable=False),
        sa.Column('event_type', sa.Enum(
            'deployment_started', 'git_clone', 'template_create', 'stack_create',
            'vm_ready', 'failed', 'deployment_deletion_requested', 'deployment_deleted',
            'ssh_wait', 'ansible_started', 'ansible_task', 'ansible_ok',
            'ansible_failed', 'ansible_completed',
            name='deploymentlogeventtype',
        ), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('request_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('deployment_logs')
    op.drop_table('deployment_instance_access')
    op.drop_table('deployment_instances')
    op.drop_table('deployments')
    op.drop_table('openstack_projects')
    op.drop_table('group_members')
    op.drop_table('course_groups')
    op.drop_table('course_members')
    op.drop_table('courses')
    op.drop_table('template_category_assignments')
    op.drop_table('template_version_files')
    op.drop_table('template_versions')
    op.drop_table('templates')
    op.drop_table('template_categories')
    op.drop_index('ix_users_external_id', table_name='users')
    op.drop_table('users')

    op.execute('DROP TYPE IF EXISTS deploymentlogeventtype')
    op.execute('DROP TYPE IF EXISTS deploymentloglevel')
    op.execute('DROP TYPE IF EXISTS accesstype')
    op.execute('DROP TYPE IF EXISTS deploymentinstancestatus')
    op.execute('DROP TYPE IF EXISTS deploymentstatus')
    op.execute('DROP TYPE IF EXISTS filetype')
    op.execute('DROP TYPE IF EXISTS templateapprovalstatus')
    op.execute('DROP TYPE IF EXISTS templatevisibility')
