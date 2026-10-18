# Windows 草稿兼容性验证（一次性，约 10 分钟）

## 为什么要测这个

我们的方案依赖一件事：**程序生成的明文剪映草稿，剪映能读。**

- macOS 上已经实测通过（剪映 11.0 能列出、能打开，11.6 打开后会自动升级加密）；
- Windows 上**没有验证过**。而剪映从 6.0 起把草稿存成 AES 密文，Windows 最新版是 6.7/7.0。
- 如果 Windows 也认明文草稿 → 双平台完整支持；
- 如果不认 → Windows 只能降级交付（见文末）。

**这一个测试的结果，决定 Windows 版要不要投入。**

---

## 准备

1. Windows 10/11，已安装剪映专业版（6.x 或 7.x），**先打开一次再退出**（让它建好草稿目录）；
2. 装 Python 3.10+（安装时勾选 *Add Python to PATH*）；
3. 把整个 `windows-spike` 文件夹拷到 Windows。

## 操作

**方式一（推荐）**：双击 `RUN_TEST.bat`，把任意一个 mp4 拖进窗口回车。

> 视频随便挑一个，**建议 ≥ 6 秒**。脚本不需要 ffmpeg（时长是直接读 mp4 头拿的），只要有 Python 和 pyJianYingDraft。

**方式二（命令行）**：

```bat
pip install pyJianYingDraft
python spike.py --video "D:\素材\任意视频.mp4" --name "WIN测试_程序生成"
```

脚本会：

- 在 `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft\` 下生成草稿 `WIN测试_程序生成`；
- 同时写 `draft_info.json`（6+ 入口）和 `draft_content.json`（5.x 入口）；
- 素材打包进该草稿的 `Resources\`；
- 备份并更新 `root_meta_info.json`（备份名 `root_meta_info.json.spike.bak`）。

然后：

1. **完全退出剪映**（包括右下角托盘图标），重新打开；
2. 在「本地草稿」里找 `WIN测试_程序生成`；
3. 双击打开。

---

## 三种结果，三条路

| 结果 | 含义 | 下一步 |
|---|---|---|
| ✅ 列表里出现，双击能看到 **2 段视频 + 2 条字幕** | Windows 也认明文草稿 | **双平台完整支持**，直接开做 |
| ⚠️ 列表出现，但打开报错 / 时间线是空的 / 提示"内容损坏" | 能识别文件、读不懂内容 | 再做一组对照：删掉 `draft_info.json`，只留 `draft_content.json`，重启剪映再试 |
| ❌ 列表里根本没有这个草稿 | 索引机制不同 | 查 `root_meta_info.json` 结构（把文件发我），或走降级方案 |

**降级方案**（如果 Windows 完全不行）：
Windows 版只交付「分镜表 + 切好的素材 + 预览片」，用户在剪映里手动拖时间线；macOS 版保持全自动。

---

## 回传什么

1. 上面三种结果哪一条；
2. 剪映版本号（设置 → 关于）；
3. 草稿列表截图（有没有出现）；
4. 如果报错，报错弹窗截图 + `%LOCALAPPDATA%\JianyingPro\User Data\Log\` 下最新日志；
5. `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json` 这个文件（脱敏后）。

---

## 安全说明

- 脚本只写一个名字带 `WIN测试_` 的草稿，**不碰你已有的草稿**；
- 修改 `root_meta_info.json` 前会自动备份为 `.spike.bak`；
- 想清理：删掉 `WIN测试_程序生成` 文件夹，再把 `.spike.bak` 还原回 `root_meta_info.json`。
