# 配置说明

UthCode 使用两个互相独立的配置文件：`config.toml` 管理模型，`permissions.toml` 管理工具权限规则。API Key 真实值只能放在环境变量中。

## `config.toml`

用户配置位于 `~/.uthcode/config.toml`，项目配置位于 `<项目目录>/.uthcode/config.toml`。

真实模型示例：

```toml
model = "my-provider/chat"
default_permission_mode = "default"

[providers.my-provider]
kind = "openai_compat"
base_url = "https://your-provider.example/v1"
api_key_env = "MY_PROVIDER_API_KEY"

[models."my-provider/chat"]
provider = "my-provider"
model = "your-model-id"
label = "My Chat Model"
max_output_tokens = 4096
```

在启动 UthCode 的终端中设置密钥：

```powershell
$env:MY_PROVIDER_API_KEY = "your-api-key"
```

支持的 `kind`：

| 值 | 说明 |
| --- | --- |
| `anthropic` | Anthropic Messages API |
| `openai_responses` | OpenAI Responses API |
| `openai_compat` | OpenAI-compatible API，需要 `base_url` |
| `fake` | 离线体验和测试 |

用户配置中的 `default_permission_mode` 只能是 `default` 或 `auto`；`full_access` 只能在当前运行中选择。项目配置可以选择用户已信任的 Provider、模型和非敏感模型参数，但不能定义 Provider、修改端点或密钥来源，也不能设置默认权限模式。

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
