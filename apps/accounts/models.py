from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        email = self.normalize_email(email)
        user = self.model(email=email, username=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Email-based auth; company FK for relational integrity;
    flexible profile/config in metadata (JSONB on PostgreSQL).
    """

    username = models.CharField(max_length=150, unique=True, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    company = models.ForeignKey(
        'core.Company',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='users',
    )
    metadata = models.JSONField(default=dict, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        self.username = self.email
        super().save(*args, **kwargs)
