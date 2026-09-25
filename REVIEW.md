## Issue 1 — SQL injection in task search

- **File:** `backend/projects/views.py`, lines 112–121 (`TaskListCreateView.get`, search branch)
- **Category:** Security
- **Severity:** Critical

### Description

The `q` search parameter is interpolated directly into a raw SQL string with f-strings and run via `connection.cursor()`:

```python
sql = (
    f"SELECT id, ... FROM tasks "
    f"WHERE project_id = '{project_id}' "
    f"AND (title ILIKE '%{q}%' OR description ILIKE '%{q}%') "
    f"ORDER BY position ASC"
)
cursor.execute(sql)
```

Any authenticated project member can read arbitrary data from the database, and `psycopg2` accepts stacked statements, so writes and deletes are possible too. A single request can compromise the confidentiality and integrity of the whole database.

### Reproduction (actual execution against the running app)

Logged in as `meera@taskboard.dev` (admin on "Q3 Launch"). The payload forces the `WHERE` clause true:

```bash
curl "http://localhost:8000/api/projects/74de7364-1457-48fd-a3ce-599181292b2b/tasks?q=x%27%20OR%20%27x%25%27%3D%27x" \
  -H "Authorization: Bearer <token>"
```

Response (all 7 tasks returned; `q` matches none of their titles):

```json
{"tasks": [{"id": "4f11720c-d0f1-4f22-acdd-bcf5fa0dde19", "title": "Finalize launch date with marketing", ...},
           {"id": "…", "title": "Draft press release", ...},
           {"id": "…", "title": "Record demo video", ...},
           ... 7 rows total ...]}
```

Control showing this is injection and not just "empty `q` returns all": an impossible condition returns 0 rows.

```bash
curl "http://localhost:8000/api/projects/…/tasks?q=x%25%27%20AND%20%27x%25%27%3D%27y%25" \
  -H "Authorization: Bearer <token>"
# → {"tasks": []}
```

An injected subquery also executes server-side:

```bash
curl "http://localhost:8000/api/projects/…/tasks?q=x%27%20OR%20%28SELECT%20COUNT%28%2A%29%20FROM%20users%29%3E%270%27%20OR%20%27x%25%27%3D%27x" \
  -H "Authorization: Bearer <token>"
# → 7 rows  (the injected (SELECT COUNT(*) FROM users)>'0' ran)
```

### Recommended fix

Delete the raw-SQL branch and use the ORM: `Task.objects.filter(project_id=project_id).filter(Q(title__icontains=q) | Q(description__icontains=q))`. Add regression tests that search still matches on title/description and that the payload `x' OR 'x%'='x` returns zero rows.

---

## Issue 2 — `PATCH /api/tasks/:id` has no membership or role check (IDOR)

- **File:** `backend/projects/views.py`, lines 164–186 (`TaskDetailView.patch`)
- **Category:** Security
- **Severity:** Critical

### Description

`TaskDetailView.patch` fetches the task and applies the update without calling `_get_membership` or checking a role. Any authenticated user, including non-members and read-only viewers, can modify any task in any project by ID. The sibling `delete` (lines 187–202) does check membership and role, so this is an oversight.

### Reproduction (actual execution against the running app)

`lina@example.com` belongs only to "Customer Onboarding Revamp" and has no relationship with "Q3 Launch". She renames a Q3 Launch task:

```bash
curl -X PATCH http://localhost:8000/api/tasks/4f11720c-d0f1-4f22-acdd-bcf5fa0dde19 \
  -H "Authorization: Bearer <lina-token>" -H "Content-Type: application/json" \
  -d '{"title":"HACKED BY NON-MEMBER"}'
```

Response (HTTP 200):

```json
{"task": {"id": "4f11720c-d0f1-4f22-acdd-bcf5fa0dde19", "project_id": "74de7364-…", "title": "HACKED BY NON-MEMBER", "status": "done", ...}}
```

`dev@example.com` is a **viewer** on Q3 Launch (read-only by design) and can edit too:

```bash
curl -X PATCH http://localhost:8000/api/tasks/4f11720c-d0f1-4f22-acdd-bcf5fa0dde19 \
  -H "Authorization: Bearer <dev-token>" -H "Content-Type: application/json" \
  -d '{"status":"done","title":"VIEWER EDITED THIS"}'
# → HTTP 200, title and status changed
```

### Recommended fix

Resolve the task's project membership for `request.user` before mutating: non-members → 403, viewers → 403, admin/member → allowed. Share the membership/role helper with `TaskDetailView.delete`. Add tests for non-member PATCH → 403, viewer PATCH → 403, member PATCH → 200.

---

## Issue 3 — Search codepath bypasses the ORM and serializers

- **File:** `backend/projects/views.py`, lines 112–127 (`TaskListCreateView.get`)
- **Category:** Architecture
- **Severity:** High

### Description

When `q` is present, the view returns raw cursor rows (`dict(zip(columns, row))`) instead of `TaskSerializer` output. The response shape then differs from the non-search path on the same endpoint: snake_case keys, no `assignee` object, and raw `UUID` values that risk a serialization error. The frontend types (`frontend/src/types/index.ts`) expect the serializer shape, and every new `tasks` column must be kept in sync in two places.

### Reproduction (actual execution against the running app)

```bash
curl "http://localhost:8000/api/projects/<proj>/tasks?q=video" -H "Authorization: Bearer <token>"
```

Response, with snake_case keys and no `assignee` object, unlike the default listing:

```json
{
  "tasks": [
    {
      "id": "3b4b9066-…",
      "project_id": "74de7364-…",
      "title": "Record demo video",
      "description": "Detail for: Record demo video",
      "status": "in_progress",
      "assignee_id": "…",
      "created_by_id": "…",
      "position": 2,
      "created_at": "2026-09-23T20:35:41.943828+00:00",
      "updated_at": "…"
    }
  ]
}
```

### Recommended fix

Replace the raw-SQL branch with the ORM (`Q(title__icontains=q) | Q(description__icontains=q)`) routed through `TaskSerializer`, so both branches return one shape. Add a test asserting the search response shape equals the serializer shape. This shares a root cause with Issue 1, so one rewrite fixes both.

---

## Issue 4 — Unbounded, unpaginated task queries

- **Files:** `backend/projects/views.py` lines 65–70 (`ProjectDetailView.get`), 118–127 (search, no `LIMIT`), 129–133 (default listing, no pagination)
- **Category:** Performance
- **Severity:** Medium

### Description

No endpoint limits result size. `ProjectDetailView.get` serializes every task (with nested assignee/created_by users) plus every membership in one response, and the listing and search paths have no `LIMIT`. At the target scale of ~1,000 tasks per project, every board load transfers the whole payload, and latency and memory grow without a ceiling.

### Reproduction

Insert 1,000 tasks into a project and time `GET /api/projects/:id`; the payload grows linearly, and no `limit`/`offset` parameter exists anywhere in `views.py`. No curl sample is included, since this is a scalability issue rather than a correctness bug.

### Recommended fix

Add `?limit=`/`?offset=` (or cursor) pagination to the task endpoints with a sane default (e.g. 200), and cap search results. Stop embedding the full task list in `ProjectDetailView`, or paginate it.

---

## Priority summary

| #   | Issue                                          | Category     | Severity | Evidence                                          |
| --- | ---------------------------------------------- | ------------ | -------- | ------------------------------------------------- |
| 1   | SQL injection in task search                   | Security     | Critical | curl repro (data returned via injected condition) |
| 2   | Missing authz on `PATCH /api/tasks/:id` (IDOR) | Security     | Critical | curl repro (HTTP 200 for non-member and viewer)   |
| 3   | Search path bypasses ORM/serializers           | Architecture | High     | curl repro (divergent response shape)             |
| 4   | Unbounded, unpaginated task queries            | Performance  | Medium   | code inspection                                   |
