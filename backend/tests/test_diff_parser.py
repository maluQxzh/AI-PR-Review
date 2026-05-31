from app.analyzer.diff_parser import extract_added_lines, should_review_file


def test_extract_added_lines_from_patch():
    patch = """@@ -10,2 +10,3 @@
 unchanged
-old
+new
+return true
"""
    added = extract_added_lines(patch)
    assert added == [
        {"line": 11, "content": "new"},
        {"line": 12, "content": "return true"},
    ]


def test_extract_added_lines_from_multiple_hunks_and_delete_only_hunk():
    patch = """@@ -1,3 +1,4 @@
 unchanged
+first
@@ -20,4 +21,3 @@
-removed only
 unchanged
@@ -40,1 +40,2 @@
+second
"""
    added = extract_added_lines(patch)

    assert added == [
        {"line": 2, "content": "first"},
        {"line": 40, "content": "second"},
    ]


def test_extract_added_lines_handles_missing_patch():
    assert extract_added_lines(None) == []
    assert extract_added_lines("") == []


def test_should_review_filters_low_value_files():
    assert not should_review_file("dist/app.min.js", total_files=3)
    assert should_review_file("src/auth/check.ts", total_files=3)
    assert should_review_file("yarn.lock", total_files=1)
