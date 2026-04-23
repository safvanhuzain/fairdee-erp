from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models


class DataImport(models.Model):
    """
    Desk CSV import job. Target models opt in with ``allow_bulk_upload = True`` on the
    model class (or are listed in ``registry.BULK_UPLOAD_BY_LABEL`` for third-party models).
    """

    class Mode(models.TextChoices):
        INSERT_ONLY = 'insert', 'Insert new only'
        UPSERT = 'upsert', 'Update existing or insert new'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        DONE = 'done', 'Done'
        FAILED = 'failed', 'Failed'

    company = models.ForeignKey(
        'core.Company',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='data_imports',
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name='+',
        help_text='Target model for this CSV.',
    )
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.INSERT_ONLY)
    attachment = models.FileField(upload_to='desk_imports/%Y/%m/')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    rows_created = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_failed = models.PositiveIntegerField(default=0)
    error_report = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='data_imports_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'data import'
        verbose_name_plural = 'data imports'

    def __str__(self) -> str:
        return f'Import #{self.pk} → {self.content_type}' if self.pk else 'Data import'
