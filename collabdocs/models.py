from django.db import transaction, IntegrityError
from rest_framework import serializers
 
from .models import (
    User,
    Workspace,
    WorkspaceMember,
    Document,
    DocumentVersion,
    Comment,
    Tag,
    AuditLog,
)
 
 
# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, min_length=8)
 
    class Meta:
        model = User
        fields = ["id", "username", "email", "bio", "password", "created_at"]
        read_only_fields = ["id", "created_at"]
 
    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user
 
 
class UserMiniSerializer(serializers.ModelSerializer):
    """Lightweight user payload for nested representations."""
    class Meta:
        model = User
        fields = ["id", "username", "email"]
 
 
# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------
class TagSerializer(serializers.ModelSerializer):
    document_count = serializers.SerializerMethodField()
 
    class Meta:
        model = Tag
        fields = ["id", "name", "document_count", "created_at"]
        read_only_fields = ["id", "created_at"]
 
    def get_document_count(self, obj):
        # When the viewset annotates `doc_count`, prefer that to avoid N+1.
        return getattr(obj, "doc_count", obj.documents.count())
 
    # ---- Custom validation #1 ------------------------------------------------
    def validate_name(self, value):
        value = value.strip().lower()
        if not value:
            raise serializers.ValidationError("Tag name cannot be blank.")
        if len(value) < 2:
            raise serializers.ValidationError("Tag name must be at least 2 characters.")
        if not all(c.isalnum() or c in "-_" for c in value):
            raise serializers.ValidationError(
                "Tag name may only contain letters, digits, '-' or '_'."
            )
        return value
 
 
# ---------------------------------------------------------------------------
# WorkspaceMember
# ---------------------------------------------------------------------------
class WorkspaceMemberSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True)
 
    class Meta:
        model = WorkspaceMember
        fields = ["id", "workspace", "user", "user_id", "role", "joined_at"]
        read_only_fields = ["id", "joined_at"]
 
    def create(self, validated_data):
        user_id = validated_data.pop("user_id")
        try:
            return WorkspaceMember.objects.create(user_id=user_id, **validated_data)
        except IntegrityError:
            # Hits the (workspace, user) UniqueConstraint
            raise serializers.ValidationError(
                {"detail": "User is already a member of this workspace."},
                code=409,
            )
 
 
# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
class WorkspaceSerializer(serializers.ModelSerializer):
    owner = UserMiniSerializer(read_only=True)
    member_count = serializers.SerializerMethodField()
    document_count = serializers.SerializerMethodField()
 
    class Meta:
        model = Workspace
        fields = [
            "id", "name", "description", "owner",
            "is_active", "member_count", "document_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "owner", "created_at", "updated_at"]
 
    def get_member_count(self, obj):
        return getattr(obj, "members_count", obj.members.count())
 
    def get_document_count(self, obj):
        return getattr(obj, "documents_count", obj.documents.count())
 
    # ---- Custom validation #2 ------------------------------------------------
    def validate_name(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError(
                "Workspace name must be at least 3 characters."
            )
        return value
 
    def create(self, validated_data):
        """
        Atomic: create workspace + add owner as admin member + audit log.
        """
        request = self.context["request"]
        owner = request.user
 
        with transaction.atomic():
            workspace = Workspace.objects.create(owner=owner, **validated_data)
            WorkspaceMember.objects.create(
                workspace=workspace,
                user=owner,
                role=WorkspaceMember.Role.ADMIN,
            )
            AuditLog.objects.create(
                actor=owner,
                action="created",
                model_name="Workspace",
                object_id=workspace.id,
            )
        return workspace
 
 
# ---------------------------------------------------------------------------
# DocumentVersion
# ---------------------------------------------------------------------------
class DocumentVersionSerializer(serializers.ModelSerializer):
    edited_by = UserMiniSerializer(read_only=True)
 
    class Meta:
        model = DocumentVersion
        fields = [
            "id", "document", "version_number",
            "content_snapshot", "edited_by", "created_at",
        ]
        read_only_fields = fields  # versions are written by the system, not the API
 
 
# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
class DocumentSerializer(serializers.ModelSerializer):
    created_by = UserMiniSerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, write_only=True, required=False
    )
    versions_count = serializers.SerializerMethodField()
    latest_version = serializers.SerializerMethodField()
 
    class Meta:
        model = Document
        fields = [
            "id", "workspace", "title", "content", "status",
            "created_by", "tags", "tag_ids",
            "versions_count", "latest_version",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]
 
    def get_versions_count(self, obj):
        return getattr(obj, "v_count", obj.versions.count())
 
    def get_latest_version(self, obj):
        v = obj.versions.order_by("-version_number").first()
        return v.version_number if v else 0
 
    # ---- Custom validation #3 ------------------------------------------------
    def validate_title(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError(
                "Document title must be at least 3 characters."
            )
        if len(value) > 200:
            raise serializers.ValidationError(
                "Document title cannot exceed 200 characters."
            )
        return value
 
    def validate(self, attrs):
        """Cross-field check: the user must belong to the workspace."""
        request = self.context.get("request")
        workspace = attrs.get("workspace") or getattr(self.instance, "workspace", None)
        if request and workspace and not WorkspaceMember.objects.filter(
            workspace=workspace, user=request.user
        ).exists():
            raise serializers.ValidationError(
                "You are not a member of this workspace."
            )
        return attrs
 
    # ---- Transactional create + version snapshot -----------------------------
    def create(self, validated_data):
        tags = validated_data.pop("tag_ids", [])
        request = self.context["request"]
 
        with transaction.atomic():
            document = Document.objects.create(
                created_by=request.user, **validated_data
            )
            if tags:
                document.tags.set(tags)
 
            # version_number computed inside the atomic block
            DocumentVersion.objects.create(
                document=document,
                version_number=document.versions.count() + 1,
                content_snapshot=document.content,
                edited_by=request.user,
            )
            # NB: AuditLog for Document is written by the post_save signal.
        return document
 
    def update(self, instance, validated_data):
        tags = validated_data.pop("tag_ids", None)
        request = self.context["request"]
 
        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)
            instance.save()
 
            if tags is not None:
                instance.tags.set(tags)
 
            DocumentVersion.objects.create(
                document=instance,
                version_number=instance.versions.count() + 1,
                content_snapshot=instance.content,
                edited_by=request.user,
            )
        return instance
 
 
# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------
class CommentSerializer(serializers.ModelSerializer):
    author = UserMiniSerializer(read_only=True)
    reply_count = serializers.SerializerMethodField()
 
    class Meta:
        model = Comment
        fields = [
            "id", "document", "author", "body",
            "parent", "reply_count", "created_at",
        ]
        read_only_fields = ["id", "author", "created_at"]
 
    def get_reply_count(self, obj):
        return getattr(obj, "r_count", obj.replies.count())
 
    # ---- Custom validation #4 ------------------------------------------------
    def validate(self, attrs):
        parent = attrs.get("parent")
        document = attrs.get("document")
        if parent and document and parent.document_id != document.id:
            raise serializers.ValidationError(
                "Reply must belong to the same document as its parent comment."
            )
        body = attrs.get("body", "").strip()
        if not body:
            raise serializers.ValidationError({"body": "Comment body cannot be empty."})
        return attrs
 
    def create(self, validated_data):
        request = self.context["request"]
        return Comment.objects.create(author=request.user, **validated_data)
 
 
# ---------------------------------------------------------------------------
# AuditLog (read-only)
# ---------------------------------------------------------------------------
class AuditLogSerializer(serializers.ModelSerializer):
    actor = UserMiniSerializer(read_only=True)
 
    class Meta:
        model = AuditLog
        fields = ["id", "actor", "action", "model_name", "object_id", "timestamp"]
        read_only_fields = fields
