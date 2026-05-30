import type { ReportResult } from "../types/report";

export const demoReport: ReportResult = {
  report_id: "demo-report",
  status: "completed",
  analysis_source: "demo",
  pr: {
    owner: "demo-org",
    repo: "checkout-service",
    number: 42,
    title: "放宽支付权限检查并新增订单查询",
    description: "用于演示的 PR，包含刻意设置的可评审风险信号。",
    author: "demo-dev",
    base_branch: "main",
    head_branch: "feature/payment-fast-path",
    html_url: "https://github.com/demo-org/checkout-service/pull/42",
  },
  summary: {
    what_changed: "这个 PR 修改了支付授权逻辑，并新增了订单查询路径。",
    risk_overview:
      "系统识别出两个高风险文件，因为变更涉及支付、权限、数据库和错误处理行为，但没有对应的测试更新。",
    review_focus: ["权限控制", "数据正确性", "测试覆盖", "错误处理"],
  },
  file_risks: [
    {
      filename: "src/payment/authorize.ts",
      status: "modified",
      additions: 28,
      deletions: 9,
      patch:
        "@@ -21,6 +21,13 @@\n+if (!user.role) {\n+  return true;\n+}\n+return hasPermission(user, 'payment:write');",
      risk_level: "critical",
      risk_score: 92,
      risk_reasons: [
        "触及支付相关代码",
        "修改了访问控制逻辑",
        "新增了宽松的空值提前返回",
        "本 PR 没有修改测试文件",
      ],
    },
    {
      filename: "src/orders/repository.ts",
      status: "modified",
      additions: 34,
      deletions: 4,
      patch:
        "@@ -10,3 +10,9 @@\n+const result = await db.query(`SELECT * FROM orders WHERE id = ${id}`);\n+return result.rows[0];",
      risk_level: "high",
      risk_score: 78,
      risk_reasons: [
        "新增 SQL 或数据库查询逻辑",
        "修改了错误处理行为",
        "本 PR 没有修改测试文件",
      ],
    },
  ],
  findings: [
    {
      title: "缺少角色的用户可能绕过权限检查",
      severity: "P1",
      confidence: 0.86,
      category: "security",
      file: "src/payment/authorize.ts",
      line: 22,
      evidence: "新增分支在 user.role 缺失时直接返回 true。",
      impact: "没有角色信息的请求可能绕过正常的支付权限检查。",
      suggestion: "将缺少角色的分支改为拒绝访问，并补充缺少角色、普通角色和管理员角色的回归测试。",
      comment_draft:
        "`user.role` 缺失时这里的提前返回似乎会允许支付写入。建议改成默认拒绝，并补充角色覆盖测试。",
    },
    {
      title: "订单查询直接用原始 id 拼接 SQL",
      severity: "P1",
      confidence: 0.79,
      category: "security",
      file: "src/orders/repository.ts",
      line: 11,
      evidence: "SQL 字符串直接将 id 插入查询语句。",
      impact: "如果路由层没有先做校验，构造过的 id 可能改变查询语义。",
      suggestion: "改用参数化查询，并测试恶意输入和空 id 输入。",
      comment_draft:
        "这个查询建议使用参数化方式，不要把 `id` 直接插入 SQL 字符串。",
    },
    {
      title: "行为变更缺少对应测试更新",
      severity: "P2",
      confidence: 0.74,
      category: "test",
      file: "src/payment/authorize.ts",
      line: 22,
      evidence: "这个 PR 没有修改测试文件。",
      impact: "缺少自动化覆盖时，权限行为后续更容易回归。",
      suggestion: "补充缺少角色、未授权用户和已授权支付写入用户的测试。",
      comment_draft: "我没有看到这个权限路径变更对应的测试覆盖。",
    },
  ],
  test_suggestions: [
    {
      title: "补充支付授权回归测试",
      reason: "这个 PR 修改了支付代码中的访问控制逻辑。",
      suggested_case: "断言缺少角色会被拒绝，且用户必须具备 payment:write 权限。",
    },
    {
      title: "补充订单查询输入测试",
      reason: "这个 PR 新增了基于 SQL 的订单查询行为。",
      suggested_case: "覆盖正常 id、空 id 和类似 SQL 的恶意输入。",
    },
  ],
  github_comment_markdown:
    "## AI PR Review 摘要\n\nPR: demo-org/checkout-service#42 - 放宽支付权限检查并新增订单查询\n\n### 变更内容\n这个 PR 修改了支付授权逻辑，并新增了订单查询路径。\n\n### 发现的问题\n- **P1 缺少角色的用户可能绕过权限检查** (`src/payment/authorize.ts:22`)\n- **P1 订单查询直接用原始 id 拼接 SQL** (`src/orders/repository.ts:11`)\n\n_由 AI PR Review 演示生成。发布前请先人工确认。_",
};
