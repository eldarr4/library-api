import os
import re
from datetime import date, timedelta
from db import init_db
import book_repository
import member_repository
import loan_repository
import report_repository
import book_service
import loan_service
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
    only_available = request.args.get("available") == "true"
    return jsonify([book_json(b) for b in book_service.list_books(only_available)])


@app.route("/books/<int:book_id>", methods=["GET"])
def get_book(book_id):
    return jsonify(book_json(book_service.get_book(book_id)))


@app.route("/books", methods=["POST"])
def create_book():
    data = request.get_json(silent=True) or {}
    return jsonify(book_json(book_service.create_book(data))), 201


@app.route("/books/<int:book_id>", methods=["DELETE"])
def delete_book(book_id):
    book_service.delete_book(book_id)
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

def loan_json(loan, with_current_fine=False):
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
    if with_current_fine:
        result["current_fine"] = money(loan_service.current_fine(loan))
    return result


@app.route("/loans", methods=["GET"])
def list_loans():
    only_overdue = request.args.get("overdue") == "true"
    return jsonify([loan_json(l, True) for l in loan_service.list_loans(only_overdue)])


@app.route("/loans/<int:loan_id>", methods=["GET"])
def get_loan(loan_id):
    return jsonify(loan_json(loan_service.get_loan(loan_id), True))


@app.route("/loans", methods=["POST"])
def create_loan():
    data = request.get_json(silent=True) or {}
    return jsonify(loan_json(loan_service.create_loan(data))), 201


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
def return_book(loan_id):
    return jsonify(loan_json(loan_service.return_book(loan_id)))


@app.route("/loans/<int:loan_id>/renew", methods=["POST"])
def renew_loan(loan_id):
    return jsonify(loan_json(loan_service.renew_loan(loan_id)))


@app.route("/loans/<int:loan_id>/pay-fine", methods=["POST"])
def pay_fine(loan_id):
    return jsonify(loan_json(loan_service.pay_fine(loan_id)))


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
