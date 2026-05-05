"""
CollabDocs :- 
post_save signal on Document writes an AuditLog entry on create/update.
Wired up in apps.py via AppConfig.ready().
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Document, AuditLog


@receiver(post_save, sender=Document)
def log_document_change(sender, instance, created, **kwargs):
    """
    instance._state.adding is False here (post_save), so we rely on
    the `created` kwarg which DRF/post_save provides for that purpose.
    """
    AuditLog.objects.create(
        actor=instance.created_by,
        action="created" if created else "updated",
        model_name="Document",
        object_id=instance.id,
    )