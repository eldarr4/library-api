"""Checks: library rules. Each function raises an error if a rule is broken."""
from datetime import date

from errors import conflict, not_found

LOAN_LIMITS = {"student": 3, "staff": 5}
DEFAULT_LOAN_LIMIT = 3
MAX_RENEWALS = 1


def loan_limit_for(member_type):
    return LOAN_LIMITS.get(member_type, DEFAULT_LOAN_LIMIT)


def must_exist(item, name):
    if item is None:
        raise not_found(name + " not found")
    return item


def book_must_be_available(book):
    if book["available"] == 0:
        raise conflict("book is not available")


def book_must_not_be_on_loan(book):
    if book["available"] == 0:
        raise conflict("book is on loan")


def email_must_be_new(existing_member):
    if existing_member is not None:
        raise conflict("email already registered")


def member_must_have_no_unpaid_fines(amount_owed):
    if amount_owed > 0:
        raise conflict("member has unpaid fines")


def member_must_be_under_limit(member_type, open_loans):
    if open_loans >= loan_limit_for(member_type):
        raise conflict("loan limit reached")


def loan_must_be_open(loan):
    if loan["returned"] == 1:
        raise conflict("loan already returned")


def loan_must_be_renewable(loan):
    loan_must_be_open(loan)
    if date.fromisoformat(loan["due_date"]) < date.today():
        raise conflict("overdue loans cannot be renewed")
    if loan["renewals"] >= MAX_RENEWALS:
        raise conflict("loan was already renewed")


def fine_must_be_payable(loan):
    if loan["returned"] == 0:
        raise conflict("return the book before paying")
    if loan["fine"] <= 0 or loan["fine_paid"] == 1:
        raise conflict("no fine to pay")