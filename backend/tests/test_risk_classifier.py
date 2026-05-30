from app.analyzer.risk_classifier import classify_files
from app.models.schemas import ChangedFile


def test_classifier_weights_permission_and_missing_tests():
    files = [
        ChangedFile(
            filename="src/auth/permission.ts",
            status="modified",
            additions=8,
            deletions=2,
            patch="""@@ -1,2 +1,4 @@
+if (!user.role) {
+  return true;
+}
""",
        )
    ]

    [classified] = classify_files(files)

    assert classified.risk_level in {"high", "critical"}
    assert "changes access-control related logic" in classified.risk_reasons
    assert "no test file changed in this PR" in classified.risk_reasons
