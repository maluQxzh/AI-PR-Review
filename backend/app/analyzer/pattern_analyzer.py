"""Pattern-based static analysis for PR code review.

Detects known bug patterns, security vulnerabilities, and anti-patterns
through regex matching on diff patches. Language-aware — different rules
apply to Python, JavaScript/TypeScript, Go, Java, and Rust.

Design: data-driven. Each rule is a PatternRule dataclass; analyze_patterns()
iterates files, detects language, applies applicable rules, and returns
structured Finding objects.
"""

import re
from dataclasses import dataclass

from app.analyzer.diff_parser import extract_added_lines, language_from_filename
from app.analyzer.risk_classifier import is_test_file
from app.models.schemas import ChangedFile, Finding


@dataclass
class PatternRule:
    """A single bug/anti-pattern detection rule."""

    pattern_id: str  # unique identifier, e.g. "py_bare_except"
    languages: list[str]  # applicable languages; empty list = cross-language
    severity: str  # P0, P1, P2, P3
    category: str  # security, logic, test, performance, maintainability
    regex: re.Pattern  # compiled regex to match against added lines
    title_template: str  # Chinese title
    evidence_template: str  # Chinese evidence description
    impact_template: str  # Chinese impact description
    suggestion_template: str  # actionable Chinese suggestion
    comment_draft_template: str  # Chinese PR comment
    confidence: float = 0.72
    skip_test_files: bool = True


# ── Python patterns ────────────────────────────────────────────────

PY_PATTERNS: list[PatternRule] = [
    PatternRule(
        pattern_id="py_bare_except",
        languages=["python"],
        severity="P2",
        category="maintainability",
        regex=re.compile(r"except\s*:\s*$|except\s+Exception\s*:\s*$"),
        title_template="裸 except 或宽泛 Exception 捕获可能掩盖错误",
        evidence_template="文件中使用了裸 except: 或捕获了过于宽泛的 Exception，会吞没 KeyboardInterrupt 和 SystemExit，并掩盖未预期的错误。",
        impact_template="异常被静默吞没后，调用方无法感知失败，可能导致数据不一致或功能静默失效。",
        suggestion_template="替换为捕获具体异常类型，如 except ValueError: 或 except (ValueError, KeyError):。在最外层记录日志后再决定是否吞没。",
        comment_draft_template="建议将 `except:` 或 `except Exception:` 替换为具体的异常类型，避免掩盖未预期的错误。",
    ),
    PatternRule(
        pattern_id="py_mutable_default",
        languages=["python"],
        severity="P2",
        category="logic",
        regex=re.compile(r"def\s+\w+\(.*=\s*\[\]|def\s+\w+\(.*=\s*\{\}"),
        title_template="可变对象作为函数默认参数会导致状态共享",
        evidence_template="函数默认参数使用了可变对象（[] 或 {}），Python 在函数定义时只计算一次默认值，所有调用共享同一实例。",
        impact_template="多次调用该函数会累积副作用，导致难以调试的状态污染问题。",
        suggestion_template="将默认值改为 None，并在函数体内进行初始化：if arg is None: arg = []。",
        comment_draft_template="可变默认参数存在状态共享风险，建议改为 `None` 并在函数体内初始化。",
    ),
    PatternRule(
        pattern_id="py_eval_exec",
        languages=["python"],
        severity="P1",
        category="security",
        regex=re.compile(r"\beval\(|\bexec\("),
        title_template="使用 eval/exec 存在代码注入风险",
        evidence_template="代码中调用了 eval() 或 exec()，可能执行不可信的动态代码。",
        impact_template="如果输入来自用户或外部数据，攻击者可以执行任意代码，导致远程代码执行 (RCE)。",
        suggestion_template="优先使用安全替代方案：ast.literal_eval() 处理字面量、getattr/setattr 动态访问属性、或用显式的映射字典替代动态代码。",
        comment_draft_template="eval/exec 存在严重安全隐患，请确认输入来源可信或改用 ast.literal_eval()。",
    ),
    PatternRule(
        pattern_id="py_open_no_with",
        languages=["python"],
        severity="P2",
        category="logic",
        regex=re.compile(r"(?<!\bwith\s)\bopen\([^)]+\)"),
        title_template="open() 未使用 with 语句可能导致资源泄漏",
        evidence_template="open() 调用未包裹在 with 语句或 try/finally 块中，文件句柄可能不会被正确关闭。",
        impact_template="长时间运行时文件句柄泄漏会导致 Too many open files 错误，或写入内容未刷盘导致数据丢失。",
        suggestion_template="使用 with open(...) as f: 语句确保文件自动关闭，或显式在 finally 块中调用 f.close()。",
        comment_draft_template="建议使用 `with open()` 语句确保文件句柄被自动关闭。",
    ),
    PatternRule(
        pattern_id="py_os_system",
        languages=["python"],
        severity="P1",
        category="security",
        regex=re.compile(r"os\.system\(|subprocess\.(call|run)\(.*shell\s*=\s*True"),
        title_template="使用 os.system 或 shell=True 存在命令注入风险",
        evidence_template="使用了 os.system() 或 subprocess 调用且 shell=True，如果参数中包含用户输入，可能被注入额外命令。",
        impact_template="攻击者可以通过注入分号、管道等 shell 元字符执行任意系统命令。",
        suggestion_template="使用 subprocess.run(cmd_list, shell=False)，将命令和参数作为列表传递，避免 shell 解析。",
        comment_draft_template="命令执行存在注入风险，建议使用 `subprocess.run(..., shell=False)` 并传递参数列表。",
    ),
    PatternRule(
        pattern_id="py_pickle_load",
        languages=["python"],
        severity="P1",
        category="security",
        regex=re.compile(r"pickle\.(load|loads)\("),
        title_template="pickle 反序列化不可信数据存在 RCE 风险",
        evidence_template="使用了 pickle.load/loads 进行反序列化，pickle 格式可以执行任意 Python 代码。",
        impact_template="如果反序列化的数据来自不可信来源（网络、用户上传），攻击者可以构造恶意 pickle 数据执行任意代码。",
        suggestion_template="改用 JSON、protobuf 或 MessagePack 等安全序列化格式。如必须使用 pickle，确保数据来源绝对可信且使用 HMAC 签名验证。",
        comment_draft_template="pickle 反序列化存在 RCE 风险，请确认数据来源可信或改用 JSON。",
    ),
    PatternRule(
        pattern_id="py_yaml_unsafe",
        languages=["python"],
        severity="P1",
        category="security",
        regex=re.compile(r"yaml\.load\((?!.*SafeLoader)(?!.*CSafeLoader)"),
        title_template="yaml.load() 未使用 SafeLoader 存在任意代码执行风险",
        evidence_template="使用了 yaml.load() 但未指定 SafeLoader 或 CSafeLoader，默认的 Loader 可以构造任意 Python 对象。",
        impact_template="攻击者可以构造恶意 YAML 文件执行任意 Python 代码。",
        suggestion_template="改用 yaml.safe_load() 或 yaml.load(stream, Loader=yaml.SafeLoader)。",
        comment_draft_template="建议使用 `yaml.safe_load()` 替代 `yaml.load()`。",
    ),
    PatternRule(
        pattern_id="py_hardcoded_secret",
        languages=["python"],
        severity="P0",
        category="security",
        regex=re.compile(r"(password|secret|token|api_key|apikey|passwd)\s*=\s*['\"][^'\"]{6,}['\"]", re.I),
        title_template="代码中硬编码了敏感凭证",
        evidence_template="检测到硬编码的密码/密钥/Token。这些值应该通过环境变量或密钥管理服务注入。",
        impact_template="凭证提交到版本控制系统后，任何有仓库访问权限的人都能获取，且轮换困难。",
        suggestion_template="将凭证移至环境变量，使用 os.getenv('SECRET_KEY') 读取，并在 .env.example 中标注但不包含实际值。",
        comment_draft_template="检测到硬编码凭证，请移至环境变量或密钥管理服务。",
        confidence=0.88,
    ),
    PatternRule(
        pattern_id="py_assert_prod",
        languages=["python"],
        severity="P3",
        category="maintainability",
        regex=re.compile(r"\bassert\b"),
        title_template="assert 在生产环境可能被优化掉",
        evidence_template="代码中使用了 assert 语句。Python 在 -O 优化模式下会移除所有 assert，因此不应依赖 assert 做业务校验。",
        impact_template="在生产环境以 -O 运行或某些部署环境（如某些 AWS Lambda 配置）中，assert 会被跳过，导致校验逻辑失效。",
        suggestion_template="将业务逻辑校验改为显式 raise ValueError/TypeError，assert 仅限于测试和调试用途。",
        comment_draft_template="assert 在生产环境可能被跳过，建议改用显式的 raise。",
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="py_thread_sleep",
        languages=["python"],
        severity="P3",
        category="performance",
        regex=re.compile(r"time\.sleep\("),
        title_template="time.sleep() 阻塞调用可能影响吞吐量",
        evidence_template="代码中使用了 time.sleep() 进行固定等待，阻塞线程期间无法处理其他任务。",
        impact_template="在高并发或异步服务中，固定阻塞等待会降低吞吐量，增加请求排队时间。",
        suggestion_template="考虑使用 asyncio.sleep()（异步上下文）或带超时的轮询/回调机制替代固定等待。",
        comment_draft_template="`time.sleep()` 会阻塞线程，考虑异步替代方案。",
    ),
    PatternRule(
        pattern_id="py_unchecked_dict_get",
        languages=["python"],
        severity="P3",
        category="logic",
        regex=re.compile(r"\.get\([^)]+\)(?!\s*(?:or|\|)\s)"),
        title_template="dict.get() 返回值未经空值检查",
        evidence_template="使用了 dict.get() 但未检查返回值是否为 None，可能在后续使用中触发 AttributeError 或 TypeError。",
        impact_template="如果 key 不存在且没有默认值，get() 返回 None，后续对 None 的操作会导致运行时崩溃。",
        suggestion_template="使用 dict.get(key, default_value) 显式提供默认值，或在获取后添加 if result is not None: 检查。",
        comment_draft_template="`dict.get()` 可能返回 None，建议显式提供默认值或添加空值检查。",
    ),
]

# ── JavaScript / TypeScript patterns ─────────────────────────────────

JS_PATTERNS: list[PatternRule] = [
    PatternRule(
        pattern_id="js_loose_equality",
        languages=["javascript", "typescript"],
        severity="P2",
        category="logic",
        regex=re.compile(r"[^=!]==[^=]"),
        title_template="使用 == 而非 === 可能导致意外类型转换",
        evidence_template="代码中使用了宽松相等比较 ==。JavaScript 的 == 会进行隐式类型转换，产生非直觉的结果（如 0 == '' 为 true）。",
        impact_template="隐式类型转换可能导致边界条件判断错误，引发业务逻辑缺陷。",
        suggestion_template="统一使用 === 和 !== 进行严格比较。仅在明确需要类型转换的场景使用 ==，并添加注释说明原因。",
        comment_draft_template="建议使用 `===` 替代 `==`，避免隐式类型转换。",
    ),
    PatternRule(
        pattern_id="js_inner_html",
        languages=["javascript", "typescript"],
        severity="P1",
        category="security",
        regex=re.compile(r"\.innerHTML\s*="),
        title_template="直接设置 innerHTML 存在 XSS 风险",
        evidence_template="使用了 .innerHTML = 直接设置 HTML 内容。如果内容包含用户输入，可能被注入恶意脚本。",
        impact_template="攻击者可以注入 <script> 标签或事件处理器，窃取用户 Cookie、会话 Token 或执行任意操作。",
        suggestion_template="使用 .textContent（纯文本）、DOMPurify 净化输入、或使用框架的安全绑定（React 的 JSX、Vue 的 v-text）。",
        comment_draft_template="innerHTML 存在 XSS 风险，建议使用 textContent 或经过净化的内容。",
    ),
    PatternRule(
        pattern_id="js_eval",
        languages=["javascript", "typescript"],
        severity="P1",
        category="security",
        regex=re.compile(r"\beval\("),
        title_template="使用 eval 存在代码注入风险",
        evidence_template="代码中调用了 eval()，如果参数来自不可信来源可能执行任意代码。",
        impact_template="攻击者可以注入恶意代码，在当前域下执行任意操作。",
        suggestion_template="避免使用 eval。对于 JSON 解析使用 JSON.parse()，对于动态属性访问使用 obj[propName]。",
        comment_draft_template="eval() 存在严重安全隐患，请使用安全替代方案。",
    ),
    PatternRule(
        pattern_id="js_hardcoded_secret",
        languages=["javascript", "typescript"],
        severity="P0",
        category="security",
        regex=re.compile(r"(password|secret|token|apiKey|api_key|apikey)\s*[:=]\s*['\"][^'\"]{6,}['\"]", re.I),
        title_template="代码中硬编码了敏感凭证",
        evidence_template="检测到硬编码的密码/密钥/Token。前端代码中的凭证对所有人可见。",
        impact_template="提交到版本控制后所有仓库访问者都能获取凭证，且前端打包后凭证明文暴露在浏览器中。",
        suggestion_template="将凭证移至环境变量（服务端）或密钥管理服务。前端不应存储任何长期密钥。",
        comment_draft_template="检测到硬编码凭证，前端不应包含任何密钥或 Token。",
        confidence=0.90,
    ),
    PatternRule(
        pattern_id="js_document_write",
        languages=["javascript", "typescript"],
        severity="P1",
        category="security",
        regex=re.compile(r"document\.write\("),
        title_template="document.write 存在 XSS 风险且性能差",
        evidence_template="使用了 document.write()，它会同步阻塞 DOM 解析，且容易引入 XSS 漏洞。",
        impact_template="document.write 会清空整个文档（页面已加载后调用时），或被注入恶意内容。现代浏览器可能完全忽略来自非解析器的 document.write。",
        suggestion_template="使用 DOM API（createElement + appendChild）或 innerHTML + DOMPurify 替代。",
        comment_draft_template="`document.write()` 存在 XSS 风险且性能差，建议使用 DOM API。",
    ),
    PatternRule(
        pattern_id="js_function_constructor",
        languages=["javascript", "typescript"],
        severity="P1",
        category="security",
        regex=re.compile(r"new\s+Function\("),
        title_template="new Function() 类似 eval 存在代码注入风险",
        evidence_template="使用了 new Function() 动态构造函数，等价于 eval，可以执行任意 JavaScript 代码。",
        impact_template="如果参数来自不可信来源，攻击者可以执行任意代码。",
        suggestion_template="避免动态构造可执行代码。使用函数映射表（dispatch map）或策略模式替代。",
        comment_draft_template="`new Function()` 等同于 eval，存在代码注入风险。",
    ),
    PatternRule(
        pattern_id="js_settimeout_string",
        languages=["javascript", "typescript"],
        severity="P1",
        category="security",
        regex=re.compile(r"setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"]"),
        title_template="setTimeout/setInterval 传入字符串类似 eval",
        evidence_template="setTimeout 或 setInterval 的第一个参数是字符串而非函数，浏览器会将其当作代码执行。",
        impact_template="类似于 eval，如果字符串由外部输入拼接而成，存在代码注入风险。",
        suggestion_template="将字符串改为箭头函数或函数引用：setTimeout(() => { ... }, delay)。",
        comment_draft_template="setTimeout 传入字符串类似 eval，请使用函数引用。",
    ),
    PatternRule(
        pattern_id="js_console_prod",
        languages=["javascript", "typescript"],
        severity="P3",
        category="maintainability",
        regex=re.compile(r"console\.(log|warn|error|debug)\("),
        title_template="生产代码中保留 console 日志输出",
        evidence_template="代码中包含了 console.log/warn/error/debug 调用，可能在开发调试后遗留。",
        impact_template="生产环境中大量日志输出可能影响性能，且可能泄露敏感数据到浏览器控制台。",
        suggestion_template="使用结构化日志库（如 winston、pino）并设置日志级别；确保敏感数据不会输出到 console。",
        comment_draft_template="生产代码中的 console 调用建议替换为结构化日志或移除。",
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="js_dangerously_html",
        languages=["javascript", "typescript"],
        severity="P1",
        category="security",
        regex=re.compile(r"dangerouslySetInnerHTML"),
        title_template="dangerouslySetInnerHTML 存在 XSS 风险",
        evidence_template="React 组件中使用了 dangerouslySetInnerHTML，如其内容包含用户输入则存在 XSS 风险。",
        impact_template="未净化的内容通过 dangerouslySetInnerHTML 渲染可能导致 XSS 攻击。",
        suggestion_template="在使用前通过 DOMPurify 或类似库净化 HTML 内容。评估是否可以改用纯文本渲染。",
        comment_draft_template="`dangerouslySetInnerHTML` 请确认内容已净化，或改用文本渲染。",
    ),
    PatternRule(
        pattern_id="js_sql_inject_concat",
        languages=["javascript", "typescript"],
        severity="P1",
        category="security",
        regex=re.compile(r"(SELECT|INSERT|UPDATE|DELETE).*\+.*|\+\s*.*(SELECT|INSERT|UPDATE|DELETE)", re.I),
        title_template="SQL 字符串拼接存在注入风险",
        evidence_template="SQL 查询通过字符串拼接或模板字面量构造，如果包含用户输入可能被注入恶意 SQL。",
        impact_template="攻击者可以通过构造特定输入绕过认证、窃取数据或破坏数据库。",
        suggestion_template="使用参数化查询或 ORM 的安全方法替代字符串拼接：db.query('SELECT * FROM t WHERE id = ?', [id])。",
        comment_draft_template="SQL 字符串拼接存在注入风险，建议使用参数化查询。",
        confidence=0.82,
    ),
    PatternRule(
        pattern_id="js_missing_key_prop",
        languages=["javascript", "typescript"],
        severity="P3",
        category="maintainability",
        regex=re.compile(r"\.map\(.*=>\s*(?:\(|<)"),
        title_template=".map() 渲染列表可能缺少 key 属性",
        evidence_template="在 .map() 中渲染组件/元素时可能未提供 key 属性，React 需要一个稳定的 key 来高效更新列表。",
        impact_template="缺少 key 会导致 React 更新时不必要的 DOM 重建，影响性能并可能导致组件状态丢失。",
        suggestion_template="为列表中的每个项目添加唯一的 key 属性：key={item.id}。避免使用数组索引作为 key（除非列表是静态的）。",
        comment_draft_template="列表渲染请确认已添加唯一的 `key` 属性。",
        confidence=0.60,
    ),
    PatternRule(
        pattern_id="js_localstorage_sensitive",
        languages=["javascript", "typescript"],
        severity="P2",
        category="security",
        regex=re.compile(r"localStorage\.setItem\(|sessionStorage\.setItem\("),
        title_template="敏感数据不宜存储在 localStorage/sessionStorage",
        evidence_template="数据被写入 localStorage 或 sessionStorage，存储在这些位置的数据在 XSS 攻击下可被恶意脚本读取。",
        impact_template="Token、个人信息等敏感数据在 XSS 攻击下会完全暴露。localStorage 不随请求自动发送，但持久化周期长，增加了泄露窗口。",
        suggestion_template="认证 Token 优先使用 httpOnly cookie。临时数据考虑内存存储。如必须使用 Web Storage，确保数据已加密且不包含敏感信息。",
        comment_draft_template="敏感数据不宜存储在 localStorage，建议使用 httpOnly cookie。",
    ),
]

# ── Go patterns ──────────────────────────────────────────────────────

GO_PATTERNS: list[PatternRule] = [
    PatternRule(
        pattern_id="go_unchecked_err",
        languages=["go"],
        severity="P2",
        category="logic",
        regex=re.compile(r"(\w+),\s*_\s*:=\s*\w+\(|^\s*\w+\(.*\)\s*$"),
        title_template="error 返回值未被检查",
        evidence_template="函数返回的 error 被赋值为 _（空白标识符），或调用返回 error 的函数后未检查 err 值。",
        impact_template="操作失败被静默忽略，后续代码在不确定状态下继续执行，可能导致数据损坏。",
        suggestion_template="检查并处理 error：if err != nil { return fmt.Errorf(\"op: %w\", err) }。不建议将 error 赋值给 _。",
        comment_draft_template="error 返回值未被检查，请添加 err != nil 判断。",
    ),
    PatternRule(
        pattern_id="go_defer_in_loop",
        languages=["go"],
        severity="P2",
        category="logic",
        regex=re.compile(r"\bdefer\s+"),
        title_template="defer 在循环中使用可能导致资源泄漏",
        evidence_template="defer 语句位于循环体内。defer 在函数返回时才执行，而非循环迭代结束时，因此循环中积累的 defer 会导致资源累积。",
        impact_template="大量未及时释放的文件句柄、数据库连接或锁会导致资源耗尽。",
        suggestion_template="将循环体提取为独立函数，使 defer 在每次迭代后执行；或改用匿名函数包裹：for { func() { defer ... }() }。",
        comment_draft_template="循环中的 defer 在函数结束才执行，建议提取为独立函数。",
    ),
    PatternRule(
        pattern_id="go_panic_lib",
        languages=["go"],
        severity="P1",
        category="logic",
        regex=re.compile(r"\bpanic\("),
        title_template="库代码中使用 panic 可能导致进程崩溃",
        evidence_template="代码中调用了 panic()。在库代码中使用 panic 会终止调用方进程，而非优雅地传播错误。",
        impact_template="panic 将导致整个程序崩溃，调用方无法通过 recover 控制生命周期（除非明确文档说明）。",
        suggestion_template="将 panic 改为返回 error：return fmt.Errorf(\"reason: %w\", err)。panic 应仅用于不可恢复的初始化错误或编程错误（如数组越界）。",
        comment_draft_template="库代码中使用 panic 可能导致进程崩溃，建议改为返回 error。",
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="go_hardcoded_secret",
        languages=["go"],
        severity="P0",
        category="security",
        regex=re.compile(r"(password|secret|token|apiKey|apikey)\s*[:=]\s*\"[^\"]{6,}\"", re.I),
        title_template="代码中硬编码了敏感凭证",
        evidence_template="检测到硬编码的密码、密钥或 Token。",
        impact_template="凭证会被提交到版本控制系统，任何仓库访问者均可获取。",
        suggestion_template="通过环境变量或密钥管理服务注入凭证：os.Getenv(\"SECRET_KEY\")。",
        comment_draft_template="检测到硬编码凭证，请通过环境变量注入。",
        confidence=0.88,
    ),
    PatternRule(
        pattern_id="go_sleep",
        languages=["go"],
        severity="P3",
        category="performance",
        regex=re.compile(r"time\.Sleep\("),
        title_template="time.Sleep 阻塞 goroutine 影响并发性能",
        evidence_template="使用了 time.Sleep() 进行固定等待，阻塞当前 goroutine。",
        impact_template="在高并发场景中，固定阻塞等待会降低吞吐量。Sleep 无法响应 context 取消信号。",
        suggestion_template="使用 time.After 结合 select 语句，或使用 context.WithTimeout 实现可取消的超时等待。",
        comment_draft_template="`time.Sleep` 阻塞 goroutine，考虑使用 time.After + select。",
    ),
    PatternRule(
        pattern_id="go_sql_raw_concat",
        languages=["go"],
        severity="P2",
        category="security",
        regex=re.compile(r"(SELECT|INSERT|UPDATE|DELETE).*\+.*|\+.*(SELECT|INSERT|UPDATE|DELETE)", re.I),
        title_template="SQL 语句字符串拼接存在注入风险",
        evidence_template="SQL 查询通过字符串拼接构造，未使用参数化查询。",
        impact_template="用户输入可能包含恶意 SQL，导致注入攻击。",
        suggestion_template="使用参数化查询：db.Query(\"SELECT * FROM t WHERE id = ?\", id)。Go 的 database/sql 使用 ? 作为占位符。",
        comment_draft_template="SQL 拼接存在注入风险，请使用参数化查询（? 占位符）。",
        confidence=0.82,
    ),
    PatternRule(
        pattern_id="go_nil_deref_risk",
        languages=["go"],
        severity="P2",
        category="logic",
        regex=re.compile(r"if\s+\w+\s*!=\s*nil\s*\{[\s\S]*?\w+\.\w+"),
        title_template="nil 检查后的代码路径中可能存在 nil 解引用",
        evidence_template="某变量在检查 nil 之后仍有通过该变量访问字段/方法的路径，表明可能存在遗漏的 nil 守卫。",
        impact_template="nil 指针解引用将导致 panic，在请求处理路径中会终止当前 goroutine 并返回 500。",
        suggestion_template="确保所有访问路径都在 nil 检查覆盖范围内，或将 nil 检查提取为 guard clause 提前返回。",
        comment_draft_template="存在 nil 解引用风险，请检查所有访问路径的 nil 守卫。",
        confidence=0.65,
    ),
]

# ── Java patterns ────────────────────────────────────────────────────

JAVA_PATTERNS: list[PatternRule] = [
    PatternRule(
        pattern_id="java_empty_catch",
        languages=["java"],
        severity="P2",
        category="logic",
        regex=re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}"),
        title_template="空的 catch 块静默吞没异常",
        evidence_template="catch 块体为空，异常被完全忽略且没有任何日志记录。",
        impact_template="异常被吞没后调用方无法感知错误，排查问题变得极其困难，可能导致数据不一致。",
        suggestion_template="至少记录异常日志：logger.error(\"message\", e)。如果异常可安全忽略，在 catch 块内添加注释说明原因。",
        comment_draft_template="空 catch 块会吞没异常，请至少记录日志。",
    ),
    PatternRule(
        pattern_id="java_sysout_prod",
        languages=["java"],
        severity="P3",
        category="maintainability",
        regex=re.compile(r"System\.(out|err)\.print"),
        title_template="生产代码中使用 System.out/err 打印日志",
        evidence_template="使用了 System.out.print 或 System.err.print 而非日志框架。",
        impact_template="控制台输出难以格式化、过滤和持久化，不适合生产环境的日志管理。",
        suggestion_template="改用 SLF4J/Log4j/Logback 等日志框架：logger.info(\"message\", param)。配置适当的日志级别和输出目标。",
        comment_draft_template="建议使用日志框架替代 System.out/err 打印。",
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="java_string_concat_loop",
        languages=["java"],
        severity="P3",
        category="performance",
        regex=re.compile(r"\+\s*=\s*.*\bfor\b|\bfor\b.*\+\s*="),
        title_template="循环中使用字符串拼接导致大量临时对象",
        evidence_template="在循环中使用 += 拼接字符串，每次拼接都会创建新的 String 对象。",
        impact_template="O(n²) 的拷贝开销和大量 GC 压力，在循环次数较多时严重降低性能。",
        suggestion_template="改用 StringBuilder 或 StringBuffer（多线程场景）：StringBuilder sb = new StringBuilder(); for(...) { sb.append(s); }。",
        comment_draft_template="循环中字符串拼接建议改用 StringBuilder。",
    ),
    PatternRule(
        pattern_id="java_connection_leak",
        languages=["java"],
        severity="P2",
        category="logic",
        regex=re.compile(r"(Connection|Statement|ResultSet|PreparedStatement)\s+\w+\s*="),
        title_template="JDBC 资源可能未在 try-with-resources 中管理",
        evidence_template="创建了 Connection/Statement/ResultSet 对象但未使用 try-with-resources 包裹，存在资源泄漏风险。",
        impact_template="数据库连接泄漏最终会耗尽连接池，导致应用无法响应新的数据库请求。",
        suggestion_template="使用 try-with-resources 确保自动关闭：try (Connection conn = ...; Statement stmt = ...) { ... }。",
        comment_draft_template="JDBC 资源建议使用 try-with-resources 管理以避免连接泄漏。",
        confidence=0.65,
    ),
    PatternRule(
        pattern_id="java_string_equals_eq",
        languages=["java"],
        severity="P2",
        category="logic",
        regex=re.compile(r"\w+\s*==\s*\"|\"\s*==\s*\w+"),
        title_template="使用 == 比较字符串对象引用而非内容",
        evidence_template="使用了 == 运算符比较字符串，== 比较的是对象引用而非内容相等。",
        impact_template="即使内容相同的字符串（不同实例），== 也会返回 false，导致比较逻辑错误。",
        suggestion_template="使用 .equals() 方法比较字符串内容：str.equals(\"value\")。比较字面量时写成 \"value\".equals(str) 可避免 NullPointerException。",
        comment_draft_template="字符串比较请使用 `.equals()` 而非 `==`。",
    ),
    PatternRule(
        pattern_id="java_runtime_exec",
        languages=["java"],
        severity="P1",
        category="security",
        regex=re.compile(r"Runtime\.getRuntime\(\)\.exec\("),
        title_template="Runtime.exec 存在命令注入风险",
        evidence_template="使用了 Runtime.getRuntime().exec() 执行系统命令，如果参数来自用户输入可能被注入额外命令。",
        impact_template="攻击者可以执行任意系统命令，获取服务器控制权。",
        suggestion_template="优先使用 Java API 替代外部命令。如必须执行外部程序，使用 ProcessBuilder 并传递参数列表（不使用 shell 解析），严格白名单校验命令。",
        comment_draft_template="Runtime.exec 存在命令注入风险，建议使用 ProcessBuilder 或 Java API。",
    ),
    PatternRule(
        pattern_id="java_hardcoded_secret",
        languages=["java"],
        severity="P0",
        category="security",
        regex=re.compile(r"(password|secret|token|apiKey|apikey)\s*=\s*\"[^\"]{6,}\"", re.I),
        title_template="代码中硬编码了敏感凭证",
        evidence_template="检测到硬编码的密码、密钥或 Token。",
        impact_template="凭证会被提交到版本控制系统，任何仓库访问者均可获取。",
        suggestion_template="将凭证移至环境变量或配置文件（排除在版本控制外），通过 System.getenv() 或配置中心读取。",
        comment_draft_template="检测到硬编码凭证，请通过环境变量或配置中心注入。",
        confidence=0.88,
    ),
]

# ── Rust patterns ────────────────────────────────────────────────────

RUST_PATTERNS: list[PatternRule] = [
    PatternRule(
        pattern_id="rust_unwrap",
        languages=["rust"],
        severity="P2",
        category="logic",
        regex=re.compile(r"\.unwrap\(\)"),
        title_template="unwrap() 在非测试代码中使用可能导致 panic",
        evidence_template="代码中调用了 .unwrap()。如果 Result 为 Err 或 Option 为 None，unwrap() 会导致线程 panic。",
        impact_template="在生产路径中 panic 会导致请求失败（500 错误），而非优雅降级。",
        suggestion_template="使用 ? 运算符传播错误，或使用 .unwrap_or()/.unwrap_or_else() 提供默认值，或使用 match/if let 显式处理。",
        comment_draft_template="非测试代码中使用 `unwrap()` 可能导致 panic，建议改用 `?` 或显式处理。",
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="rust_expect_empty",
        languages=["rust"],
        severity="P3",
        category="maintainability",
        regex=re.compile(r"\.expect\(\s*\"\s*\"\s*\)"),
        title_template="expect() 的错误信息为空，不利于排查",
        evidence_template=".expect() 的消息为空字符串，触发 panic 时无法提供有用的调试信息。",
        impact_template="生产环境中出现 panic 时，空的 expect 消息无法帮助快速定位问题根因。",
        suggestion_template="为 expect() 提供描述性错误信息：.expect(\"failed to parse config file\")。",
        comment_draft_template="`expect()` 错误信息为空，建议提供描述性消息。",
    ),
    PatternRule(
        pattern_id="rust_unsafe_block",
        languages=["rust"],
        severity="P1",
        category="security",
        regex=re.compile(r"unsafe\s*\{"),
        title_template="unsafe 块绕过了 Rust 的安全保证",
        evidence_template="代码中使用了 unsafe 块。unsafe 代码绕过了编译器的借用检查和安全保证，容易出现内存安全问题。",
        impact_template="unsafe 代码中的错误（悬垂指针、数据竞争、UB）不受编译器保护，可能导致内存损坏或未定义行为。",
        suggestion_template="评估是否可以用安全 Rust 实现同等功能。如必须使用 unsafe，将 unsafe 代码封装在安全抽象后，添加 SAFETY 文档注释说明不变性条件，并编写专项测试。",
        comment_draft_template="`unsafe` 块绕过了 Rust 的安全保证，请添加 SAFETY 注释和专项测试。",
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="rust_panic_lib",
        languages=["rust"],
        severity="P1",
        category="logic",
        regex=re.compile(r"panic!\("),
        title_template="库代码中使用 panic! 可能导致进程崩溃",
        evidence_template="库代码中调用了 panic!。除非是明确不可恢复的错误，否则应将错误传播给调用方。",
        impact_template="panic 将展开栈并终止当前线程，在库中被调用方的 catch_unwind 捕获前导致不可预期的行为。",
        suggestion_template="将 panic! 改为返回 Result::Err，让调用方决定如何处理错误。",
        comment_draft_template="库代码中的 `panic!` 建议改为返回 `Result::Err`。",
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="rust_clone_loop",
        languages=["rust"],
        severity="P3",
        category="performance",
        regex=re.compile(r"\.clone\(\)"),
        title_template="循环中的 clone() 可能造成不必要的内存分配",
        evidence_template="代码中使用了 .clone()。在热路径中频繁 clone 会导致大量内存分配和释放。",
        impact_template="过多的 clone 调用增加内存分配压力和 GC（或 drop）开销，降低吞吐量。",
        suggestion_template="考虑使用引用（&T）或借用代替 clone，或使用 Rc/Arc 共享所有权。对于大型数据结构，考虑使用 Cow 延迟复制。",
        comment_draft_template="频繁的 `clone()` 调用会影响性能，考虑使用引用或共享所有权。",
        confidence=0.60,
    ),
]

# ── Cross-language patterns ──────────────────────────────────────────

XL_PATTERNS: list[PatternRule] = [
    PatternRule(
        pattern_id="xl_todo_fixme",
        languages=[],
        severity="P3",
        category="maintainability",
        regex=re.compile(r"TODO|FIXME|HACK|XXX|TEMP|WORKAROUND", re.I),
        title_template="代码中存在未解决的 TODO/FIXME 标记",
        evidence_template="检测到 TODO、FIXME 或其他临时标记。这些标记可能存在未完成的功能或已知缺陷。",
        impact_template="未跟踪的 TODO/FIXME 可能被遗忘，导致技术债务积累或功能缺失。",
        suggestion_template="为每个临时标记创建对应的 Issue/Ticket 并在标记中引用编号（如 TODO(#123)），或在本次 PR 中完成相关实现。",
        comment_draft_template="请为 TODO/FIXME 创建跟踪 Issue 或在本 PR 中解决。",
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="xl_hardcoded_secret_any",
        languages=[],
        severity="P0",
        category="security",
        regex=re.compile(r"(password|secret|token|api[_-]?key|apikey|passwd|private[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.I),
        title_template="代码中硬编码了敏感凭证（跨语言检测）",
        evidence_template="检测到疑似硬编码的密码、密钥或 Token。",
        impact_template="凭证进入版本控制后，任何有仓库权限的人都能获取，轮换困难且容易遗忘。",
        suggestion_template="使用环境变量、密钥管理服务（AWS Secrets Manager、Vault）或 CI/CD 注入方式管理凭证。立即轮换已暴露的凭证。",
        comment_draft_template="⚠️ 检测到硬编码凭证，请立即移除并使用安全方式注入。",
        confidence=0.90,
        skip_test_files=False,
    ),
    PatternRule(
        pattern_id="xl_sql_injection_concat",
        languages=[],
        severity="P1",
        category="security",
        regex=re.compile(r"(SELECT|INSERT|UPDATE|DELETE)\s+.*['\"]\s*\+|f['\"].*(SELECT|INSERT|UPDATE|DELETE)", re.I),
        title_template="SQL 查询通过字符串拼接构造，存在注入风险",
        evidence_template="SQL 语句通过字符串拼接、f-string 或模板字面量构造。",
        impact_template="SQL 注入可导致数据泄露、数据篡改或权限绕过。",
        suggestion_template="使用参数化查询/预编译语句替代字符串拼接。各语言对应方式：Python: cursor.execute(sql, params)、JS: db.query(sql, [params])、Go: db.Query(sql, args...)、Java: PreparedStatement。",
        comment_draft_template="SQL 拼接存在注入风险，请使用参数化查询。",
        confidence=0.82,
    ),
    PatternRule(
        pattern_id="xl_path_traversal",
        languages=[],
        severity="P1",
        category="security",
        regex=re.compile(r"\.\.\/|\.\.\\"),
        title_template="路径中使用了 ../ 可能存在路径穿越风险",
        evidence_template="代码中包含了 ../ 或 ..\\ 路径。如果路径由用户输入组成，可能被利用访问预期目录外的文件。",
        impact_template="攻击者可以通过 ../../../etc/passwd 等方式读取或覆盖服务器上的任意文件。",
        suggestion_template="使用 os.path.realpath() 解析并验证路径在允许的目录范围内；使用白名单限制可访问的文件名；避免将用户输入直接拼接到路径中。",
        comment_draft_template="路径中包含 `../`，请验证路径在允许范围内。",
    ),
    PatternRule(
        pattern_id="xl_command_injection",
        languages=[],
        severity="P1",
        category="security",
        regex=re.compile(r"(os\.system|exec\(|popen|spawn|ProcessBuilder|subprocess)\s*\("),
        title_template="命令执行函数参数可能存在注入风险",
        evidence_template="使用了系统命令执行函数。如果参数包含用户输入且未过滤，可能被注入额外命令。",
        impact_template="攻击者可以执行任意系统命令，获取服务器控制权或窃取敏感数据。",
        suggestion_template="避免直接执行 shell 命令。如必须执行，将命令和参数分离为列表传递，避免使用 shell 解释器，并对输入做严格白名单校验。",
        comment_draft_template="命令执行存在注入风险，建议将命令和参数分离传递。",
    ),
    PatternRule(
        pattern_id="xl_missing_null_check",
        languages=[],
        severity="P2",
        category="logic",
        regex=re.compile(r"\.(\w+)\s*\(.*\)\s*\.(\w+)\s*\("),
        title_template="链式调用缺少中间结果的空值检查",
        evidence_template="连续调用多个方法/属性（链式调用），中间结果可能为 null/None/undefined。",
        impact_template="任一层级返回空值都可能导致 NullPointerException、AttributeError 或 TypeError，使请求失败。",
        suggestion_template="使用可选链操作符（?. in JS/TS）、match/if let（Rust）、或显示中间结果并进行空值检查后再继续调用。",
        comment_draft_template="链式调用缺少空值检查，考虑使用可选链或分步判断。",
        confidence=0.65,
    ),
]

# ── Aggregate by language ────────────────────────────────────────────

_ALL_PATTERNS: dict[str, list[PatternRule]] = {
    "python": PY_PATTERNS,
    "javascript": JS_PATTERNS,
    "javascript/react": JS_PATTERNS,
    "typescript": JS_PATTERNS,  # TypeScript shares JS patterns
    "typescript/react": JS_PATTERNS,
    "go": GO_PATTERNS,
    "java": JAVA_PATTERNS,
    "rust": RUST_PATTERNS,
}


def _rules_for_language(lang: str, skip_test: bool) -> list[PatternRule]:
    """Return applicable rules for a given language."""
    rules: list[PatternRule] = list(XL_PATTERNS)
    lang_rules = _ALL_PATTERNS.get(lang.lower(), [])
    rules.extend(lang_rules)
    if skip_test:
        rules = [r for r in rules if r.skip_test_files]
    return rules


def _build_finding(rule: PatternRule, file_obj: ChangedFile, line: int,
                   matched_text: str) -> Finding:
    """Build a Finding from a matched pattern rule."""
    return Finding(
        title=rule.title_template,
        severity=rule.severity,
        confidence=rule.confidence,
        category=rule.category,
        file=file_obj.filename,
        line=line,
        evidence=f"[{rule.pattern_id}] {rule.evidence_template} 匹配内容: {matched_text[:200]}",
        impact=rule.impact_template,
        suggestion=rule.suggestion_template,
        comment_draft=rule.comment_draft_template,
    )


def analyze_patterns(files: list[ChangedFile]) -> list[Finding]:
    """Run pattern-based static analysis on changed files.

    Scans each file's added lines against language-appropriate bug patterns
    and returns structured Finding objects. One finding per rule per file
    to avoid noise.

    Returns at most 20 findings; caller may further limit.
    """
    findings: list[Finding] = []

    for file_obj in files:
        added_lines = extract_added_lines(file_obj.patch)
        if not added_lines:
            continue

        lang = language_from_filename(file_obj.filename)
        is_test = is_test_file(file_obj.filename)
        rules = _rules_for_language(lang, skip_test=is_test)
        if not rules:
            continue

        # Track which rules have already fired for this file
        fired_rules: set[str] = set()

        for rule in rules:
            if rule.pattern_id in fired_rules:
                continue
            for entry in added_lines:
                match = rule.regex.search(entry["content"])
                if match:
                    finding = _build_finding(
                        rule, file_obj,
                        int(entry["line"]),
                        entry["content"].strip(),
                    )
                    findings.append(finding)
                    fired_rules.add(rule.pattern_id)
                    break  # One finding per rule per file

    # Deduplicate by (file, pattern_id) and cap
    return _deduplicate_findings(findings)[:20]


def _deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """Remove findings with the same (file, line, title)."""
    seen: set[tuple[str, int, str]] = set()
    result: list[Finding] = []
    for f in findings:
        key = (f.file.replace("\\", "/"), f.line, f.title)
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result
