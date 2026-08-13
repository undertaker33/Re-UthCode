# T07：把权限判断放进执行链

权限系统面对的不是一句自然语言请求，而是已经准备好的具体行动。只有知道工具、动作、影响、资源和范围，系统才能判断风险。

例如，同样是 `Bash`，读取工作目录内文件与删除目录的风险完全不同。UthCode 先由工具预检生成 `PermissionAction`，再进入权限决策：

```text
Prepared Tool Call
  → Guard
  → Policy
  → Permission Mode
  → allow / ask / deny
```

## Guard、Policy 与 Mode 各自解决什么

Guard 表示必须优先处理的保护边界；用户和项目显式 Guard 在所有模式中有效。Policy 表示针对某类行动的明确规则。没有规则命中时，Mode 提供默认策略：

- `default` 自动允许工作目录内的只读操作；
- `auto` 还自动允许目录内的普通写入；
- `full_access` 跳过内置普通 Guard、普通 Policy 与默认策略判断。

`full_access` 仍不能绕过用户或项目显式 Guard，也不能绕过灾难性操作的 circuit breaker、参数校验、工具注册、操作系统权限和第三方权限。

## Approval 不是 Sandbox

权限审批决定“UthCode 是否同意执行这个已识别的动作”，并不会降低进程本身的系统权限。尤其是 `Bash`，它使用当前 OS 用户权限执行，因此 Permission Approval 不能替代容器、虚拟机或操作系统沙箱。

## 临时授权为什么不自动持久化

用户可以仅批准一次，也可以在条件明确时为当前 Run 提供 Session Grant。后者只保存在内存中，不会偷偷写成长期规则。需要持久行为时，应由用户显式编辑 `permissions.toml`。

权限系统把“约束”放到了行动发生之前。最后一章将在同一个 Runtime 中加入规划与任务进度，而不建立第二套执行引擎。
