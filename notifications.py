"""Notifications (MOCKED).

Nothing is really sent. MockNotificationService is a mock object
(https://en.wikipedia.org/wiki/Mock_object): a stand-in for a real email
service. It remembers every message in `sent_messages` and writes a line to
outbox.txt so you can see what would have been sent.
"""
OUTBOX_PATH = "outbox.txt"


class MockNotificationService:
    def __init__(self, outbox_path=OUTBOX_PATH):
        self.outbox_path = outbox_path
        self.sent_messages = []

    def send(self, email, subject, body):
        self.sent_messages.append({"to": email, "subject": subject, "body": body})
        with open(self.outbox_path, "a") as f:
            f.write("TO: " + email + " | SUBJECT: " + subject + " | BODY: " + body + "\n")


notifier = MockNotificationService()


def send_email(email, subject, body):
    notifier.send(email, subject, body)


def notify_checkout(email, title):
    send_email(email, "Book checked out", "You checked out " + title)


def notify_renewal(email, title):
    send_email(email, "Loan renewed", "You renewed " + title)


def notify_return(email, title, fine):
    send_email(email, "Book returned", "You returned " + title + ". Fine: $" + str(fine))


def notify_fine_paid(email, amount):
    send_email(email, "Fine paid", "We received $" + str(amount))