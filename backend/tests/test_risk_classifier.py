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
    assert "修改访问控制相关逻辑" in classified.risk_reasons
    assert "该 PR 没有修改测试文件" in classified.risk_reasons
