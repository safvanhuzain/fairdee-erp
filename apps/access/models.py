from django.contrib.auth.models import Group
from django.db import models


class RoleProfile(models.Model):
    """
    Relational wrapper around Django's Group for named finance roles.
    Permissions are still assigned to the Group (Admin or future UI).
    """

    group = models.OneToOneField(
        Group,
        on_delete=models.CASCADE,
        related_name='finance_role_profile',
    )
    slug = models.SlugField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    company = models.ForeignKey(
        'core.Company',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='role_profiles',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self) -> str:
        return self.slug
