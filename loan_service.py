from datetime import date, timedelta

import book_repository
import checks
import fines
import loan_repository
import member_repository
import notifications
import validation
from errors import bad_request

LOAN_DAYS = 14
RENEWAL_DAYS = 14


def amount_owed(loan):
    """What this one loan costs the member right now (0 if nothing is owed)."""
    if loan["returned"] == 0:
        return fines.fine_for(loan["due_date"])
    if loan["fine_paid"] == 0:
        return loan["fine"]
    return 0


def total_owed(loans):
    total = 0
    for loan in loans:
        total += amount_owed(loan)
    return total


def count_open_loans(loans):
    return sum(1 for loan in loans if loan["returned"] == 0)


def current_fine(loan):
    if loan["returned"] == 0:
        return fines.fine_for(loan["due_date"])
    return loan["fine"]


def is_overdue(loan):
    return loan["returned"] == 0 and fines.days_late(loan["due_date"]) > 0


def list_loans(only_overdue):
    loans = loan_repository.list_loans()
    if only_overdue:
        loans = [loan for loan in loans if is_overdue(loan)]
    return loans


def get_loan(loan_id):
    return checks.must_exist(loan_repository.get_loan(loan_id), "loan")


def create_loan(data):
    if not data.get("book_id") or not data.get("member_id"):
        raise bad_request("book_id and member_id are required")
    if data.get("due_date") and not validation.is_valid_date(data["due_date"]):
        raise bad_request("invalid due_date")

    book = checks.must_exist(book_repository.get_book(data["book_id"]), "book")
    member = checks.must_exist(member_repository.get_member(data["member_id"]), "member")
    checks.book_must_be_available(book)

    member_loans = loan_repository.list_loans_for_member(data["member_id"])
    checks.member_must_have_no_unpaid_fines(total_owed(member_loans))
    checks.member_must_be_under_limit(member["type"], count_open_loans(member_loans))

    today = date.today()
    due_date = data.get("due_date") or (today + timedelta(days=LOAN_DAYS)).isoformat()
    loan = loan_repository.create_loan(data["book_id"], data["member_id"], due_date, today.isoformat())

    notifications.notify_checkout(member["email"], book["title"])
    return loan


def return_book(loan_id):
    loan = get_loan(loan_id)
    checks.loan_must_be_open(loan)

    fine = fines.fine_for(loan["due_date"])
    updated = loan_repository.mark_returned(loan_id, loan["book_id"], fine)

    member = member_repository.get_member(loan["member_id"])
    book = book_repository.get_book(loan["book_id"])
    notifications.notify_return(member["email"], book["title"], fines.money(fine))
    return updated


def renew_loan(loan_id):
    loan = get_loan(loan_id)
    checks.loan_must_be_renewable(loan)

    new_due = (date.fromisoformat(loan["due_date"]) + timedelta(days=RENEWAL_DAYS)).isoformat()
    updated = loan_repository.extend_loan(loan_id, new_due)

    member = member_repository.get_member(loan["member_id"])
    book = book_repository.get_book(loan["book_id"])
    notifications.notify_renewal(member["email"], book["title"])
    return updated


def pay_fine(loan_id):
    loan = get_loan(loan_id)
    checks.fine_must_be_payable(loan)

    updated = loan_repository.mark_fine_paid(loan_id)

    member = member_repository.get_member(loan["member_id"])
    notifications.notify_fine_paid(member["email"], fines.money(loan["fine"]))
    return updated