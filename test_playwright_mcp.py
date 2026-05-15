#!/usr/bin/env python3
"""
测试 Playwright MCP 是否正常工作
"""

import subprocess
import json

def test_playwright_mcp():
    """测试 Playwright MCP 服务器"""
    
    # 启动 MCP 服务器并测试
    result = subprocess.run(
        ["/home/roler/.hermes/node/bin/playwright-mcp", "--help"],
        capture_output=True,
        text=True
    )
    
    print("Playwright MCP 安装状态:")
    print("=" * 50)
    
    if result.returncode == 0:
        print("✅ Playwright MCP 已正确安装")
        print("\n可用选项:")
        print(result.stdout[:500] + "...")
    else:
        print("❌ Playwright MCP 安装有问题")
        print(result.stderr)
        return False
    
    # 检查 Hermes 配置
    print("\n" + "=" * 50)
    print("Hermes MCP 配置:")
    print("=" * 50)
    
    result = subprocess.run(
        ["hermes", "mcp", "list"],
        capture_output=True,
        text=True
    )
    
    if "playwright" in result.stdout:
        print("✅ Playwright MCP 已在 Hermes 中配置")
        print(result.stdout)
        return True
    else:
        print("❌ Playwright MCP 未在 Hermes 中配置")
        return False

if __name__ == "__main__":
    success = test_playwright_mcp()
    
    if success:
        print("\n" + "=" * 50)
        print("🎉 Playwright MCP 配置成功!")
        print("=" * 50)
        print("\n使用方法:")
        print("1. 启动新的 Hermes 会话: hermes")
        print("2. 使用 Playwright 工具，例如:")
        print("   - browser_navigate: 导航到网页")
        print("   - browser_click: 点击元素")
        print("   - browser_type: 输入文本")
        print("   - browser_take_screenshot: 截图")
        print("   - browser_evaluate: 执行 JavaScript")
        print("\n注意: 需要启动新的会话才能使用新添加的工具")
    else:
        print("\n❌ 配置可能有问题，请检查")
