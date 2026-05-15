# Playwright MCP 配置指南

## ✅ 配置状态

**Playwright MCP 已成功配置！**

### 安装详情
- **包名**: `@playwright/mcp`
- **安装路径**: `/home/roler/.hermes/node/bin/playwright-mcp`
- **版本**: 最新版
- **MCP 服务器**: 已添加到 Hermes 配置
- **工具数量**: 23 个工具

### 配置位置
配置文件: `~/.hermes/config.yaml`

```yaml
mcp_servers:
  playwright:
    command: /home/roler/.hermes/node/bin/playwright-mcp
    enabled: true
```

## 🚀 使用方法

### 1. 启动新会话
**重要**: 必须启动新的 Hermes 会话才能使用 Playwright 工具

```bash
# 启动新的 Hermes 会话
hermes

# 或者在当前会话中重置
/reset
```

### 2. 可用工具列表

Playwright MCP 提供 23 个强大的浏览器自动化工具：

#### 页面导航
- `browser_navigate` - 导航到 URL
- `browser_navigate_back` - 返回上一页
- `browser_close` - 关闭页面

#### 元素交互
- `browser_click` - 点击元素
- `browser_type` - 输入文本
- `browser_hover` - 悬停元素
- `browser_drag` - 拖拽元素
- `browser_drop` - 拖放文件
- `browser_select_option` - 选择下拉选项
- `browser_press_key` - 按键

#### 表单操作
- `browser_fill_form` - 填充表单
- `browser_file_upload` - 上传文件

#### 页面信息
- `browser_snapshot` - 获取页面快照（可访问性树）
- `browser_take_screenshot` - 截图
- `browser_console_messages` - 获取控制台消息
- `browser_network_requests` - 获取网络请求列表
- `browser_network_request` - 获取单个请求详情

#### 浏览器控制
- `browser_resize` - 调整窗口大小
- `browser_tabs` - 管理标签页
- `browser_wait_for` - 等待元素或时间
- `browser_handle_dialog` - 处理对话框
- `browser_evaluate` - 执行 JavaScript
- `browser_run_code_unsafe` - 运行 Playwright 代码（不安全）

## 💡 使用示例

### 示例 1: 访问网页并截图
```
用户: 访问 https://github.com 并截图

AI: 我来帮您访问 GitHub 并截图。

[使用 browser_navigate 导航到 https://github.com]
[使用 browser_take_screenshot 截图]
```

### 示例 2: 搜索内容
```
用户: 在 TradingView 上搜索 BTC 策略

AI: 我来帮您在 TradingView 上搜索 BTC 策略。

[使用 browser_navigate 导航到 https://www.tradingview.com]
[使用 browser_click 点击搜索按钮]
[使用 browser_type 输入 "BTC strategy"]
[使用 browser_press_key 按 Enter]
[使用 browser_snapshot 获取结果]
```

### 示例 3: 获取页面内容
```
用户: 获取 https://example.com 的页面内容

AI: 我来帮您获取页面内容。

[使用 browser_navigate 导航到 https://example.com]
[使用 browser_evaluate 执行 JavaScript 获取内容]
或
[使用 browser_snapshot 获取可访问性树]
```

## 🔧 高级配置

### 配置选项
您可以通过修改 `~/.hermes/config.yaml` 来自定义 Playwright MCP：

```yaml
mcp_servers:
  playwright:
    command: /home/roler/.hermes/node/bin/playwright-mcp
    enabled: true
    env:
      - PLAYWRIGHT_HEADLESS=true
      - PLAYWRIGHT_VIEWPORT=1920x1080
```

### 命令行选项
Playwright MCP 支持多种选项：

```bash
# 查看所有选项
/home/roler/.hermes/node/bin/playwright-mcp --help

# 常用选项:
--headless              # 无头模式
--viewport-size 1920x1080  # 视口大小
--timeout-navigation 30000   # 导航超时
--timeout-action 5000        # 动作超时
--ignore-https-errors        # 忽略 HTTPS 错误
--user-agent "Custom UA"     # 自定义 User-Agent
```

## ⚠️ 注意事项

1. **新会话必需**: 添加 MCP 后必须启动新会话才能使用
2. **浏览器实例**: 每个会话会有独立的浏览器实例
3. **资源占用**: 浏览器会占用内存，使用完毕后建议关闭
4. **安全性**: `browser_run_code_unsafe` 可以执行任意 JavaScript，谨慎使用

## 🆚 与原生 browser 工具的区别

| 特性 | Playwright MCP | 原生 browser 工具 |
|------|----------------|------------------|
| 浏览器引擎 | Playwright (Chromium/Firefox/WebKit) | Browserbase/Camofox/本地 Chromium |
| 工具数量 | 23 个 | 约 10 个 |
| 截图功能 | ✅ 完整支持 | ✅ 支持 |
| JavaScript 执行 | ✅ 完整支持 | ⚠️ 有限支持 |
| 网络拦截 | ✅ 支持 | ❌ 不支持 |
| 文件上传 | ✅ 支持 | ❌ 不支持 |
| 多标签页 | ✅ 支持 | ❌ 不支持 |
| 对话框处理 | ✅ 支持 | ❌ 不支持 |

## 🔍 故障排除

### 问题 1: MCP 无法连接
```bash
# 检查 MCP 服务器状态
hermes mcp test playwright

# 重新添加
hermes mcp remove playwright
hermes mcp add playwright --command "/home/roler/.hermes/node/bin/playwright-mcp"
```

### 问题 2: 浏览器无法启动
```bash
# 检查 Playwright 浏览器是否安装
ls -la ~/.cache/ms-playwright/

# 手动安装浏览器
npx playwright install chromium
```

### 问题 3: 工具不显示
```bash
# 确保在新会话中
/reset

# 或退出并重新启动 hermes
exit
hermes
```

## 📚 参考链接

- [Playwright MCP GitHub](https://github.com/microsoft/playwright-mcp)
- [Playwright 文档](https://playwright.dev/)
- [MCP 协议文档](https://modelcontextprotocol.io/)

## ✅ 验证安装

运行以下命令验证安装：

```bash
# 检查 MCP 配置
hermes mcp list

# 测试 MCP 连接
hermes mcp test playwright

# 运行测试脚本
python3 /home/roler/Code/CryptoQuant/test_playwright_mcp.py
```

---

**配置完成时间**: 2025年  
**Playwright MCP 版本**: 最新版  
**状态**: ✅ 已启用
