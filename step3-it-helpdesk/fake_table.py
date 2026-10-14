"""A stand-in for a boto3 DynamoDB Table, for the Lambdas' unit tests.

Holds rows in a dict keyed by `pk` and answers the calls our code makes,
shaped like boto3's real responses. Rows are copied in and out, so a test
can't change the table by editing a returned dict (nor can our code).
Each call is recorded in `calls`, so a test can check the table was never
touched.
"""

import copy


class FakeTable:
    def __init__(self, items=()):
        self.rows = {item["pk"]: copy.deepcopy(item) for item in items}
        self.calls = []

    def get_item(self, Key):
        self.calls.append(("get_item", Key))
        row = self.rows.get(Key["pk"])
        return {"Item": copy.deepcopy(row)} if row is not None else {}

    def put_item(self, Item):
        self.calls.append(("put_item", Item["pk"]))
        self.rows[Item["pk"]] = copy.deepcopy(Item)

    def rows_of_kind(self, kind):
        """The stored rows of one kind, e.g. "audit"."""
        return [row for row in self.rows.values() if row["kind"] == kind]

    def writes(self):
        """The keys written so far, in order."""
        return [key for call, key in self.calls if call == "put_item"]
