from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'users', views.UserViewSet)
router.register(r'workspaces', views.WorkspaceViewSet)
router.register(r'documents', views.DocumentViewSet)
router.register(r'comments', views.CommentViewSet)
router.register(r'tags', views.TagViewSet)
router.register(r'audit-logs', views.AuditLogViewSet)

urlpatterns = router.urls