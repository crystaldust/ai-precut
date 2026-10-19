# 更新记录

版本号规则：`CFBundleShortVersionString` 取 `pyproject.toml` 的 `version`；
`CFBundleVersion`（构建号）取环境变量 `AICUT_BUILD_NUMBER`，否则取 git 提交数（见 `packaging/version.py`）。

## 0.1.0

首个内部试用版：素材 → 三路分析 → 片段浏览 → 覆盖式选段 → 剪映工程。

### 升级须知

- 当前构建是 adhoc 签名（没有设置 `CODESIGN_IDENTITY`）。每次升级后 macOS 会把它当成一个新 App：
  第一次打开要重新允许访问「钥匙串」里保存的 API Key，以及「文稿」目录。
  想避免重复授权，按 `docs/PACKAGING.md` 的「稳定签名身份（自签证书）」一节建一个固定的签名身份。
- 项目数据（`~/Documents/AI粗剪/`）和凭证不随 App 删除，升级后照常可用。
