from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm as DjangoAuthenticationForm
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from apps.core.models import Company

User = get_user_model()


class NoOutputWidget(forms.Widget):
    """Collect values from POST only; real controls are rendered in the desk template."""

    def render(self, name, value, attrs=None, renderer=None):
        return mark_safe('')

    def value_from_datadict(self, data, files, name):
        # Same as SelectMultiple: POST can repeat the same name; QueryDict.get() only returns one value.
        try:
            return data.getlist(name)
        except AttributeError:
            v = data.get(name)
            if v is None:
                return []
            return v if isinstance(v, (list, tuple)) else [v]

    def value_omitted_from_data(self, data, files, name):
        return False


class EmailAuthenticationForm(DjangoAuthenticationForm):
    """Login form: field is still `username` internally, but we use email (see AUTH_USER_MODEL)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Email'
        self.fields['username'].widget.attrs.update(
            {
                'class': 'desk-login-input',
                'placeholder': 'you@company.com',
                'autocomplete': 'email',
            }
        )
        self.fields['password'].widget.attrs.update(
            {
                'class': 'desk-login-input',
                'placeholder': '••••••••',
                'autocomplete': 'current-password',
            }
        )


class DeskUserCreateForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'desk-modal-input', 'autocomplete': 'off'}),
    )
    password1 = forms.CharField(
        label='Password',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'desk-modal-input', 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Password confirmation',
        strip=False,
        widget=forms.PasswordInput(attrs={'class': 'desk-modal-input', 'autocomplete': 'new-password'}),
    )
    groups = forms.ModelMultipleChoiceField(
        label='Groups',
        queryset=Group.objects.order_by('name'),
        required=False,
        widget=NoOutputWidget(),
    )
    user_permissions = forms.ModelMultipleChoiceField(
        label='User permissions',
        queryset=Permission.objects.none(),
        required=False,
        widget=NoOutputWidget(),
    )

    def __init__(self, acting_user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        from apps.desk.registry import permission_queryset_for_user_matrix

        self.fields['user_permissions'].queryset = permission_queryset_for_user_matrix()
        active_companies = Company.objects.filter(is_active=True).order_by('name')
        if acting_user.is_superuser:
            self.fields['company'] = forms.ModelChoiceField(
                label='Company',
                queryset=active_companies,
                required=True,
                empty_label='',
                widget=forms.Select(attrs={'class': 'desk-modal-input'}),
            )
        else:
            cid = getattr(acting_user, 'company_id', None)
            if cid:
                self.fields['company'] = forms.ModelChoiceField(
                    label='Company',
                    queryset=Company.objects.filter(pk=cid),
                    required=True,
                    initial=cid,
                    widget=forms.Select(attrs={'class': 'desk-modal-input'}),
                )

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('A user with this email already exists.')
        return email

    def clean(self):
        data = super().clean()
        p1 = data.get('password1')
        p2 = data.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'The two password fields do not match.')
        email = data.get('email')
        if p1 and email:
            try:
                validate_password(p1, User(email=email))
            except ValidationError as e:
                for msg in e.messages:
                    self.add_error('password1', msg)
        if not self.acting_user.is_superuser and 'company' not in self.fields:
            self.add_error(
                None,
                'Your account must belong to a company before you can create users.',
            )
        return data


class DeskGroupForm(forms.ModelForm):
    """Desk create/edit Group: name + permission matrix (POST via ``NoOutputWidget``)."""

    class Meta:
        model = Group
        fields = ['name', 'permissions']

    permissions = forms.ModelMultipleChoiceField(
        label='Permissions',
        queryset=Permission.objects.none(),
        required=False,
        widget=NoOutputWidget(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.desk.registry import permission_queryset_for_user_matrix

        self.fields['permissions'].queryset = permission_queryset_for_user_matrix()
        self.fields['name'].widget.attrs.setdefault('class', 'desk-modal-input')


class DeskDataImportForm(forms.Form):
    """Desk CSV import: target model (``allow_bulk_upload``), mode, file."""

    content_type = forms.ModelChoiceField(
        label='Model',
        queryset=ContentType.objects.none(),
        widget=forms.Select(attrs={'class': 'desk-modal-select'}),
    )
    mode = forms.ChoiceField(
        label='Import mode',
        widget=forms.Select(attrs={'class': 'desk-modal-select'}),
    )
    attachment = forms.FileField(
        label='Attachment (CSV)',
        help_text='UTF-8 CSV with a header row matching field names. For Google Sheets: File → Download → Comma-separated values (.csv).',
        widget=forms.ClearableFileInput(attrs={'class': 'desk-modal-input'}),
    )

    def __init__(self, acting_user, *args, **kwargs):
        from apps.desk.models import DataImport
        from apps.desk.registry import content_types_for_bulk_upload

        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.fields['content_type'].queryset = content_types_for_bulk_upload()
        self.fields['mode'].choices = DataImport.Mode.choices

        def _label(ct: ContentType) -> str:
            m = ct.model_class()
            if m is None:
                return str(ct)
            v = m._meta.verbose_name.title()
            return f'{ct.app_label}.{m._meta.model_name} — {v}'

        self.fields['content_type'].label_from_instance = _label

        from apps.desk.document_form import _desk_blank_select_empty_labels

        _desk_blank_select_empty_labels(self)

    def clean_content_type(self):
        ct = self.cleaned_data['content_type']
        m = ct.model_class()
        if m is None:
            raise ValidationError('Invalid model.')
        add_perm = f'{m._meta.app_label}.add_{m._meta.model_name}'
        if not self.acting_user.has_perm(add_perm):
            raise ValidationError('You do not have permission to add rows to this model.')
        return ct
