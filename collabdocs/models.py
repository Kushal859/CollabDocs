"""
CollabDocs :- 
All 8 models with UUID PKs, TextChoices, constraints, and relationships.
"""

import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
 
 
# ---------------------------------------------------------------------------
# 1. User
# ---------------------------------------------------------------------------
class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    bio = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
 
    REQUIRED_FIELDS = ["email"]
 
    def __str__(self):
        return self.username
 
 
# ---------------------------------------------------------------------------
# 2. Workspace
# ---------------------------------------------------------------------------
class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_workspaces",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ["-created_at"]
 
    def __str__(self):
        return self.name
 
 
# ---------------------------------------------------------------------------
# 3. WorkspaceMember
# ---------------------------------------------------------------------------
class WorkspaceMember(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"
 
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VIEWER)
    joined_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="unique_workspace_member",
            )
        ]
 
    def __str__(self):
        return f"{self.user} @ {self.workspace} ({self.role})"
 
 
# ---------------------------------------------------------------------------
# 4. Document
# ---------------------------------------------------------------------------
class Document(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"
 
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="documents"
    )
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    tags = models.ManyToManyField("Tag", related_name="documents", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["created_by"]),
        ]
 
    def __str__(self):
        return self.title
 
 
# ---------------------------------------------------------------------------
# 5. DocumentVersion
# ---------------------------------------------------------------------------
class DocumentVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    content_snapshot = models.TextField()
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="document_edits",
    )
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version_number"],
                name="unique_document_version_number",
            )
        ]
 
    def __str__(self):
        return f"{self.document.title} v{self.version_number}"
 
 
# ---------------------------------------------------------------------------
# 6. Comment (self-referential for threaded replies)
# ---------------------------------------------------------------------------
class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    body = models.TextField()
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["created_at"]
 
    def __str__(self):
        return f"Comment by {self.author} on {self.document}"
 
 
# ---------------------------------------------------------------------------
# 7. Tag (M2M with Document)
# ---------------------------------------------------------------------------
class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["name"]
 
    def __str__(self):
        return self.name
 
 
# ---------------------------------------------------------------------------
# 8. AuditLog
# ---------------------------------------------------------------------------
class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=50)            # 'created', 'updated', 'deleted'
    model_name = models.CharField(max_length=50)        # 'Document', 'Workspace'
    object_id = models.UUIDField()
    timestamp = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["actor"]),
        ]
 
    def __str__(self):
        return f"{self.actor} {self.action} {self.model_name}({self.object_id})"
