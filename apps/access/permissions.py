"""
Helpers for enforcing company scope and Django permissions in views/APIs (v1).
"""


def user_must_belong_to_company(user, company_id):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if company_id is None:
        return user.company_id is None
    return user.company_id == company_id
