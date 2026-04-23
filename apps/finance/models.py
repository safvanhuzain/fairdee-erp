from django.conf import settings
from django.db import models

# ERPNext Account DocType account_type options (see erpnext/accounts/doctype/account/account.json).
_ACCOUNT_TYPE_LINES = """
Accumulated Depreciation
Asset Received But Not Billed
Bank
Cash
Chargeable
Capital Work in Progress
Cost of Goods Sold
Current Asset
Current Liability
Depreciation
Direct Expense
Direct Income
Equity
Expense Account
Expenses Included In Asset Valuation
Expenses Included In Valuation
Fixed Asset
Income Account
Indirect Expense
Indirect Income
Liability
Payable
Receivable
Round Off
Round Off for Opening
Stock
Stock Adjustment
Stock Received But Not Billed
Service Received But Not Billed
Tax
Temporary
""".strip().splitlines()


class Account(models.Model):
    """
    Chart of accounts row aligned with ERPNext Account DocType
    (field names and semantics follow account.json where possible).
    """

    allow_bulk_upload = True
    allow_tree_view = True

    class RootType(models.TextChoices):
        ASSET = 'Asset', 'Asset'
        LIABILITY = 'Liability', 'Liability'
        INCOME = 'Income', 'Income'
        EXPENSE = 'Expense', 'Expense'
        EQUITY = 'Equity', 'Equity'

    class ReportType(models.TextChoices):
        BALANCE_SHEET = 'Balance Sheet', 'Balance Sheet'
        PROFIT_AND_LOSS = 'Profit and Loss', 'Profit and Loss'

    class BalanceMustBe(models.TextChoices):
        DEBIT = 'Debit', 'Debit'
        CREDIT = 'Credit', 'Credit'

    class FreezeAccount(models.TextChoices):
        NO = 'No', 'No'
        YES = 'Yes', 'Yes'

    ACCOUNT_TYPE_CHOICES = [('', '—')] + [(line, line) for line in _ACCOUNT_TYPE_LINES if line.strip()]

    account_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=64, blank=True, db_index=True)
    is_group = models.BooleanField(default=False)
    company = models.ForeignKey(
        'core.Company',
        on_delete=models.PROTECT,
        related_name='accounts',
    )
    root_type = models.CharField(
        max_length=16,
        choices=RootType.choices,
        blank=True,
    )
    report_type = models.CharField(
        max_length=32,
        choices=ReportType.choices,
        blank=True,
    )
    account_currency = models.ForeignKey(
        'core.Currency',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='accounts',
    )
    parent_account = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='child_accounts',
    )
    account_type = models.CharField(
        max_length=64,
        choices=ACCOUNT_TYPE_CHOICES,
        blank=True,
    )
    tax_rate = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    freeze_account = models.CharField(
        max_length=3,
        choices=FreezeAccount.choices,
        default=FreezeAccount.NO,
    )
    balance_must_be = models.CharField(
        max_length=8,
        choices=BalanceMustBe.choices,
        blank=True,
    )
    lft = models.PositiveIntegerField(default=0, db_index=True)
    rgt = models.PositiveIntegerField(default=0, db_index=True)
    old_parent = models.CharField(max_length=255, blank=True)
    include_in_gross = models.BooleanField(default=False)
    disabled = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company', 'account_number', 'account_name']
        verbose_name_plural = 'accounts'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'account_name'],
                name='finance_account_company_account_name_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'parent_account']),
        ]

    def __str__(self) -> str:
        return f'{self.account_name} ({self.company_id})'


class CostCenter(models.Model):
    """
    Company-scoped cost center dimension with optional tree (nested-set lft/rgt),
    aligned with common ERP cost center / dimension patterns.
    """

    allow_bulk_upload = True
    allow_tree_view = True

    cost_center_name = models.CharField(max_length=255)
    cost_center_number = models.CharField(max_length=64, blank=True, db_index=True)
    parent_cost_center = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='child_cost_centers',
    )
    company = models.ForeignKey(
        'core.Company',
        on_delete=models.PROTECT,
        related_name='cost_centers',
    )
    is_group = models.BooleanField(default=False)
    lft = models.PositiveIntegerField(default=0, db_index=True)
    rgt = models.PositiveIntegerField(default=0, db_index=True)
    old_parent = models.CharField(max_length=255, blank=True)
    disabled = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company', 'cost_center_number', 'cost_center_name']
        verbose_name = 'cost center'
        verbose_name_plural = 'cost centers'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'cost_center_name'],
                name='finance_costcenter_company_cost_center_name_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'parent_cost_center']),
        ]

    def __str__(self) -> str:
        return f'{self.cost_center_name} ({self.company_id})'


class Invoice(models.Model):
    """Sales / purchase invoice shell for v1 (posting rules come later)."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        POSTED = 'posted', 'Posted'
        CANCELLED = 'cancelled', 'Cancelled'

    company = models.ForeignKey(
        'core.Company',
        on_delete=models.PROTECT,
        related_name='invoices',
    )
    number = models.CharField(max_length=64)
    currency = models.CharField(max_length=3, default='USD')
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='invoices_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'number'],
                name='finance_invoice_company_number_uniq',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.number} ({self.company_id})'


class PurchaseInvoice(models.Model):
    """Example purchase-side invoice; same desk list + bulk delete pattern as Invoice."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        POSTED = 'posted', 'Posted'
        CANCELLED = 'cancelled', 'Cancelled'

    company = models.ForeignKey(
        'core.Company',
        on_delete=models.PROTECT,
        related_name='purchase_invoices',
    )
    number = models.CharField(max_length=64)
    currency = models.CharField(max_length=3, default='USD')
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='purchase_invoices_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'number'],
                name='finance_purchaseinvoice_company_number_uniq',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'PI-{self.number} ({self.company_id})'


class JournalEntry(models.Model):
    """GL journal header (lines hold debits/credits)."""

    company = models.ForeignKey(
        'core.Company',
        on_delete=models.PROTECT,
        related_name='journal_entries',
    )
    posting_date = models.DateField()
    reference = models.CharField(max_length=128, blank=True)
    memo = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='journal_entries_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-posting_date', '-id']

    def __str__(self) -> str:
        return f'JE-{self.pk} @ {self.posting_date}'


class JournalLine(models.Model):
    """Single debit/credit line; account as code until chart-of-accounts model exists."""

    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    account_code = models.CharField(max_length=64)
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f'{self.account_code} D{self.debit} C{self.credit}'
