# 0001: Comments are append-only

## Context

Tasks have a comment thread. Comments are a record of who said what and when. Letting authors (or admins) edit or delete them would let the history be rewritten, and would need extra rules about who may change whose comments.

## Decision

Comments are append-only. The API exposes only list (GET) and create (POST) on `/api/tasks/<task_id>/comments`. There is no detail route and no PATCH, PUT or DELETE handler, so those methods return 405 for every role, including the project owner. Author and `created_at` are set by the server. Comments are not registered in the Django admin.

## Consequences

- The thread is a trustworthy history; no per-role edit/delete permission logic is needed.
- Mistakes cannot be corrected in place; users post a follow-up comment.
- Comments are removed only by cascade (task deleted) and keep existing if the author account is deleted (author set to null).
- Moderation or edit features would need a new ADR and a deliberate schema/API change.
