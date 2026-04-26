"""
CollabDocs :-
ModelViewSets + @action endpoints. Demonstrates:
  - select_related on every nested-data endpoint
  - prefetch_related for M2M (tags) and reverse FKs (versions, comments)
  - Q objects for OR filtering on documents
  - annotate(Count(...)) on Workspace, Tag, Document list
  - values_list for ID-only lookups
  - filter() lookups: gte, lte, in, icontains
  - Explicit DoesNotExist / IntegrityError handling -> 404 / 409
"""
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

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
from .serializers import (
    UserSerializer,
    WorkspaceSerializer,
    WorkspaceMemberSerializer,
    DocumentSerializer,
    DocumentVersionSerializer,
    CommentSerializer,
    TagSerializer,
    AuditLogSerializer,
)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        """GET /users/{id}/stats/ -- counts of workspaces, documents, comments."""
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=404)

        data = User.objects.filter(pk=user.pk).aggregate(
            workspaces=Count("owned_workspaces", distinct=True),
            documents=Count("documents", distinct=True),
            comments=Count("comments", distinct=True),
        )
        return Response({"id": str(user.id), **data})


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------
class WorkspaceViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # annotate counts; select_related the FK; only show workspaces the user belongs to
        member_workspace_ids = WorkspaceMember.objects.filter(
            user=self.request.user
        ).values_list("workspace_id", flat=True)        # values_list use #1

        qs = (
            Workspace.objects
            .filter(id__in=member_workspace_ids)         # __in lookup
            .select_related("owner")
            .annotate(
                members_count=Count("members", distinct=True),
                documents_count=Count("documents", distinct=True),
            )
        )

        # Filtering
        params = self.request.query_params
        if "is_active" in params:
            qs = qs.filter(is_active=params["is_active"].lower() == "true")
        if "search" in params:
            qs = qs.filter(name__icontains=params["search"])  # icontains lookup
        if "created_after" in params:
            qs = qs.filter(created_at__gte=params["created_after"])  # gte lookup
        return qs

    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        """GET/POST /workspaces/{id}/members/"""
        try:
            workspace = Workspace.objects.get(pk=pk)
        except Workspace.DoesNotExist:
            return Response({"detail": "Workspace not found."}, status=404)

        if request.method == "GET":
            members = (
                WorkspaceMember.objects
                .filter(workspace=workspace)
                .select_related("user", "workspace")
            )
            return Response(WorkspaceMemberSerializer(members, many=True).data)

        # POST -- add a member, atomic with audit log, 409 on duplicate
        data = {**request.data, "workspace": workspace.id}
        serializer = WorkspaceMemberSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                member = serializer.save()
                AuditLog.objects.create(
                    actor=request.user,
                    action="added_member",
                    model_name="WorkspaceMember",
                    object_id=member.id,
                )
        except IntegrityError:
            return Response(
                {"detail": "User is already a member of this workspace."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(WorkspaceMemberSerializer(member).data, status=201)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """GET /workspaces/{id}/summary/ -- aggregate stats."""
        try:
            ws = Workspace.objects.get(pk=pk)
        except Workspace.DoesNotExist:
            return Response({"detail": "Workspace not found."}, status=404)

        data = Workspace.objects.filter(pk=ws.pk).aggregate(
            total_members=Count("members", distinct=True),
            total_documents=Count("documents", distinct=True),
            published_documents=Count(
                "documents",
                filter=Q(documents__status=Document.Status.PUBLISHED),
                distinct=True,
            ),
        )
        return Response({"id": str(ws.id), "name": ws.name, **data})


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = (
            Document.objects
            .select_related("workspace", "created_by")
            .prefetch_related("tags", "versions")
            .annotate(v_count=Count("versions", distinct=True))
        )

        params = self.request.query_params

        # OR filter using Q -- search across title and content
        if "q" in params:
            term = params["q"]
            qs = qs.filter(Q(title__icontains=term) | Q(content__icontains=term))

        if "status" in params:
            qs = qs.filter(status__in=params["status"].split(","))  # __in lookup
        if "workspace" in params:
            qs = qs.filter(workspace_id=params["workspace"])
        if "created_after" in params:
            qs = qs.filter(created_at__gte=params["created_after"])
        if "created_before" in params:
            qs = qs.filter(created_at__lte=params["created_before"])  # lte lookup
        if "tag" in params:
            qs = qs.filter(tags__name__icontains=params["tag"])
        return qs

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        """GET /documents/{id}/versions/"""
        try:
            doc = Document.objects.get(pk=pk)
        except Document.DoesNotExist:
            return Response({"detail": "Document not found."}, status=404)

        versions = (
            DocumentVersion.objects
            .filter(document=doc)
            .select_related("edited_by", "document")
        )
        return Response(DocumentVersionSerializer(versions, many=True).data)

    @action(detail=True, methods=["post"])
    def tags(self, request, pk=None):
        """POST /documents/{id}/tags/  body: {"tag_ids": [...]}"""
        doc = get_object_or_404(Document, pk=pk)
        tag_ids = request.data.get("tag_ids", [])
        if not isinstance(tag_ids, list):
            return Response(
                {"detail": "tag_ids must be a list."}, status=400
            )

        # Validate every id exists; return 404 on first miss
        existing = set(
            Tag.objects.filter(id__in=tag_ids).values_list("id", flat=True)
        )                                                    # values_list use #2
        missing = [t for t in tag_ids if str(t) not in {str(x) for x in existing}]
        if missing:
            return Response(
                {"detail": f"Tag(s) not found: {missing}"}, status=404
            )

        with transaction.atomic():
            doc.tags.add(*tag_ids)
            AuditLog.objects.create(
                actor=request.user,
                action="tagged",
                model_name="Document",
                object_id=doc.id,
            )
        return Response(DocumentSerializer(doc).data, status=200)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """GET /documents/stats/ -- aggregate counts by status."""
        data = Document.objects.aggregate(
            total=Count("id"),
            drafts=Count("id", filter=Q(status=Document.Status.DRAFT)),
            published=Count("id", filter=Q(status=Document.Status.PUBLISHED)),
            archived=Count("id", filter=Q(status=Document.Status.ARCHIVED)),
        )
        return Response(data)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
class CommentViewSet(viewsets.ModelViewSet):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = (
            Comment.objects
            .select_related("author", "document", "parent")
            .annotate(r_count=Count("replies", distinct=True))
        )
        params = self.request.query_params
        if "document" in params:
            qs = qs.filter(document_id=params["document"])
        if "top_level" in params and params["top_level"].lower() == "true":
            qs = qs.filter(parent__isnull=True)
        return qs

    @action(detail=True, methods=["get"])
    def replies(self, request, pk=None):
        """GET /comments/{id}/replies/"""
        try:
            parent = Comment.objects.get(pk=pk)
        except Comment.DoesNotExist:
            return Response({"detail": "Comment not found."}, status=404)

        replies = (
            Comment.objects
            .filter(parent=parent)
            .select_related("author", "document")
        )
        return Response(CommentSerializer(replies, many=True).data)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Tag.objects.annotate(doc_count=Count("documents", distinct=True))
        params = self.request.query_params
        if "search" in params:
            qs = qs.filter(name__icontains=params["search"])
        return qs


# ---------------------------------------------------------------------------
# AuditLogs (read-only)
# ---------------------------------------------------------------------------
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        params = self.request.query_params
        if "model_name" in params:
            qs = qs.filter(model_name__iexact=params["model_name"])
        if "action" in params:
            qs = qs.filter(action__in=params["action"].split(","))
        if "since" in params:
            qs = qs.filter(timestamp__gte=params["since"])
        return qs
