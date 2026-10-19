"""Guards against a SQLAlchemy mistake: turning a query Result straight into a dict.

    dict(db.session.execute(...))      # WRONG: raises "'ChunkedIteratorResult' object is not subscriptable"
    {a: b for a, b in db.session.execute(...)}   # right

A Result has a keys() method, so dict() thinks it is a mapping and tries result["column"].
These tests need no database:
    python -m unittest tests.test_query_result_handling -v
"""
import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN = ["services", "routes", "forms", "models", "cli.py", "app.py"]
QUERY_METHODS = {"execute", "scalars", "scalar"}


class FakeResult:
    """Stands in for a SQLAlchemy Result: iterable rows, a keys() method, no item lookup."""

    def __init__(self):
        self._rows = [(3, 2), (7, 1)]

    def keys(self):
        return ["provider_id", "job_count"]

    def __iter__(self):
        return iter(self._rows)


def find_dict_over_query_results(source):
    """Line numbers where dict(...) is applied to something that comes from a query call."""
    problems = []
    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, (ast.FunctionDef, ast.Module)):
            continue
        # names assigned from  x = something.execute(...) / .scalars(...)
        query_names = set()
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and call.func.attr in QUERY_METHODS:
                    query_names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and node.args:
                argument = node.args[0]
                direct = any(
                    isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr in QUERY_METHODS
                    for inner in ast.walk(argument)
                )
                via_name = isinstance(argument, ast.Name) and argument.id in query_names
                if direct or via_name:
                    problems.append(node.lineno)
    return sorted(set(problems))


class ResultHandlingTests(unittest.TestCase):
    def test_dict_of_a_result_object_fails_the_way_the_bug_did(self):
        with self.assertRaises(TypeError) as caught:
            dict(FakeResult())
        self.assertIn("not subscriptable", str(caught.exception))

    def test_a_comprehension_reads_the_rows_correctly(self):
        self.assertEqual({provider_id: jobs for provider_id, jobs in FakeResult()}, {3: 2, 7: 1})

    def test_the_guard_detects_the_bad_pattern(self):
        direct = "def f():\n    return dict(db.session.execute(stmt))\n"
        indirect = "def f():\n    rows = db.session.execute(stmt)\n    return dict(rows)\n"
        self.assertEqual(find_dict_over_query_results(direct), [2])
        self.assertEqual(find_dict_over_query_results(indirect), [3])

    def test_the_guard_accepts_the_good_patterns(self):
        good = (
            "def f():\n"
            "    rows = db.session.execute(stmt)\n"
            "    a = {k: v for k, v in rows}\n"
            "    b = dict(some_plain_list)\n"
            "    return a, b\n"
        )
        self.assertEqual(find_dict_over_query_results(good), [])

    def test_no_project_code_turns_a_query_result_straight_into_a_dict(self):
        offenders = {}
        for entry in SCAN:
            path = PROJECT_ROOT / entry
            files = [path] if path.is_file() else sorted(path.rglob("*.py"))
            for file in files:
                lines = find_dict_over_query_results(file.read_text(encoding="utf-8"))
                if lines:
                    offenders[str(file.relative_to(PROJECT_ROOT))] = lines
        self.assertEqual(offenders, {}, "dict(<query result>) found; build the dict with a comprehension instead")


if __name__ == "__main__":
    unittest.main()
