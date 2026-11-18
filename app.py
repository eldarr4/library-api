import os
import re
from datetime import date, timedelta
from db import init_db
import book_repository
import member_repository
import loan_repository
import report_repository
from errors import LibraryError, error_response
from fines import money

from flask import Flask, jsonify, request

app = Flask(__name__)
@app.errorhandler(LibraryError)
def handle_library_error(error):
    return error_response(error.message, error.status)

CURRENT_MEMBER = None

# ---------- helpers ----------


def check(value, kind):
    if kind == "email":
        return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(value)) is not None
    elif kind == "isbn":
        digits = str(value).replace("-", "")
        return digits.isdigit() and len(digits) in (10, 13)
    elif kind == "date":
        try:
            date.fromisoformat(str(value))
            return True
        except ValueError:
            return False
    elif kind == "member_type":
        return value in ("student", "staff")
    return False


def notify(kind, title="", send=True):
    if not send:
        return
    if kind == "checkout":
        subject = "Book checked out"
        body = "You checked out " + title
    elif kind == "renew":
        subject = "Loan renewed"
        body = "You renewed " + title
    else:
        subject = "Library notice"
        body = title
    with open("outbox.txt", "a") as f:
        f.write("TO: " + CURRENT_MEMBER[2] + " | SUBJECT: " + subject + " | BODY: " + body + "\n")


# ---------- books ----------

def book_json(book):
    return {"id": book["id"], "title": book["title"], "author": book["author"], "isbn": book["isbn"], "available": bool(book["available"])}


@app.route("/books", methods=["GET"])
def list_books():
    rows = book_repository.list_books(request.args.get("available") == "true")
    result = []
    for r in rows:
        result.append(book_json(r))
    return jsonify(result)


@app.route("/books/<int:book_id>", methods=["GET"])
def get_book(book_id):
    r = book_repository.get_book(book_id)
    if r is None:
        return jsonify({"error": "book not found"}), 404
    return jsonify(book_json(r))


@app.route("/books", methods=["POST"])
def create_book():
    data = request.get_json(silent=True) or {}
    if not data.get("title") or not data.get("author"):
        return jsonify({"error": "title and author are required"}), 400
    if not check(data.get("isbn"), "isbn"):
        return jsonify({"error": "invalid isbn"}), 400
    r = book_repository.create_book(data["title"], data["author"], data["isbn"])
    return jsonify(book_json(r)), 201


@app.route("/books/<int:book_id>", methods=["DELETE"])
def delete_book(book_id):
    r = book_repository.get_book(book_id)
    if r is None:
        return jsonify({"error": "book not found"}), 404
    if r["available"] == 0:
        return jsonify({"error": "book is on loan"}), 409
    book_repository.delete_book(book_id)
    return "", 204


# ---------- members ----------

def member_json(member):
    return {"id": member["id"], "name": member["name"], "email": member["email"], "type": member["type"]}


@app.route("/members", methods=["GET"])
def list_members():
    result = []
    for r in member_repository.list_members():
        result.append(member_json(r))
    return jsonify(result)


@app.route("/members/<int:member_id>", methods=["GET"])
def get_member(member_id):
    r = member_repository.get_member(member_id)
    if r is None:
        return jsonify({"error": "member not found"}), 404
    return jsonify(member_json(r))


@app.route("/members", methods=["POST"])
def create_member():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400
    if not check(data.get("email"), "email"):
        return jsonify({"error": "invalid email"}), 400
    member_type = data.get("type", "student")
    if not check(member_type, "member_type"):
        return jsonify({"error": "type must be student or staff"}), 400
    if member_repository.get_member_by_email(data["email"]) is not None:
        return jsonify({"error": "email already registered"}), 409
    r = member_repository.create_member(data["name"], data["email"], member_type)
    return jsonify(member_json(r)), 201


@app.route("/members/<int:member_id>/loans", methods=["GET"])
def member_loans(member_id):
    m = member_repository.get_member(member_id)
    if m is None:
        return jsonify({"error": "member not found"}), 404
    rows = loan_repository.list_loans_for_member(member_id)
    owed = 0
    open_loans = 0
    loans = []
    for loan in rows:
        if loan["returned"] == 0:
            open_loans += 1
            days_late = (date.today() - date.fromisoformat(loan["due_date"])).days
            if days_late > 0:
                owed += days_late * 0.5
        elif loan["fine_paid"] == 0:
            owed += loan["fine"]
        loans.append(
            {
                "id": loan["id"],
                "book_id": loan["book_id"],
                "due_date": loan["due_date"],
                "returned": bool(loan["returned"]),
                "fine": money(loan["fine"]),
                "fine_paid": bool(loan["fine_paid"]),
            }
        )
    if m["type"] == "staff":
        remaining = 5 - open_loans
    else:
        remaining = 3 - open_loans
    return jsonify({"loans": loans, "total_owed": money(owed), "loans_remaining": remaining})


# ---------- loans ----------

def loan_json(loan, current_fine=None):
    result = {
        "id": loan["id"],
        "book_id": loan["book_id"],
        "member_id": loan["member_id"],
        "due_date": loan["due_date"],
        "returned": bool(loan["returned"]),
        "fine": money(loan["fine"]),
        "fine_paid": bool(loan["fine_paid"]),
        "renewals": loan["renewals"],
        "checked_out": loan["checked_out"],
    }
    if current_fine is not None:
        result["current_fine"] = money(current_fine)
    return result


@app.route("/loans", methods=["GET"])
def list_loans():
    result = []
    for loan in loan_repository.list_loans():
        current_fine = loan["fine"]
        days_late = (date.today() - date.fromisoformat(loan["due_date"])).days
        if loan["returned"] == 0:
            current_fine = max(0, days_late) * 0.50
        if request.args.get("overdue") == "true" and (loan["returned"] == 1 or days_late <= 0):
            continue
        result.append(loan_json(loan, current_fine))
    return jsonify(result)


@app.route("/loans/<int:loan_id>", methods=["GET"])
def get_loan(loan_id):
    loan = loan_repository.get_loan(loan_id)
    if loan is None:
        return jsonify({"error": "loan not found"}), 404
    current_fine = loan["fine"]
    if loan["returned"] == 0:
        days_late = (date.today() - date.fromisoformat(loan["due_date"])).days
        current_fine = max(0, days_late) * 0.50
    return jsonify(loan_json(loan, current_fine))


@app.route("/loans", methods=["POST"])
def create_loan():
    global CURRENT_MEMBER
    data = request.get_json(silent=True) or {}
    if not data.get("book_id") or not data.get("member_id"):
        return jsonify({"error": "book_id and member_id are required"}), 400
    if data.get("due_date") and not check(data["due_date"], "date"):
        return jsonify({"error": "invalid due_date"}), 400

    book = book_repository.get_book(data["book_id"])
    if book is None:
        return jsonify({"error": "book not found"}), 404
    member = member_repository.get_member(data["member_id"])
    if member is None:
        return jsonify({"error": "member not found"}), 404
    if book["available"] == 0:
        return jsonify({"error": "book is not available"}), 409

    rows = loan_repository.list_loans_for_member(data["member_id"])
    owed = 0
    open_loans = 0
    for loan in rows:
        if loan["returned"] == 0:
            open_loans += 1
            days_late = (date.today() - date.fromisoformat(loan["due_date"])).days
            if days_late > 0:
                owed += days_late * 0.5
        elif loan["fine_paid"] == 0:
            owed += loan["fine"]
    if owed > 0:
        return jsonify({"error": "member has unpaid fines"}), 409
    limit = 3
    if member["type"] == "staff":
        limit = 5
    if open_loans >= limit:
        return jsonify({"error": "loan limit reached"}), 409

    today = date.today()
    due_date = data.get("due_date") or (today + timedelta(days=14)).isoformat()
    loan = loan_repository.create_loan(data["book_id"], data["member_id"], due_date, today.isoformat())

    CURRENT_MEMBER = member
    notify("checkout", book["title"])

    return jsonify(loan_json(loan)), 201


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
def return_book(loan_id):
    loan = loan_repository.get_loan(loan_id)
    if loan is None:
        return jsonify({"error": "loan not found"}), 404
    if loan["returned"] == 1:
        return jsonify({"error": "loan already returned"}), 409

    days_late = (date.today() - date.fromisoformat(loan["due_date"])).days
    fine = max(0, days_late) * 0.50
    updated = loan_repository.mark_returned(loan_id, loan["book_id"], fine)
    member = member_repository.get_member(loan["member_id"])
    book = book_repository.get_book(loan["book_id"])

    with open("outbox.txt", "a") as f:
        f.write(
            "TO: " + member["email"] + " | SUBJECT: Book returned | BODY: You returned " + book["title"]
            + ". Fine: $" + str(money(fine)) + "\n"
        )

    return jsonify(loan_json(updated))


@app.route("/loans/<int:loan_id>/renew", methods=["POST"])
def renew_loan(loan_id):
    global CURRENT_MEMBER
    loan = loan_repository.get_loan(loan_id)
    if loan is None:
        return jsonify({"error": "loan not found"}), 404
    if loan["returned"] == 1:
        return jsonify({"error": "loan already returned"}), 409
    if date.fromisoformat(loan["due_date"]) < date.today():
        return jsonify({"error": "overdue loans cannot be renewed"}), 409
    if loan["renewals"] >= 1:
        return jsonify({"error": "loan was already renewed"}), 409

    new_due = (date.fromisoformat(loan["due_date"]) + timedelta(days=14)).isoformat()
    updated = loan_repository.extend_loan(loan_id, new_due)
    CURRENT_MEMBER = member_repository.get_member(loan["member_id"])
    book = book_repository.get_book(loan["book_id"])

    notify("renew", book["title"])

    return jsonify(loan_json(updated))


@app.route("/loans/<int:loan_id>/pay-fine", methods=["POST"])
def pay_fine(loan_id):
    loan = loan_repository.get_loan(loan_id)
    if loan is None:
        return jsonify({"error": "loan not found"}), 404
    if loan["returned"] == 0:
        return jsonify({"error": "return the book before paying"}), 409
    if loan["fine"] <= 0 or loan["fine_paid"] == 1:
        return jsonify({"error": "no fine to pay"}), 409

    updated = loan_repository.mark_fine_paid(loan_id)
    member = member_repository.get_member(loan["member_id"])

    with open("outbox.txt", "a") as f:
        f.write(
            "TO: " + member["email"] + " | SUBJECT: Fine paid | BODY: We received $" + str(money(loan["fine"])) + "\n"
        )

    return jsonify(loan_json(updated))


# ---------- reports ----------

@app.route("/reports/overdue", methods=["GET"])
def report_overdue():
    rows = report_repository.list_open_loans_with_details()
    items = []
    total = 0
    for r in rows:
        days_late = (date.today() - date.fromisoformat(r["due_date"])).days
        if days_late > 0:
            fine = days_late * 0.5
            total += fine
            items.append(
                {"loan_id": r["loan_id"], "title": r["title"], "member": r["member"], "days_late": days_late, "fine": money(fine)}
            )
    return jsonify({"items": items, "total_fines": money(total)})


@app.route("/reports/summary", methods=["GET"])
def report_summary():
    total_books = book_repository.count_books()
    rows = loan_repository.list_loans()
    on_loan = 0
    outstanding = 0
    for loan in rows:
        if loan["returned"] == 0:
            on_loan += 1
            days_late = (date.today() - date.fromisoformat(loan["due_date"])).days
            outstanding += max(0, days_late) * 0.50
        elif loan["fine_paid"] == 0:
            outstanding += loan["fine"]
    return jsonify({"total_books": total_books, "on_loan": on_loan, "fines_outstanding": money(outstanding)})


if not os.path.exists("library.db"):
    init_db()
