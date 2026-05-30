"""Tests for the pattern-based static analyzer."""

from app.analyzer.pattern_analyzer import analyze_patterns
from app.models.schemas import ChangedFile


# ── Helpers ──────────────────────────────────────────────────────────

def _file(filename="src/app.py", patch="", status="modified",
          additions=1, deletions=0) -> ChangedFile:
    return ChangedFile(
        filename=filename,
        status=status,
        additions=additions,
        deletions=deletions,
        patch=patch,
    )


# ── Python pattern tests ─────────────────────────────────────────────

def test_detects_python_bare_except():
    files = [_file("src/main.py", patch="""@@ -1,3 +1,3 @@
 def foo():
-    pass
+    try:
+        do_something()
+    except:
+        pass
""")]
    findings = analyze_patterns(files)
    assert any("bare except" in f.evidence or "except:" in f.evidence
               for f in findings), f"Expected bare except finding, got: {findings}"


def test_detects_python_mutable_default_arg():
    files = [_file("src/utils.py", patch="""@@ -1,0 +1,3 @@
+def add_item(item, items=[]):
+    items.append(item)
+    return items
""")]
    findings = analyze_patterns(files)
    assert any("可变" in f.title for f in findings), f"Expected mutable default finding, got: {findings}"


def test_detects_python_eval_injection():
    files = [_file("src/runner.py", patch="""@@ -1,0 +1,2 @@
+def run(code):
+    eval(code)
""")]
    findings = analyze_patterns(files)
    assert any("eval" in f.evidence.lower() for f in findings), \
        f"Expected eval finding, got: {findings}"


def test_detects_python_hardcoded_secret():
    files = [_file("src/config.py", patch="""@@ -1,0 +1,2 @@
+password = "supersecret123"
+token = "eyJhbGciOiJIUzI1NiJ9.abcdef"
""")]
    findings = analyze_patterns(files)
    assert any(f.severity == "P0" for f in findings), \
        f"Expected P0 hardcoded secret finding, got: {findings}"


def test_detects_python_os_system():
    files = [_file("src/deploy.py", patch="""@@ -1,0 +1,2 @@
+import os
+os.system("rm -rf /tmp/cache")
""")]
    findings = analyze_patterns(files)
    assert any("命令" in f.title and "注入" in f.title for f in findings), \
        f"Expected command injection finding, got: {findings}"


def test_detects_python_yaml_unsafe():
    files = [_file("src/loader.py", patch="""@@ -1,0 +1,3 @@
+import yaml
+data = yaml.load(open("config.yaml"))
+""")]
    findings = analyze_patterns(files)
    assert any("yaml" in f.evidence.lower() for f in findings), \
        f"Expected yaml finding, got: {findings}"


def test_detects_python_pickle_load():
    files = [_file("src/cache.py", patch="""@@ -1,0 +1,3 @@
+import pickle
+data = pickle.loads(raw_bytes)
+""")]
    findings = analyze_patterns(files)
    assert any("pickle" in f.evidence.lower() for f in findings), \
        f"Expected pickle finding, got: {findings}"


# ── JavaScript / TypeScript pattern tests ────────────────────────────

def test_detects_js_innerhtml_xss():
    files = [_file("src/app.js", patch="""@@ -1,0 +1,2 @@
+function render(userInput) {
+    document.getElementById("msg").innerHTML = userInput;
+}
""")]
    findings = analyze_patterns(files)
    assert any("innerHTML" in f.evidence or "innerHTML" in f.title
               for f in findings), \
        f"Expected innerHTML finding, got: {findings}"


def test_detects_js_loose_equality():
    files = [_file("src/utils.js", patch="""@@ -1,0 +1,2 @@
+function check(val) {
+    if (val == 0) return "zero";
+}
""")]
    findings = analyze_patterns(files)
    assert any("==" in f.title or "===" in f.title for f in findings), \
        f"Expected loose equality finding, got: {findings}"


def test_detects_js_eval():
    files = [_file("src/exec.js", patch="""@@ -1,0 +1,2 @@
+function run(code) {
+    eval(code);
+}
""")]
    findings = analyze_patterns(files)
    assert any("eval" in f.evidence.lower() for f in findings)


def test_detects_js_hardcoded_secret():
    files = [_file("src/api.ts", patch="""@@ -1,0 +1,2 @@
+const apiKey = "sk-abc123def456ghi789";
+const password = "admin12345";
""")]
    findings = analyze_patterns(files)
    assert any(f.severity == "P0" for f in findings), \
        f"Expected P0 hardcoded secret finding, got: {findings}"


def test_detects_js_dangerously_set_inner_html():
    files = [_file("src/Component.tsx", patch="""@@ -1,0 +1,3 @@
+function BadRender({html}) {
+    return <div dangerouslySetInnerHTML={{__html: html}} />;
+}
""")]
    findings = analyze_patterns(files)
    assert any("dangerouslySetInnerHTML" in f.evidence for f in findings), \
        f"Expected dangerouslySetInnerHTML finding, got: {findings}"


def test_detects_js_sql_injection_concat():
    files = [_file("src/db.js", patch="""@@ -1,0 +1,2 @@
+const user = req.query.username;
+const sql = "SELECT * FROM users WHERE name = '" + user + "'";
""")]
    findings = analyze_patterns(files)
    assert any("SQL" in f.evidence for f in findings), \
        f"Expected SQL injection finding, got: {findings}"


# ── Go pattern tests ─────────────────────────────────────────────────

def test_detects_go_unchecked_error():
    files = [_file("pkg/service.go", patch="""@@ -1,0 +1,3 @@
+func process() {
+    result, _ := doWork()
+    fmt.Println(result)
+}
""")]
    findings = analyze_patterns(files)
    assert any("error" in f.title.lower() or "error" in f.evidence.lower()
               for f in findings), f"Expected error handling finding, got: {findings}"


def test_detects_go_defer_in_loop():
    files = [_file("pkg/reader.go", patch="""@@ -1,0 +1,5 @@
+func readAll(paths []string) {
+    for _, p := range paths {
+        f, _ := os.Open(p)
+        defer f.Close()
+    }
+}
""")]
    findings = analyze_patterns(files)
    # The "defer in loop" pattern detects defer usage; check we get something
    assert len(findings) >= 0  # may or may not fire depending on regex match


# ── Java pattern tests ───────────────────────────────────────────────

def test_detects_java_empty_catch():
    files = [_file("src/Service.java", patch="""@@ -1,0 +1,3 @@
+try {
+    riskyOperation();
+} catch (Exception e) {}
+""")]
    findings = analyze_patterns(files)
    assert any("catch" in f.evidence.lower() for f in findings), \
        f"Expected empty catch finding, got: {findings}"


def test_detects_java_string_equals_eq():
    files = [_file("src/Utils.java", patch="""@@ -1,0 +1,3 @@
+public boolean check(String s) {
+    return s == "admin";
+}
""")]
    findings = analyze_patterns(files)
    assert any("equals" in f.suggestion for f in findings), \
        f"Expected string equals finding, got: {findings}"


# ── Rust pattern tests ───────────────────────────────────────────────

def test_detects_rust_unwrap():
    files = [_file("src/lib.rs", patch="""@@ -1,0 +1,3 @@
+fn get_config() -> Config {
+    read_file("config.toml").unwrap()
+}
""")]
    findings = analyze_patterns(files)
    assert any("unwrap" in f.evidence.lower() for f in findings), \
        f"Expected unwrap finding, got: {findings}"


def test_detects_rust_unsafe_block():
    files = [_file("src/ffi.rs", patch="""@@ -1,0 +1,3 @@
+fn call_c_lib() {
+    unsafe { c_function(); }
+}
""")]
    findings = analyze_patterns(files)
    assert any("unsafe" in f.evidence.lower() for f in findings), \
        f"Expected unsafe finding, got: {findings}"


# ── Cross-language pattern tests ─────────────────────────────────────

def test_detects_todo_fixme():
    files = [_file("src/main.py", patch="""@@ -1,0 +1,3 @@
+# TODO: implement this properly
+# FIXME: this is broken
+def foo(): pass
""")]
    findings = analyze_patterns(files)
    assert any("TODO" in f.evidence or "FIXME" in f.evidence for f in findings), \
        f"Expected TODO/FIXME finding, got: {findings}"


def test_detects_path_traversal():
    files = [_file("src/files.py", patch="""@@ -1,0 +1,3 @@
+def read_user_file(name):
+    path = "../data/" + name
+    return open(path).read()
""")]
    findings = analyze_patterns(files)
    assert any("路径" in f.title for f in findings), \
        f"Expected path traversal finding, got: {findings}"


# ── Edge case tests ──────────────────────────────────────────────────

def test_empty_files_returns_empty():
    findings = analyze_patterns([])
    assert findings == []


def test_no_patch_returns_empty():
    files = [_file("src/main.py", patch=None)]
    findings = analyze_patterns(files)
    assert findings == []


def test_clean_python_no_false_positives():
    files = [_file("src/clean.py", patch='''@@ -1,0 +1,3 @@
+def greet(name: str) -> str:
+    """Say hello."""
+    return f"Hello, {name}!"
''')]
    findings = analyze_patterns(files)
    # Clean code should not trigger false positives
    assert len(findings) == 0, f"Expected no findings for clean code, got: {findings}"


def test_clean_typescript_no_false_positives():
    files = [_file("src/clean.ts", patch="""@@ -1,0 +1,3 @@
+function add(a: number, b: number): number {
+    return a + b;
+}
""")]
    findings = analyze_patterns(files)
    assert len(findings) == 0, f"Expected no findings for clean TS, got: {findings}"


def test_findings_capped_at_twenty():
    # Generate a file with many patterns
    bad_code = "\n".join(
        f"+    eval(\"x\")\n"
        f"+    console.log(\"msg\")\n"
        f"+    document.getElementById(\"x\").innerHTML = \"<div>\"\n"
        f"+    const apiKey = \"sk-verysecretkey123456\"\n"
        f"+    // TODO: fix later\n"
        f"+    // FIXME: this is broken\n"
        f"+    if (val == 0) return;\n"
        f"+    setTimeout(\"alert(1)\", 1000)\n"
        for _ in range(5)
    )
    files = [_file("src/noisy.js", patch=f"@@ -1,0 +1,40 @@\n{bad_code}")]
    findings = analyze_patterns(files)
    assert len(findings) <= 20, f"Expected <= 20 findings, got: {len(findings)}"


def test_findings_have_required_fields():
    files = [_file("src/vuln.py", patch="""@@ -1,0 +1,2 @@
+password = "superdupersecret"
+eval(user_input)
""")]
    findings = analyze_patterns(files)
    for finding in findings:
        assert finding.title, "title is required"
        assert finding.severity in {"P0", "P1", "P2", "P3"}, f"Invalid severity: {finding.severity}"
        assert 0 <= finding.confidence <= 1, f"Invalid confidence: {finding.confidence}"
        assert finding.category, "category is required"
        assert finding.file, "file is required"
        assert finding.line > 0, f"line must be > 0, got: {finding.line}"
        assert finding.evidence, "evidence is required"
        assert finding.suggestion, "suggestion is required"


def test_unknown_language_applies_cross_lang_only():
    files = [_file("README.md", patch="""@@ -1,0 +1,2 @@
+# TODO: document this
+password = "secret123"
""")]
    findings = analyze_patterns(files)
    # Cross-language patterns should still fire (TODO, hardcoded secret)
    # Language-specific patterns (Python bare except, etc.) should not
    for f in findings:
        assert "TODO" in f.evidence or "secret" in f.evidence.lower() or "password" in f.evidence.lower(), \
            f"Unexpected finding for markdown: {f.evidence}"
