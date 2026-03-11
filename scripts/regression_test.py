#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回归测试脚本 - 验证核心功能是否正常

使用方式:
    python scripts/regression_test.py

说明:
    1. 运行 analyze_stock() API 方式
    2. 运行 aishare 命令行方式
    3. 验证代码能正常运行，输出格式正确
"""

import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 测试配置
TEST_STOCK_CODE = "000001"  # 平安银行


def get_git_info():
    """获取 git 提交信息"""
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            encoding='utf-8',
            errors='replace'
        ).strip()

        # 检查是否有未提交的更改
        has_changes = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            text=True,
            encoding='utf-8',
            errors='replace'
        ).strip()

        # 如果有未提交的更改，添加 WIP 标记
        if has_changes:
            commit_hash = f"{commit_hash}-WIP"

        # 尝试获取分支名（CI 环境可能无法获取）
        try:
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=PROJECT_ROOT,
                text=True,
                encoding='utf-8',
                errors='replace'
            ).strip()
            if not branch:
                branch = os.getenv("GITHUB_REF_NAME", "unknown")
        except:
            branch = os.getenv("GITHUB_REF_NAME", "unknown")

        return commit_hash, branch
    except Exception as e:
        print(f"警告: 无法获取 git 信息: {e}")
        return "unknown", "unknown"


def test_api_method(stock_code, commit_hash):
    """测试 API 方式: analyze_stock()"""
    print("\n" + "="*60)
    print(f"[1/2] 测试 API 方式: analyze_stock('{stock_code}')")
    print("="*60)

    ci_env = is_ci_environment()

    try:
        from AIShareTxt import analyze_stock

        print(f"正在调用 analyze_stock('{stock_code}')...")
        result = analyze_stock(stock_code)

        # 验证结果
        if result is None:
            print(f"❌ API 调用失败: 返回 None")
            if ci_env:
                print(f"::error::API 测试失败: 返回 None")
            return False

        if isinstance(result, str) and result.startswith("错误"):
            print(f"❌ API 调用失败: {result[:100]}...")
            if ci_env:
                print(f"::error::API 测试失败: {result[:100]}")
            return False

        if len(result) < 100:
            print(f"❌ API 输出过短: {len(result)} 字符")
            if ci_env:
                print(f"::error::API 测试失败: 输出过短")
            return False

        print(f"✅ API 测试成功")
        print(f"   输出长度: {len(result)} 字符")

        # 显示输出摘要
        lines = result.split('\n')
        print(f"   输出行数: {len(lines)}")

        # 显示前几行
        print(f"   输出预览:")
        for line in lines[:3]:
            print(f"      {line}")

        return True

    except Exception as e:
        print(f"❌ API 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_cli_method(stock_code, commit_hash):
    """测试命令行方式: aishare [code]"""
    print("\n" + "="*60)
    print(f"[2/2] 测试命令行方式: aishare {stock_code}")
    print("="*60)

    ci_env = is_ci_environment()

    try:
        # Windows 上使用 python -m 方式运行
        python_exe = sys.executable
        cmd = [python_exe, "-m", "AIShareTxt.core.data_processor", stock_code]

        print(f"正在执行命令: {' '.join(cmd)}...")

        # 运行命令行（Windows 上使用 utf-8 编码）
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )

        output = result.stdout or ""
        if result.stderr:
            output += "\n" + result.stderr

        # 检查是否成功
        if result.returncode != 0:
            print(f"❌ 命令行执行失败")
            print(f"   返回码: {result.returncode}")
            if ci_env:
                print(f"::error::命令行测试失败: 返回码 {result.returncode}")
            return False

        # 检查输出内容
        if "错误：股票代码格式不正确" in output:
            print(f"❌ 命令行执行失败: 股票代码格式错误")
            if ci_env:
                print(f"::error::命令行测试失败: 股票代码格式错误")
            return False

        if len(output) < 100:
            print(f"❌ 命令行输出过短: {len(output)} 字符")
            if ci_env:
                print(f"::error::命令行测试失败: 输出过短")
            return False

        print(f"✅ 命令行测试成功")
        print(f"   输出长度: {len(output)} 字符")

        # 显示输出摘要
        lines = output.split('\n')
        print(f"   输出行数: {len(lines)}")

        # 显示前几行
        print(f"   输出预览:")
        for line in lines[:3]:
            if line.strip():
                print(f"      {line}")

        return True

    except subprocess.TimeoutExpired:
        print(f"❌ 命令行执行超时")
        return None
    except Exception as e:
        print(f"❌ 命令行测试异常: {e}")
        import traceback
        traceback.print_exc()
        return None


def print_summary(commit_hash, branch, api_result, cli_result):
    """打印测试摘要"""
    ci_env = is_ci_environment()

    print("\n" + "="*60)
    print("回归测试摘要")
    print("="*60)
    print(f"Git 提交: {commit_hash}")
    print(f"分支: {branch}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试股票: {TEST_STOCK_CODE}")
    print("-"*60)
    print(f"API 方式:     {'✅ 通过' if api_result else '❌ 失败'}")
    print(f"命令行方式:   {'✅ 通过' if cli_result else '❌ 失败'}")
    print("="*60)

    # CI 环境输出特殊格式
    if ci_env:
        if api_result:
            print("::notice::API 测试通过")
        else:
            print("::error::API 测试失败")

        if cli_result:
            print("::notice::命令行测试通过")
        else:
            print("::error::命令行测试失败")

    if api_result and cli_result:
        print("\n🎉 所有测试通过！代码改动未影响核心功能。")
        if ci_env:
            print("::notice::回归测试全部通过")
        return 0
    else:
        print("\n⚠️  部分测试失败，请检查上述错误信息。")
        if ci_env:
            print("::error::回归测试部分失败")
        return 1


def is_ci_environment():
    """检测是否在 CI 环境中运行"""
    return os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true"


def main():
    """主函数"""
    ci_env = is_ci_environment()

    if ci_env:
        print("="*60)
        print("AIShareTxt 回归测试 (CI 环境)")
        print("="*60)
    else:
        print("="*60)
        print("AIShareTxt 回归测试")
        print("="*60)

    # 获取 git 信息
    commit_hash, branch = get_git_info()
    print(f"Git 提交: {commit_hash}")
    print(f"分支: {branch}")
    print(f"测试股票: {TEST_STOCK_CODE} (平安银行)")

    # 运行测试
    api_result = test_api_method(TEST_STOCK_CODE, commit_hash)
    cli_result = test_cli_method(TEST_STOCK_CODE, commit_hash)

    # 打印摘要
    exit_code = print_summary(commit_hash, branch, api_result, cli_result)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
