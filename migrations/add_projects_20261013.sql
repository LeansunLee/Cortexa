-- Approved project-management additive migration. Execute in one transaction.
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE TABLE t_projects (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES t_workspaces(id),
 title varchar(200) NOT NULL, goal varchar(2000) NOT NULL, scope varchar(4000) NOT NULL DEFAULT '',
 owner_id uuid NOT NULL REFERENCES t_users(id), creator_id uuid NOT NULL REFERENCES t_users(id),
 status varchar(16) NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','active','completed','archived')),
 due_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(workspace_id,id)
);
CREATE INDEX ix_t_projects_workspace_id ON t_projects(workspace_id);
CREATE INDEX ix_t_projects_status ON t_projects(status);
CREATE TABLE t_project_members (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES t_workspaces(id), project_id uuid NOT NULL,
 user_id uuid NOT NULL REFERENCES t_users(id),role varchar(16) NOT NULL DEFAULT 'member',
 UNIQUE(project_id,user_id), FOREIGN KEY(workspace_id,project_id) REFERENCES t_projects(workspace_id,id)
);
CREATE TABLE t_project_activities (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES t_workspaces(id),project_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES t_users(id),action varchar(32) NOT NULL,data_json json NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(),FOREIGN KEY(workspace_id,project_id) REFERENCES t_projects(workspace_id,id)
);
ALTER TABLE t_works ADD COLUMN project_id uuid;
ALTER TABLE t_works ADD CONSTRAINT fk_work_project_workspace FOREIGN KEY(workspace_id,project_id) REFERENCES t_projects(workspace_id,id);
CREATE INDEX ix_t_works_project_id ON t_works(project_id);
COMMIT;
