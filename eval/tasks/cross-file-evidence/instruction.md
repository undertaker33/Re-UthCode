修复 CLI 到 Application 再到 domain 的请求标识传递缺失。用户只能看到最终结果，请沿真实调用链修复它；不要让 CLI 直接绕过 Application 调用 domain，并验证正常值和缺省标识两条路径。
