import re

from app.analyzer.diff_parser import extract_added_lines, should_review_file
from app.models.schemas import ChangedFile


HIGH_RISK_PATHS = {
    "auth": "涉及认证或授权代码",
    "permission": "涉及权限逻辑",
    "payment": "涉及支付代码",
    "migration": "涉及数据库迁移代码",
    "security": "涉及安全敏感代码",
    "crypto": "涉及加密相关代码",
    "database": "涉及数据库代码",
    "config": "修改运行时配置",
}

RISK_PATTERNS = [
    (re.compile(r"\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b", re.I), "新增 SQL 或数据库查询逻辑", 14),
    (re.compile(r"allow|deny|role|admin|token|jwt|session", re.I), "修改访问控制相关逻辑", 18),
    (re.compile(r"except\s*:|catch\s*\(|try\s*\{|raise|throw", re.I), "修改错误处理行为", 10),
    (re.compile(r"fetch\(|axios|httpx|requests\.|http\.", re.I), "新增网络请求行为", 10),
    (re.compile(r"TODO|FIXME|temporary|hack", re.I), "包含临时实现标记", 8),
    (re.compile(r"return\s+true|return\s+None|return\s+null", re.I), "新增宽松或可空的提前返回", 12),
]


def classify_files(files: list[ChangedFile]) -> list[ChangedFile]:
    total_files = len(files)
    has_test_change = any(_is_test_file(item.filename) for item in files)
    classified: list[ChangedFile] = []

    for item in files:
        score = min(35, item.additions + item.deletions)
        reasons: list[str] = []
        normalized = item.filename.lower().replace("\\", "/")

        if not should_review_file(item.filename, total_files=total_files):
            item.risk_score = 5
            item.risk_level = "low"
            item.risk_reasons = ["生成文件、二进制文件或 lock 文件，评审价值较低"]
            classified.append(item)
            continue

        for token, reason in HIGH_RISK_PATHS.items():
            if token in normalized:
                score += 18
                reasons.append(reason)

        if item.additions + item.deletions >= 120:
            score += 15
            reasons.append("大规模 diff 增加评审风险")
        elif item.additions + item.deletions >= 40:
            score += 8
            reasons.append("中等规模行为变更")

        added_text = "\n".join(str(line["content"]) for line in extract_added_lines(item.patch))
        for pattern, reason, weight in RISK_PATTERNS:
            if pattern.search(added_text):
                score += weight
                reasons.append(reason)

        if not has_test_change and not _is_test_file(item.filename):
            score += 12
            reasons.append("该 PR 没有修改测试文件")

        if normalized.endswith((".json", ".yml", ".yaml", ".toml")):
            score += 6
            reasons.append("配置或依赖行为可能发生变化")

        if item.context:
            if item.context.related_tests and not _is_test_file(item.filename):
                reasons.append("已找到相关测试文件，可用于验证变更影响")
            elif not has_test_change and not _is_test_file(item.filename):
                score += 6
                reasons.append("未在仓库上下文中找到直接相关测试")
            if any(path.startswith(".github/") for path in item.context.related_files):
                score += 4
                reasons.append("相关上下文触达 CI 或仓库自动化配置")
            if len(item.context.related_files) >= 3:
                score += 4
                reasons.append("存在多个相邻或同名相关文件，影响面需要核对")

        item.risk_score = max(0, min(100, score))
        item.risk_level = _level(item.risk_score)
        item.risk_reasons = _dedupe(reasons) or ["小范围独立变更"]
        classified.append(item)

    return sorted(classified, key=lambda file: file.risk_score, reverse=True)


def _level(score: int) -> str:
    if score >= 85:
        return "critical"
    if score >= 65:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _is_test_file(filename: str) -> bool:
    path = filename.lower()
    return "test" in path or "spec" in path or path.endswith(("_test.py", ".test.ts", ".spec.ts"))


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
