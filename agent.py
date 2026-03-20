"""
顧客分析エージェント: Claude Opus 4.6 + web_search/web_fetch で
IR情報を自動収集・分析・評価する
"""

import json
import time
from datetime import datetime
from typing import Any

import anthropic

from config import (
    EVALUATION_CRITERIA,
    EVALUATION_PROMPT,
    IR_ANALYSIS_PERSPECTIVES,
    IR_COLLECTION_SYSTEM_PROMPT,
    TABLE_ORGANIZATION_PROMPT,
)

MODEL = "claude-sonnet-4-6"

# Claude が使用するツール定義
TOOLS: list[dict] = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]


def _run_agent_loop(
    client: anthropic.Anthropic,
    system: str,
    user_message: str,
    max_iterations: int = 10,
) -> str:
    """
    Claude のエージェントループ。
    web_search / web_fetch ツールを使いながら stop_reason == "end_turn" になるまで繰り返す。
    """
    messages: list[dict] = [{"role": "user", "content": user_message}]
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        with client.messages.stream(
            model=MODEL,
            max_tokens=8192,
            system=system,
            thinking={"type": "adaptive"},
            tools=TOOLS,  # type: ignore[arg-type]
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        # pause_turn: サーバー側ループの再開
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        # end_turn: 完了
        if response.stop_reason == "end_turn":
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_blocks)

        # tool_use: ツール実行（web_search / web_fetch はサーバー側で自動実行）
        # ツール結果はレスポンスに含まれるため、そのまま次ターンへ渡す
        messages.append({"role": "assistant", "content": response.content})

        # tool_result を user ターンに追加
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                # web_search / web_fetch の結果はブロック内に含まれる
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "ツール実行中",
                    }
                )

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return "エラー: 最大イテレーション数を超えました"


def collect_ir_info(client: anthropic.Anthropic, company_name: str) -> dict[str, Any]:
    """
    Step 1: 指定企業の IR 情報を web_search / web_fetch で収集する
    """
    perspectives_text = "\n".join(
        f"- {p}" for p in IR_ANALYSIS_PERSPECTIVES
    )
    system = IR_COLLECTION_SYSTEM_PROMPT.format(perspectives=perspectives_text)

    user_message = f"""
「{company_name}」のIR情報を収集してください。

## 検索すべき情報
1. 公式IRサイトの最新決算情報（売上高・営業利益・純利益）
2. 中期経営計画・経営ビジョン
3. DX・デジタル投資に関するコメント・数値
4. 設備投資・R&D投資の状況
5. 経営者メッセージ・事業戦略

収集した情報をJSON形式で整理して返してください。
情報が見つからない項目は "情報なし" と記載してください。

最終的な出力は以下の構造のJSONのみとし、余分な説明は不要です：
{{
  "company_name": "{company_name}",
  "ir_page_url": "IRページURL",
  "collected_at": "収集日時",
  "financials": {{
    "revenue": "売上高",
    "operating_profit": "営業利益",
    "net_profit": "純利益",
    "growth_rate": "成長率",
    "fiscal_year": "対象年度"
  }},
  "strategy": {{
    "vision": "ビジョン・ミッション",
    "mid_term_plan": "中期経営計画概要",
    "priority_areas": ["注力領域1", "注力領域2"]
  }},
  "investment": {{
    "capex": "設備投資額",
    "rd_investment": "R&D投資",
    "dx_budget": "DX関連予算・コメント",
    "ma_activity": "M&A動向"
  }},
  "management_comment": "経営者コメント（課題・リスク含む）",
  "competitive_advantage": "競合優位性",
  "financial_health": {{
    "equity_ratio": "自己資本比率",
    "debt": "有利子負債",
    "cash_flow": "営業CF"
  }},
  "sources": ["情報源URL1", "情報源URL2"]
}}
"""

    raw_text = _run_agent_loop(client, system, user_message)

    # JSON 抽出
    try:
        # ```json ... ``` ブロックがある場合は除去
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        # JSON 部分だけ抽出（{ から始まる部分）
        json_start = raw_text.find("{")
        json_end = raw_text.rfind("}") + 1
        if json_start >= 0:
            raw_text = raw_text[json_start:json_end]

        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "company_name": company_name,
            "collected_at": datetime.now().isoformat(),
            "raw_text": raw_text,
            "parse_error": "JSON解析エラー。raw_textに生データを保存。",
        }


def organize_ir_table(
    client: anthropic.Anthropic, ir_data: dict[str, Any]
) -> dict[str, Any]:
    """
    Step 2: 収集した IR 情報を観点別の表形式に整理する
    """
    company_name = ir_data.get("company_name", "不明")
    perspectives_text = "\n".join(
        f"- {p}" for p in IR_ANALYSIS_PERSPECTIVES
    )

    system = "あなたは企業分析の専門家です。収集したIR情報を指定の観点で整理・要約してください。"

    user_message = TABLE_ORGANIZATION_PROMPT.format(
        company_name=company_name,
        ir_data=json.dumps(ir_data, ensure_ascii=False, indent=2),
        perspectives=perspectives_text,
    )

    raw_text = _run_agent_loop(client, system, user_message, max_iterations=3)

    try:
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()
        json_start = raw_text.find("{")
        json_end = raw_text.rfind("}") + 1
        if json_start >= 0:
            raw_text = raw_text[json_start:json_end]
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "company_name": company_name,
            "raw_text": raw_text,
            "parse_error": "JSON解析エラー",
        }


def evaluate_and_prioritize(
    client: anthropic.Anthropic,
    organized_data_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Step 3: 全企業を評価基準でスコアリングし、優先順位を付ける
    """
    criteria_text = json.dumps(EVALUATION_CRITERIA, ensure_ascii=False, indent=2)
    weights_text = ", ".join(
        f"{v['name']}: {v['weight']}" for v in EVALUATION_CRITERIA.values()
    )

    system = "あなたは営業戦略の専門家です。各企業データを客観的に評価し、営業優先順位を決定してください。"

    user_message = EVALUATION_PROMPT.format(
        companies_data=json.dumps(organized_data_list, ensure_ascii=False, indent=2),
        criteria=criteria_text,
        weights=weights_text,
    )

    raw_text = _run_agent_loop(client, system, user_message, max_iterations=3)

    try:
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()
        json_start = raw_text.find("{")
        json_end = raw_text.rfind("}") + 1
        if json_start >= 0:
            raw_text = raw_text[json_start:json_end]
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {"raw_text": raw_text, "parse_error": "JSON解析エラー"}
