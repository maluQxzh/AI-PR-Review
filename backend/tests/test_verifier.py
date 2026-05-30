import pytest

from app.analyzer.verifier import (
    _apply_severity_downgrade,
    _build_added_line_map,
    _build_source_test_map,
    _deduplicate_similar,
    _evidence_matches_diff,
    _is_style_only,
    _title_similarity,
    verify_findings,
)
from app.models.schemas import ChangedFile, Finding


# ---------------------------------------------------------------------------
# Helpers to build test data quickly
# ---------------------------------------------------------------------------

def _make_finding(
    title="Default finding",
    severity="P2",
    confidence=0.8,
    category="logic",
    file="src/app.ts",
    line=4,
    evidence="Evidence text here.",
    impact="Impact text here.",
    suggestion="Suggestion here.",
    comment_draft="Draft comment.",
    tag="",
) -> Finding:
    return Finding(
        title=title,
        severity=severity,
        confidence=confidence,
        category=category,
        file=file,
        line=line,
        evidence=evidence,
        impact=impact,
        suggestion=suggestion,
        comment_draft=comment_draft,
        tag=tag,
    )


def _make_file(
    filename="src/app.ts",
    status="modified",
    additions=30,
    deletions=10,
    patch=None,
    risk_score=50,
    risk_reasons=None,
) -> ChangedFile:
    return ChangedFile(
        filename=filename,
        status=status,
        additions=additions,
        deletions=deletions,
        patch=patch,
        risk_score=risk_score,
        risk_reasons=risk_reasons or [],
    )


# ---------------------------------------------------------------------------
# Existing test — must still pass
# ---------------------------------------------------------------------------

def test_verifier_removes_unbacked_findings():
    """Original behaviour: findings whose file is not in changed_files are removed."""
    patch = "@@ -1,2 +1,3 @@\n unchanged\n+function validate(input) { return true; }"
    files = [_make_file(filename="src/app.ts", patch=patch)]

    # Line 2 is the added line
    findings = [
        _make_finding(
            title="Real issue",
            file="src/app.ts",
            line=2,
            evidence="Function validate added without validation logic.",
            impact="Callers may fail on invalid input.",
            suggestion="Add proper input validation inside function.",
        ),
        _make_finding(
            title="Other file",
            file="src/other.ts",
            line=2,
            evidence="Looks risky here — some problem.",
            impact="Unknown issue in this file.",
            suggestion="Please check this problem carefully.",
        ),
    ]

    verified = verify_findings(findings, files)
    assert len(verified) == 1
    assert verified[0].title == "Real issue"


# ---------------------------------------------------------------------------
# 1. Line validated against diff
# ---------------------------------------------------------------------------

def test_line_validated_against_diff():
    """Findings with a line number not in the added lines are removed."""
    patch = """@@ -10,3 +10,5 @@
 unchanged context
+added at line eleven
+added at line twelve
 unchanged context
"""
    files = [_make_file(filename="src/app.ts", patch=patch)]

    # This line is in the diff (11)
    good = _make_finding(
        title="Good finding",
        file="src/app.ts",
        line=11,
        evidence="Added line eleven with new logic.",
        suggestion="Review the added code at line eleven.",
    )
    # This line is not in the diff at all (99)
    bad = _make_finding(
        title="Phantom line",
        file="src/app.ts",
        line=99,
        evidence="This line number is wrong.",
        suggestion="Remove phantom reference.",
    )

    verified = verify_findings([good, bad], files)
    assert len(verified) == 1
    assert verified[0].title == "Good finding"


# ---------------------------------------------------------------------------
# 2. Patch=None skips line validation (graceful degradation)
# ---------------------------------------------------------------------------

def test_patch_none_skips_line_validation():
    """When patch is None, any positive line number is accepted."""
    files = [_make_file(filename="src/app.ts", patch=None)]
    finding = _make_finding(
        title="Still there",
        file="src/app.ts",
        line=42,
        evidence="No diff to check against.",
        suggestion="But this should survive anyway.",
    )

    verified = verify_findings([finding], files)
    assert len(verified) == 1
    assert verified[0].title == "Still there"


# ---------------------------------------------------------------------------
# 3. Evidence cross-referenced against diff content
# ---------------------------------------------------------------------------

def test_evidence_cross_referenced():
    """Finding evidence must mention something present in the nearby added lines."""
    patch = """@@ -1,0 +1,3 @@
+if (user == null) return;
+const name = user.name;
"""
    files = [_make_file(filename="src/app.ts", patch=patch)]

    # Evidence contains "null" which appears in the added line at line 1
    good = _make_finding(
        title="Null check issue",
        file="src/app.ts",
        line=1,
        evidence="User might be null here.",
        suggestion="Add null guard before accessing name field.",
    )
    # Evidence mentions "SQL" but nothing SQL-related exists in the diff
    bad = _make_finding(
        title="SQL injection",
        file="src/app.ts",
        line=1,
        evidence="SQL injection vulnerability here.",
        suggestion="Use parameterized queries instead.",
    )

    verified = verify_findings([good, bad], files)
    assert len(verified) == 1
    assert verified[0].title == "Null check issue"


def test_evidence_patch_none_skips_check():
    """When patch is None, evidence check is skipped entirely."""
    files = [_make_file(filename="src/app.ts", patch=None)]
    finding = _make_finding(
        title="Anything",
        file="src/app.ts",
        line=1,
        evidence="Evidence mentions code that is not in any diff.",
        suggestion="But it should still be accepted here.",
    )

    verified = verify_findings([finding], files)
    assert len(verified) == 1


# ---------------------------------------------------------------------------
# 4. Semantic dedup
# ---------------------------------------------------------------------------

def test_semantic_dedup_removes_similar():
    """Two findings in the same (file, category) with similar titles — keep higher confidence."""
    patch = "@@ -1,0 +1,2 @@\n+function validate() {}\n+function sanitize() {}\n"
    files = [_make_file(filename="src/app.ts", patch=patch)]

    f1 = _make_finding(
        title="Missing null check in function",
        severity="P2",
        confidence=0.7,
        category="logic",
        file="src/app.ts",
        line=1,
        evidence="Validate function added without null check.",
        suggestion="Add null validation inside function.",
    )
    f2 = _make_finding(
        title="Null check missing in function",
        severity="P2",
        confidence=0.85,
        category="logic",
        file="src/app.ts",
        line=2,
        evidence="Sanitize function missing validation logic.",
        suggestion="Add validation inside sanitize function.",
    )

    verified = verify_findings([f1, f2], files)
    assert len(verified) == 1
    assert verified[0].confidence == 0.85


def test_semantic_dedup_different_category_keeps_both():
    """Same title but different categories — both survive."""
    patch = "@@ -1,0 +1,2 @@\n+function validate(input) {}\n+function execute(query) {}\n"
    files = [_make_file(filename="src/app.ts", patch=patch)]

    f1 = _make_finding(
        title="Null check missing here",
        category="security",
        file="src/app.ts",
        line=1,
        evidence="Validate function lacks security check.",
        suggestion="Add null check for security validation.",
    )
    f2 = _make_finding(
        title="Null check missing here",
        category="logic",
        file="src/app.ts",
        line=2,
        evidence="Execute function missing validation.",
        suggestion="Add null check for logic validation.",
    )

    verified = verify_findings([f1, f2], files)
    assert len(verified) == 2


def test_title_similarity_identical():
    assert _title_similarity("Null check missing", "Null check missing") > 0.9


def test_title_similarity_different():
    assert _title_similarity("SQL injection in query", "Formatting issue") < 0.3


def test_title_similarity_empty():
    assert _title_similarity("", "something") == 0.0
    assert _title_similarity("", "") == 0.0


# ---------------------------------------------------------------------------
# 5. Style detection — downgrade instead of delete
# ---------------------------------------------------------------------------

def test_style_downgraded_not_deleted():
    """Style-only findings are kept but downgraded to P3 with [建议] tag."""
    patch = "@@ -1,0 +1,2 @@\n+const x = 1\n+const y = 2\n"
    files = [_make_file(filename="src/app.ts", patch=patch)]

    finding = _make_finding(
        title="Fix formatting and naming convention",
        severity="P1",
        confidence=0.8,
        category="style",
        file="src/app.ts",
        line=1,
        evidence="Indentation is off and naming convention inconsistent.",
        suggestion="Run prettier to fix formatting and naming.",
    )

    verified = verify_findings([finding], files)
    assert len(verified) == 1
    assert verified[0].severity == "P3"
    assert verified[0].tag == "[建议]"


def test_non_style_unchanged():
    """Security findings are NOT flagged as style-only."""
    patch = "@@ -1,0 +1,2 @@\n+const query = 'SELECT * FROM ' + table\n+db.run(query)\n"
    files = [_make_file(filename="src/app.ts", patch=patch)]

    finding = _make_finding(
        title="SQL injection risk in query builder",
        severity="P1",
        confidence=0.85,
        category="security",
        file="src/app.ts",
        line=1,
        evidence="String concatenation in SQL query.",
        suggestion="Use parameterized queries instead.",
    )

    verified = verify_findings([finding], files)
    assert len(verified) == 1
    assert verified[0].severity == "P1"
    assert verified[0].tag == ""


def test_is_style_only_detects_naming():
    f = _make_finding(
        title="Rename variable to follow camelCase convention",
        evidence="The variable user_name should be userName.",
        suggestion="Rename to camelCase style.",
    )
    assert _is_style_only(f) is True


def test_is_style_only_risk_exclusion_blocks():
    """Style keyword + risk keyword → NOT style-only."""
    f = _make_finding(
        title="Formatting issue may hide security vulnerability",
        evidence="Badly formatted auth check.",
        suggestion="Fix formatting and review security.",
    )
    assert _is_style_only(f) is False


# ---------------------------------------------------------------------------
# 6. Test coverage confidence adjustment
# ---------------------------------------------------------------------------

def test_test_coverage_lowers_confidence():
    """When a corresponding test file is changed, confidence is slightly reduced."""
    patch_src = "@@ -1,0 +1,1 @@\n+export function login() {}\n"
    patch_test = "@@ -1,0 +1,1 @@\n+import { login } from './auth';\n"

    files = [
        _make_file(filename="src/auth.ts", patch=patch_src, risk_score=70),
        _make_file(filename="src/auth.test.ts", patch=patch_test),
    ]

    finding = _make_finding(
        title="Auth function needs review",
        file="src/auth.ts",
        line=1,
        confidence=0.8,
        evidence="Login function added here.",
        suggestion="Review the login function.",
    )

    verified = verify_findings([finding], files)
    assert len(verified) == 1
    # Confidence should be reduced by 5% (0.8 * 0.95 = 0.76)
    assert verified[0].confidence == 0.76


def test_missing_test_elevates_confidence():
    """When no test files are changed and the file is high-risk, confidence is elevated."""
    patch = "@@ -1,0 +1,1 @@\n+export function processPayment() {}\n"
    files = [_make_file(filename="src/payment.ts", patch=patch, risk_score=80)]

    finding = _make_finding(
        title="Payment processing change needs tests",
        file="src/payment.ts",
        line=1,
        confidence=0.7,
        evidence="Payment function added here.",
        suggestion="Add tests for payment processing.",
    )

    verified = verify_findings([finding], files)
    assert len(verified) == 1
    # Confidence should be elevated by 8% (0.7 * 1.08 = 0.756)
    assert verified[0].confidence == pytest.approx(0.756, rel=1e-6)


# ---------------------------------------------------------------------------
# 7. Severity downgrade based on file context
# ---------------------------------------------------------------------------

def test_severity_downgrade_ignored_file():
    """Files matching IGNORE_PATTERNS have their findings downgraded."""
    f = _make_finding(
        title="Something in dist",
        severity="P2",
        file="dist/bundle.js",
        line=1,
    )
    file_obj = _make_file(filename="dist/bundle.js", status="modified", additions=30, deletions=10)
    _apply_severity_downgrade(f, file_obj)
    assert f.severity == "P3"
    assert f.tag == "[建议]"


def test_severity_downgrade_removed_file():
    """Findings on removed files are downgraded to P3."""
    f = _make_finding(
        title="Issue in deleted file",
        severity="P1",
        file="src/old.ts",
        line=1,
    )
    file_obj = _make_file(filename="src/old.ts", status="removed", additions=30, deletions=10)
    _apply_severity_downgrade(f, file_obj)
    assert f.severity == "P3"
    assert f.tag == "[建议]"


def test_severity_downgrade_documentation_file():
    """Markdown/doc files are downgraded to P3."""
    f = _make_finding(title="Issue in readme", severity="P2", file="README.md", line=1)
    file_obj = _make_file(filename="README.md", status="modified", additions=30, deletions=10)
    _apply_severity_downgrade(f, file_obj)
    assert f.severity == "P3"
    assert f.tag == "[建议]"


def test_severity_downgrade_tiny_change():
    """Files with ≤10 total line changes have findings downgraded."""
    f = _make_finding(title="Small change", severity="P2", file="src/util.ts", line=1)
    file_obj = _make_file(filename="src/util.ts", status="modified", additions=3, deletions=2)
    _apply_severity_downgrade(f, file_obj)
    assert f.severity == "P3"
    assert f.tag == "[建议]"


def test_low_confidence_p0_downgraded():
    """P0/P1 findings with confidence < 0.65 should be downgraded to P2."""
    f = _make_finding(
        title="Risky change",
        severity="P0",
        confidence=0.6,
        file="src/risky.ts",
        line=1,
    )
    file_obj = _make_file(filename="src/risky.ts", status="modified", additions=50, deletions=10)
    _apply_severity_downgrade(f, file_obj)
    assert f.severity == "P2"
    assert f.tag == "[建议]"


def test_severity_not_downgraded_for_normal_file():
    """Normal source file with sufficient changes: no downgrade applied."""
    f = _make_finding(title="Real issue", severity="P2", file="src/main.ts", line=1)
    file_obj = _make_file(
        filename="src/main.ts", status="modified", additions=30, deletions=10
    )
    original_severity = f.severity
    original_tag = f.tag
    _apply_severity_downgrade(f, file_obj)
    assert f.severity == original_severity
    assert f.tag == original_tag


# ---------------------------------------------------------------------------
# 8. Unit tests for new helpers
# ---------------------------------------------------------------------------

def test_build_added_line_map():
    patch = "@@ -1,0 +1,3 @@\n+line one\n+line two\n"
    files = [
        _make_file(filename="src/a.ts", patch=patch),
        _make_file(filename="src/b.ts", patch=None),  # no patch
    ]
    result = _build_added_line_map(files)
    assert result["src/a.ts"] == {1, 2}
    assert result["src/b.ts"] == set()


def test_evidence_matches_diff_finds_word():
    added = [{"line": 5, "content": "if (user == null) { return false; }"}]
    f = _make_finding(file="x.ts", line=5, evidence="user might be null", suggestion="")
    assert _evidence_matches_diff(f, added) is True


def test_evidence_matches_diff_no_match():
    added = [{"line": 5, "content": "const x = 1;"}]
    f = _make_finding(
        file="x.ts",
        line=5,
        evidence="SQL injection in query construction",
        suggestion="Use parameterized queries",
    )
    assert _evidence_matches_diff(f, added) is False


def test_evidence_matches_diff_empty_added():
    """Empty added lines list → accept (graceful degradation)."""
    f = _make_finding(
        file="x.ts", line=5, evidence="anything here", suggestion="do something"
    )
    assert _evidence_matches_diff(f, []) is True


def test_deduplicate_similar_empty():
    assert _deduplicate_similar([]) == []


def test_deduplicate_similar_single():
    f = _make_finding(title="Only one")
    assert _deduplicate_similar([f]) == [f]


def test_build_source_test_map_with_test():
    """Corresponding test file in common locations is detected."""
    files = [
        _make_file(filename="src/auth/login.ts"),
        _make_file(filename="src/auth/__tests__/login.test.ts"),
    ]
    result = _build_source_test_map(files)
    assert result.get("src/auth/login.ts") is True


def test_build_source_test_map_without_test():
    """No corresponding test file changed."""
    files = [
        _make_file(filename="src/auth/login.ts"),
        _make_file(filename="src/ui/button.ts"),
    ]
    result = _build_source_test_map(files)
    assert result.get("src/auth/login.ts") is False
    assert result.get("src/ui/button.ts") is False


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

def test_empty_files_returns_empty():
    """When there are no changed files, all findings are removed."""
    files: list[ChangedFile] = []
    findings = [_make_finding(title="Something", file="src/app.ts", line=1)]
    assert verify_findings(findings, files) == []


def test_empty_findings_returns_empty():
    """When there are no findings, return empty list immediately."""
    files = [_make_file()]
    assert verify_findings([], files) == []


def test_line_zero_rejected():
    """Finding with line=0 is always rejected."""
    files = [_make_file(filename="src/app.ts", patch="@@ -1,0 +1,1 @@\n+added")]
    finding = _make_finding(title="Zero line", file="src/app.ts", line=0)
    assert verify_findings([finding], files) == []


def test_confidence_below_threshold_rejected():
    """Finding with confidence < 0.55 is rejected (after adjustments)."""
    patch = "@@ -1,0 +1,1 @@\n+added line here"
    files = [_make_file(filename="src/app.ts", patch=patch)]
    finding = _make_finding(
        title="Low confidence",
        file="src/app.ts",
        line=1,
        confidence=0.4,
        evidence="Added line here now.",
        suggestion="Review the added line here.",
    )
    assert verify_findings([finding], files) == []


def test_short_evidence_rejected():
    """Evidence with < 8 non-whitespace chars is rejected."""
    patch = "@@ -1,0 +1,1 @@\n+added content here"
    files = [_make_file(filename="src/app.ts", patch=patch)]
    finding = _make_finding(
        title="Short evidence",
        file="src/app.ts",
        line=1,
        evidence="short",  # only 5 chars
        suggestion="short",  # only 5 chars
    )
    assert verify_findings([finding], files) == []


def test_path_normalization_handles_backslashes():
    """File paths with backslashes are normalized for comparison."""
    patch = "@@ -1,0 +1,1 @@\n+added content here"
    files = [_make_file(filename="src\\app.ts", patch=patch)]
    finding = _make_finding(
        title="Windows path",
        file="src/app.ts",
        line=1,
        evidence="Added content here now.",
        suggestion="Review the added content.",
    )
    verified = verify_findings([finding], files)
    assert len(verified) == 1


# ---------------------------------------------------------------------------
# 10. Integration: full pipeline
# ---------------------------------------------------------------------------

def test_full_pipeline_integration():
    """Multiple filters work together: line-check, evidence, style downgrade,
    test-coverage adjustment, dedup."""
    patch_auth = (
        "@@ -1,0 +1,4 @@\n"
        "+function login(user, pass) {\n"
        "+  const q = 'SELECT * FROM users WHERE name=' + user;\n"
        "+  db.query(q);\n"
        "+}\n"
    )
    patch_test = "@@ -1,0 +1,2 @@\n+import { login } from '../auth';\n+test('login', () => {});\n"
    patch_style = "@@ -1,0 +1,1 @@\n+const x = 1;\n"

    files = [
        _make_file(filename="src/auth.ts", patch=patch_auth, additions=15, deletions=0, risk_score=85),
        _make_file(filename="src/auth.test.ts", patch=patch_test, additions=10, deletions=0),
        _make_file(filename="src/style.ts", patch=patch_style, additions=5, deletions=0, risk_score=20),
    ]

    findings = [
        # Real issue — SQL injection, should survive with adjusted confidence
        _make_finding(
            title="SQL injection in login function",
            severity="P1",
            confidence=0.82,
            category="security",
            file="src/auth.ts",
            line=2,
            evidence="User input concatenated directly into SQL query.",
            suggestion="Use parameterized queries for user input.",
        ),
        # Style issue — should be downgraded to P3 + [建议]
        _make_finding(
            title="Inconsistent spacing around assignment",
            severity="P3",
            confidence=0.7,
            category="style",
            file="src/style.ts",
            line=1,
            evidence="Const assignment is formatted inconsistently.",
            suggestion="Run formatter to normalize const assignment formatting.",
        ),
        # Phantom line — should be removed
        _make_finding(
            title="Something at line 99",
            severity="P2",
            confidence=0.8,
            category="logic",
            file="src/auth.ts",
            line=99,
            evidence="This line does not exist in the diff.",
            suggestion="Remove the nonexistent code.",
        ),
    ]

    verified = verify_findings(findings, files)

    # Phantom finding removed; style downgraded but kept; SQL finding kept
    assert len(verified) == 2

    sql_finding = next(f for f in verified if f.category == "security")
    style_finding = next(f for f in verified if f.category == "style")

    # SQL finding: auth.ts has auth.test.ts → confidence reduced by 5% (0.82 * 0.95 = 0.779)
    assert sql_finding.confidence == pytest.approx(0.779, rel=1e-6)
    assert sql_finding.severity == "P1"

    # Style finding: downgraded (style → P3, then tiny change also triggers but already P3)
    assert style_finding.severity == "P3"
    assert style_finding.tag == "[建议]"
