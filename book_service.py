import book_repository
import checks
import validation
from errors import bad_request


def list_books(only_available):
    return book_repository.list_books(only_available)


def get_book(book_id):
    return checks.must_exist(book_repository.get_book(book_id), "book")


def create_book(data):
    if not data.get("title") or not data.get("author"):
        raise bad_request("title and author are required")
    if not validation.is_valid_isbn(data.get("isbn")):
        raise bad_request("invalid isbn")
    return book_repository.create_book(data["title"], data["author"], data["isbn"])


def delete_book(book_id):
    book = get_book(book_id)
    checks.book_must_not_be_on_loan(book)
    book_repository.delete_book(book_id)