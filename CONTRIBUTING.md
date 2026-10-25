# 贡献指南

欢迎修复问题、完善文档、分享使用建议。提 Issue 前请先确认：系统版本、樱响版本、复现步骤，并把截图、日志里的个人信息、路径、账号信息脱敏后再发。

## 提 Issue

- 一个问题开一个 Issue，标题写清现象，例如“网易云在自动均衡下被拉到无声”。
- 附上：Windows 版本、樱响版本（安装包 / 便携包 / 源码）、出声应用名、均衡开关与基准设置、是否手动调过音量。

## 提代码

- 只改与问题相关的文件，不要顺带重构无关代码。
- 改核心均衡逻辑（`volrider_core.py`）时，请附上离线单测结果或真机测试说明；改界面（`qt_app.py`）时，请附上截图。
- 不要提交二进制文件（安装包、便携包、图标、图片、字体请走 Releases 或由维护者上传），不要提交个人信息、密钥、账号、服务器地址。
- 提交前请确认：LICENSE 仍为 MIT、署名 YearnRiver 不变，第三方声明按需同步到 THIRD_PARTY_NOTICES.md。

## 本地运行

```bat
pip install -r requirements.txt
python qt_app.py
```

网页版：`python web\server.py`，或 `python web\server.py --mock` 在无 Windows 音频环境的机器上演示。
