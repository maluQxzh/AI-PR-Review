from app.analyzer.risk_classifier import classify_files, detect_dimensions
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


def test_dimensions_detected_for_security_file():
    files = [
        ChangedFile(
            filename="src/auth/login.py",
            status="modified",
            additions=5,
            deletions=1,
            patch="""@@ -1,0 +1,5 @@
+def login(username, password):
+    token = jwt.encode({"user": username}, SECRET_KEY)
+    session["token"] = token
+    return token
+""",
        )
    ]
    [classified] = classify_files(files)
    assert "security" in classified.risk_dimensions, \
        f"Expected security dimension, got: {classified.risk_dimensions}"
    assert "test_gap" in classified.risk_dimensions, \
        f"Expected test_gap dimension, got: {classified.risk_dimensions}"


def test_dimensions_detected_for_concurrency_file():
    files = [
        ChangedFile(
            filename="src/worker.py",
            status="modified",
            additions=4,
            deletions=1,
            patch="""@@ -1,0 +1,4 @@
+async def process():
+    async with lock:
+        await db.execute(query)
+""",
        )
    ]
    [classified] = classify_files(files)
    assert "concurrency" in classified.risk_dimensions, \
        f"Expected concurrency dimension, got: {classified.risk_dimensions}"


def test_dimensions_detected_for_multiple():
    files = [
        ChangedFile(
            filename="src/payment/gateway.py",
            status="modified",
            additions=6,
            deletions=1,
            patch="""@@ -1,0 +1,6 @@
+import hashlib
+async def charge(amount):
+    key = os.getenv("STRIPE_KEY")
+    await stripe.Charge.create(amount=amount)
+    db.session.add(Transaction(amount=amount))
+""",
        )
    ]
    [classified] = classify_files(files)
    dims = classified.risk_dimensions
    # Payment path -> security, async -> concurrency, DB ops -> data
    assert "security" in dims, f"Expected security, got: {dims}"
    assert "concurrency" in dims, f"Expected concurrency, got: {dims}"


def test_dimensions_empty_for_simple_file():
    files = [
        ChangedFile(
            filename="src/format.py",
            status="modified",
            additions=1,
            deletions=0,
            patch="""@@ -1,0 +1,1 @@
+GREETING = "Hello, World!"
""",
        )
    ]
    [classified] = classify_files(files)
    # Simple constant assignment — may get test_gap but not security/concurrency
    assert "security" not in classified.risk_dimensions


def test_detect_dimensions_helper():
    text = "async def foo(): await bar(); password = 'secret'"
    dims = detect_dimensions(text, "src/app.py")
    assert "security" in dims
    assert "concurrency" in dims
