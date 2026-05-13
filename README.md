# CollabDocs

Backend API for **CollabDocs** — a Notion/Google-Docs-style collaboration platform where users create workspaces, invite collaborators, write versioned documents, leave threaded comments, and control access with role-based permissions.

API-only. No frontend. Postman is the client.

Built with Django, Django REST Framework, and PostgreSQL.

---

## Tech Stack

- **Python** 3.11+
- **Django** 5.x
- **Django REST Framework**
- **PostgreSQL** 14+
- **python-decouple** for environment variables

---

## Features

- 8 data models with UUID primary keys
- 17 REST API endpoints (CRUD + custom `@action` endpoints)
- Role-based workspace membership (admin / editor / viewer)
- Document versioning — every save creates a new `DocumentVersion` atomically
- Threaded comments via self-referential ForeignKey
- Many-to-many tagging on documents
- Custom request-logging middleware (method, path, status, ms)
- `post_save` signal on `Document` writing to `AuditLog`
- Atomic transactions on workspace creation and document save
- `IntegrityError` → HTTP 409 on duplicate workspace members
- Query optimisation with `select_related`, `Q` objects, `annotate(Count(...))`, and `values_list`

---

## Project Structure

```
CollabDocs/
├── collabdocs/           # main app
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py           # ready() imports signals
│   ├── middleware.py     # request logging middleware
│   ├── models.py         # 8 models
│   ├── serializers.py
│   ├── signals.py        # post_save on Document → AuditLog
│   ├── urls.py
│   └── views.py
├── config/               # project settings
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── .env.example
├── .gitignore
├── manage.py
├── requirements.txt
├── CollabDocs.postman_collection.json
└── README.md
```

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Kushal859/CollabDocs.git
cd CollabDocs
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create the PostgreSQL database

```bash
psql -U postgres
CREATE DATABASE collabdocs;
CREATE USER collabdocs_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE collabdocs TO collabdocs_user;
\q
```

### 5. Configure environment variables

Copy `.env.example` to `.env` and fill in your local values:

```bash
cp .env.example .env
```

`.env` content:

```
SECRET_KEY=your-django-secret-key
DEBUG=True
DB_NAME=collabdocs
DB_USER=collabdocs_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

### 6. Apply migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 7. Create a superuser (optional, for admin access)

```bash
python manage.py createsuperuser
```

### 8. Run the development server

```bash
python manage.py runserver
```

Server runs at `http://127.0.0.1:8000/`.

---

## API Endpoints

All endpoints are namespaced under `/api/`.

### Users
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/users/` | Register a new user |
| GET | `/api/users/{id}/` | Get user details |
| GET | `/api/users/{id}/stats/` | Aggregated stats: docs created, comments made |

### Workspaces
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/workspaces/` | Create workspace (owner auto-added as admin member, atomic) |
| GET | `/api/workspaces/` | List workspaces |
| GET | `/api/workspaces/{id}/` | Retrieve workspace |
| POST | `/api/workspaces/{id}/add_member/` | Add a member (returns 409 on duplicate) |
| GET | `/api/workspaces/{id}/summary/` | Aggregated summary: member count, doc count |

### Documents
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/documents/` | Create document (atomic: doc + first version) |
| GET | `/api/documents/` | List documents (filterable; uses Q for OR search) |
| GET | `/api/documents/{id}/` | Retrieve document |
| PUT | `/api/documents/{id}/` | Update document (atomic: save + new version) |
| GET | `/api/documents/{id}/versions/` | List all versions of a document |
| GET | `/api/documents/{id}/tags/` | List tags on a document |

### Comments
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/comments/` | Create a comment (top-level or reply via `parent`) |
| GET | `/api/comments/` | List comments |

### Tags & Audit Logs
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tags/` | List tags |
| GET | `/api/audit-logs/` | List audit log entries |

---

## Middleware

`collabdocs/middleware.py` defines `RequestLoggingMiddleware`. Registered last in `MIDDLEWARE` in `config/settings.py`. For every request, it prints:

```
[METHOD] /path/ → status_code (XX ms)
```

Example console output during a request:

```
[POST] /api/workspaces/ → 201 (47 ms)
[GET]  /api/workspaces/ → 200 (12 ms)
```

---

## Signals

`collabdocs/signals.py` connects a `post_save` receiver to the `Document` model. Wired via `CollabdocsConfig.ready()` in `apps.py`. On every create or update of a `Document`, an `AuditLog` row is written with:

- `actor` = `instance.created_by`
- `action` = `"created"` if `created` else `"updated"`
- `model_name` = `"Document"`
- `object_id` = `instance.id`

---

## Transactions

Two `transaction.atomic()` blocks guarantee data integrity:

1. **Workspace creation** — creates the `Workspace` and the owner's `WorkspaceMember` row in a single atomic block. If either fails, both roll back.
2. **Document save** — creates/updates the `Document` and writes the new `DocumentVersion` (with `version_number = Document.versions.count() + 1`) inside the same atomic block. The `AuditLog` entry from the signal is part of the same outer transaction.

Duplicate workspace member adds are caught with `try/except IntegrityError` and return HTTP **409 Conflict**.

---

## Postman Collection

A Postman collection covering all 17 endpoints is committed at the repository root as `CollabDocs.postman_collection.json`. Folders: **Users**, **Workspaces**, **Documents**, **Comments**, **Tags**, **Audit Logs**. Sample request bodies are included for all POST and PUT calls.

To use it:

1. Open Postman → **Import** → select `CollabDocs.postman_collection.json`.
2. Set the `{{base_url}}` collection variable to `http://127.0.0.1:8000`.
3. Run requests in this order to get a clean happy-path flow: create user → create workspace → add member → create document → update document → list versions → comment → reply.

---

## Demo Video

Walkthrough (5–10 min) showing atomic rollback, middleware logs, an aggregation endpoint, and the AuditLog being written by the signal:

**🔗 [Loom / Google Drive link goes here]**

---

## Author

**Kushal** — built as part of the Airtribe AI-Software Engineering coursework.
