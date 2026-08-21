# 配置说明

UthCode 使用两个互相独立的配置文件：`config.toml` 管理模型，`permissions.toml` 管理工具权限规则。Provider 只允许在用户级配置中定义；项目配置只能选择用户级 Provider 和模型参数。API Key 可直接写入用户级 `api_key`（literal），或使用 `env:VARIABLE_NAME` 读取当前进程环境变量；项目配置禁止凭据和端点。

## `config.toml`

用户配置位于 `~/.uthcode/config.toml`，项目配置位于 `<项目目录>/.uthcode/config.toml`。

真实模型示例：

```toml
default_model = "my-provider/chat"
default_permission_mode = "default"

[providers.my-provider]
kind = "openai_compat"
base_url = "https://your-provider.example/v1"
api_key = "env:MY_PROVIDER_API_KEY"

[models."my-provider/chat"]
provider = "my-provider"
remote_id = "your-model-id"
display_name = "My Chat Model"
context_window = 128000
max_output_tokens = 4096
reasoning_effort = "medium"
```

使用 env 写法时，在启动 UthCode 的终端中设置密钥：

```powershell
$env:MY_PROVIDER_API_KEY = "your-api-key"
```

也可以在用户配置中写入 `api_key = "literal-secret"`。两种形式都会在内部保存为不可序列化的脱敏凭据；真实值不会进入 Prompt、History、Event、diagnostics 或 Eval artifact。`env:` 后必须是明确的环境变量名，变量缺失或为空会受控失败；UthCode 不会猜测变量名。

支持的 `kind`：

| 值 | 说明 |
| --- | --- |
| `anthropic` | Anthropic Messages API |
| `openai_responses` | OpenAI Responses API |
| `openai_compat` | OpenAI-compatible API，需要 `base_url` |
| `fake` | 离线体验和测试 |

用户配置中的 `default_permission_mode` 只能是 `default` 或 `auto`；`full_access` 只能在当前运行中选择。项目配置可以选择用户已信任的 Provider、模型和非敏感模型参数，但不能定义 Provider、修改端点或密钥来源，也不能设置默认权限模式。

模型表的键是逻辑 Model Profile ID，仅用于 `/model`、TUI 和 `/status`。`remote_id` 才会发送给远端；远端模型名称由 Provider 最终校验，不根据名称子串推断。`reasoning_effort` 可省略（省略时请求不带 reasoning），或使用 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`；当前只对 OpenAI Responses 和 OpenAI-compatible 的非 `none` 值启用映射，无法支持的 Provider 会在配置/构造阶段失败。

### Context Window 与 Provider 限制

`models.<model-ref>.context_window` 是用户显式配置的输入运行上限，必须是正整数。项目配置只能在用户配置已经存在该值时保持或收紧，不能补造缺失值或放大用户值。Provider 可以在运行时提供更小的可靠 `max_input_tokens`，最终请求使用两者中更紧的上限；`max_output_tokens` 和可选的 combined-context 限制分别校验，未知维度不会被猜测或伪造。

如果用户没有配置 `context_window`，且 Provider 也没有可靠输入上限，当前模型会在发送前 fail closed；UthCode 不使用固定窗口、型号名称推断或官方随包窗口表作为回退。每次普通请求、工具续环、手动 Compact、L4/L5 和 overflow retry 都会按最终 Provider-visible request 重新执行 Hard Gate。

## `permissions.toml`

用户规则位于 `~/.uthcode/permissions.toml`，项目规则位于 `<项目目录>/.uthcode/permissions.toml`。规则在新建一次运行时载入，运行中修改不会立即生效。

Policy 示例：

```toml
[policy]

[[policy.rules]]
id = "ask-before-readme-write"
decision = "ask"
tool = "WriteFile"
action = "write"
effect = "write"
resource = "README.md"
scope = "inside"
```

需要在所有权限模式下生效的显式保护规则写入 Guard：

```toml
[guard]

[[guard.rules]]
id = "deny-env-read"
decision = "deny"
effect = "read"
resource_regex = "(^|/)\\.env$"
```

规则字段：

| 字段 | 可用值或含义 |
| --- | --- |
| `decision` | `allow`、`ask`、`deny`；显式 Guard 通常用于 `ask` 或 `deny` |
| `tool` / `action` | 匹配工具名与动作名 |
| `effect` | `read`、`write`、`destructive`、`external`、`unknown` |
| `scope` | `inside`、`outside`、`unknown` |
| `resource` | 精确资源路径；配合 `resource_prefix = true` 可匹配其下资源 |
| `resource_regex` | 对规范化资源摘要进行正则匹配，不能与 `resource` 同时使用 |

每条规则至少填写一个匹配字段。更具体或更靠近当前目录的规则优先；同优先级冲突时按 `deny`、`ask`、`allow` 收紧。
