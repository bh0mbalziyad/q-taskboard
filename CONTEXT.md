# Taskboard

A project management app where teams track tasks on a board, per project.

## Language

**Project**:
A workspace that owns Tasks and has Members. Created by its owner, who becomes an admin.

**Member**:
A user with a Membership on a Project. Everyone with access to a Project is a Member, whatever their role. Use "non-member" for users without a Membership.

**Role**:
A Member's permission level on one Project: `admin`, `member`, or `viewer`. Roles are per Project, and are read at request time.
_Avoid_: "permission", "access level"

**Editor**:
A Member whose Role is `admin` or `member`, and so can change Tasks and post Comments. Viewers are read-only.
_Avoid_: using "member" alone to mean this; it is ambiguous with Member above and with the `member` Role.

**Task**:
A unit of work on a Project, with a status, an optional assignee, and a Comment thread.

**Comment**:
A message posted by an Editor on a Task. Comments form a chronological thread, shown oldest first, with author, body, and time posted. Comments are **append-only**: once posted, they cannot be edited or deleted by anyone, including admins. The team treats them as part of the engagement audit trail.
_Avoid_: "note", "reply", "message"

**Thread**:
The ordered set of Comments on one Task. It is part of the Task: deleting the Task deletes its Thread, but deleting an author's account does not delete their Comments.

## Relationships

- A **Project** has many **Members** (each with one **Role**) and many **Tasks**
- A **Task** belongs to one **Project** and has one **Thread**
- A **Thread** holds many **Comments**, each written by one **Member** at the time of posting
- Authorization for a **Comment** is derived from the caller's **Role** on the **Task**'s **Project**

## Flagged ambiguities

- "member" is used for both any Project participant and the middle Role. Say **Member** for the participant, and **Editor** when you mean admin-or-member.
