import os
import json
import re
import ast
import requests
from typing import Dict, Tuple, Optional

CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai_config.json"))

def load_ai_config() -> Dict[str, str]:
    """
    加载 AI 接口配置，若无则返回默认值
    """
    default_config = {
        "api_key": "",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model_name": "gemini-1.5-pro",
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 兼容旧配置并合并默认值
                for k, v in default_config.items():
                    if k not in config:
                        config[k] = v
                return config
        except Exception:
            return default_config
    return default_config

def save_ai_config(api_key: str, base_url: str, model_name: str) -> None:
    """
    保存 AI 接口配置到本地
    """
    config = {
        "api_key": api_key.strip(),
        "base_url": base_url.strip(),
        "model_name": model_name.strip(),
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def validate_strategy_code(code_string: str) -> Tuple[bool, str]:
    """
    🛡️ AST 安全盾：在内存中解析并编译 AI 编写的代码，防止语法错误和恶意库加载
    """
    try:
        # 1. 语法正确性检查
        parsed_ast = ast.parse(code_string)
        
        # 2. 安全合规性静态分析（防止 AI 引入敏感系统操作）
        for node in ast.walk(parsed_ast):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ["subprocess", "shutil"]:
                        return False, f"检测到导入了敏感系统库: {alias.name}，已被安全盾拦截！"
            elif isinstance(node, ast.ImportFrom):
                if node.module in ["os", "sys", "subprocess", "shutil"]:
                    return False, f"检测到从系统敏感库 {node.module} 导入，已被安全盾拦截！"
        
        # 3. 编译验证
        compile(code_string, "<string>", "exec")
        return True, "语法与安全静态校验 100% 通过！"
    except SyntaxError as se:
        return False, f"语法错误: 行 {se.lineno}, 列 {se.offset} - {se.msg}\n错误行: {se.text}"
    except Exception as e:
        return False, f"校验异常: {str(e)}"

def request_ai_diagnosis(
    vt_symbol: str,
    stats: Dict[str, str],
    strategy_code: str,
    api_key: str,
    base_url: str,
    model_name: str
) -> Tuple[str, str, str]:
    """
    向大语言模型接口发起诊断与进化请求。
    返回元组: (raw_response, parsed_report, parsed_code)
    """
    if not api_key:
        raise ValueError("API Key 不能为空，请先在界面配置并保存！")
        
    url = f"{base_url.rstrip('/')}/chat/completions"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 构建极其专业、结构化的量化诊断 Prompt
    prompt = f"""您是一位世界顶级的量化策略分析师与高级 Python 算法交易开发专家，专精于基于 VeighNa (VN.py) CTA 框架的 A 股策略设计。

当前我们要对股票【 {vt_symbol} 】在过去几年的历史回测表现进行深度诊断和逻辑自进化。

=== 🚀 1. 该股票的回测核心指标 (Stats) ===
{json.dumps(stats, indent=4, ensure_ascii=False)}

=== 💻 2. 策略当前 Python 源代码 ===
```python
{strategy_code}
```

=== 🎯 3. 您的任务与具体要求 ===
请您对回测的业绩指标与当前的策略逻辑进行诊断：
1. **诊断并归因 (Diagnosis & Attribution)**: 分析该策略在这个标的上的核心问题。例如：回测期总收益不佳、夏普比率偏低、在熊市/震荡市期间最大回撤失控、或交易笔数过多（频繁止损导致手续费损耗过大）。
2. **逻辑漏洞与改进建议 (Suggestions)**: 指出原有逻辑的缺陷，给出实质性的逻辑优化策略。例如：
   - 增加指标过滤器（如 RSI、CCI、布林带）以过滤高风险区间的交易。
   - 调整仓位管理或修改子仓位加仓条件。
   - 优化止盈点 (profit_target) 或加入动态移动止损。
3. **自动代码自演化 (Code Evolution)**: **直接重写**整份策略 Python 源代码！必须输出一份功能完整、变量和参数定义严谨、符合 VeighNa CTA 规范的全新策略代码。

=== ⚠️ 4. 关键输出格式（极其重要，请绝对遵守） ===
为了让交易终端能解析出您的诊断报告与代码，请**完全使用**以下 XML 标签包裹您的输出，不要夹杂其他文字：

<diagnosis_report>
在这里用 Markdown 语法书写您极其详尽、专业的“首席量化专家深度诊断报告”（包含：盈利/亏损归因、漏洞分析、指标优化建议）。字数不少于 400 字，力求极度专业。
</diagnosis_report>

<evolved_code>
在这里给出**完整、没有截断、可直接编译运行**的全新优化后策略 Python 代码。确保：
- 代码中不包含 `os`, `sys`, `subprocess` 等敏感系统库调用。
- 逻辑改写符合 VN.py CtaTemplate 规范。
- 保持原策略的类名（例如 {re.search(r'class\s+(\w+)\(', strategy_code).group(1) if re.search(r'class\s+(\w+)\(', strategy_code) else 'StockQuantStrategy'}），这样主系统可以零无缝热重载！
</evolved_code>
"""

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2  # 较低的温度确保代码的严谨性与格式一致性
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code != 200:
            raise Exception(f"接口调用失败，状态码: {response.status_code}\n详情: {response.text}")
            
        res_json = response.json()
        raw_text = res_json["choices"][0]["message"]["content"]
        
        # 精确正则匹配标签内容
        report_match = re.search(r"<diagnosis_report>(.*?)</diagnosis_report>", raw_text, re.DOTALL)
        code_match = re.search(r"<evolved_code>(.*?)</evolved_code>", raw_text, re.DOTALL)
        
        report = report_match.group(1).strip() if report_match else "未能解析出诊断报告，请确保 API 正常返回且包裹在 <diagnosis_report> 标签中。"
        code = code_match.group(1).strip() if code_match else ""
        
        # 清洗代码中的 Markdown 块包裹
        if code.startswith("```python"):
            code = code[9:]
        elif code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        code = code.strip()
        
        return raw_text, report, code
        
    except requests.exceptions.Timeout:
        raise Exception("接口请求超时，请检查网络连接或更换 API 代理 Base URL 后重试。")
    except Exception as e:
        raise Exception(f"AI 诊断失败: {str(e)}")
