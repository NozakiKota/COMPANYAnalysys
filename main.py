#!/usr/bin/env python3
"""
顧客分析エージェント - メインエントリーポイント

使い方:
  python main.py "トヨタ自動車" "ソニーグループ" "NTT"
  python main.py --file companies.txt
"""

import os
import sys
import time
from pathlib import Path

import anthropic
import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from agent import collect_ir_info, estimate_cost, evaluate_and_prioritize, organize_ir_table
from output import (
    create_company_folder,
    create_ir_excel,
    create_priority_excel,
    save_organized_json,
    save_raw_ir_json,
)

app = typer.Typer(help="顧客IR情報を自動収集・分析・優先順位化するエージェント")
console = Console()


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        console.print(
            "[bold red]エラー:[/] ANTHROPIC_API_KEY 環境変数が設定されていません。\n"
            "  export ANTHROPIC_API_KEY=your-api-key",
            style="red",
        )
        sys.exit(1)
    return key


def print_banner():
    console.print(
        Panel.fit(
            "[bold cyan]顧客分析エージェント[/]\n"
            "[dim]IR情報自動収集 → 観点別整理 → 優先順位評価[/]",
            border_style="cyan",
        )
    )


def process_single_company(
    client: anthropic.Anthropic,
    company_name: str,
    progress: Progress,
) -> tuple[dict, dict]:
    """1社分の処理: IR収集 → 整理 → 保存"""
    folder = create_company_folder(company_name)

    # Step 1: IR情報収集
    task = progress.add_task(f"  [{company_name}] IR情報収集中...", total=3)
    ir_data = collect_ir_info(client, company_name)
    save_raw_ir_json(folder, ir_data)
    progress.update(task, advance=1, description=f"  [{company_name}] 情報整理中...")

    # Step 2: 表形式に整理
    organized = organize_ir_table(client, ir_data)
    save_organized_json(folder, organized)
    progress.update(task, advance=1, description=f"  [{company_name}] Excel出力中...")

    # Step 3: 企業別Excelを保存
    excel_path = create_ir_excel(company_name, organized, folder)
    progress.update(task, advance=1, description=f"  [{company_name}] ✓ 完了")

    console.print(f"  ✅ {company_name}: [green]{excel_path}[/]")
    return ir_data, organized


@app.command()
def analyze(
    companies: list[str] = typer.Argument(
        None, help="分析対象の企業名（スペース区切りで複数指定可）"
    ),
    file: Path = typer.Option(
        None, "--file", "-f",
        help="企業名リストファイル（1行1社）",
    ),
    output_dir: Path = typer.Option(
        Path("output"), "--output", "-o",
        help="出力ディレクトリ（デフォルト: output/）",
    ),
):
    """
    指定した顧客のIR情報を収集・分析・優先順位付けします。

    例:
      python main.py "トヨタ自動車" "ソニーグループ"
      python main.py --file companies.txt
    """
    print_banner()

    # 企業リストの準備
    company_list: list[str] = list(companies) if companies else []
    if file:
        if not file.exists():
            console.print(f"[red]ファイルが見つかりません: {file}[/]")
            raise typer.Exit(1)
        company_list.extend(
            line.strip() for line in file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    if not company_list:
        console.print("[yellow]企業名を指定してください。[/]")
        console.print("  例: python main.py \"トヨタ自動車\" \"ソニーグループ\"")
        raise typer.Exit(1)

    # 重複除去
    company_list = list(dict.fromkeys(company_list))

    console.print(f"\n[bold]対象企業:[/] {', '.join(company_list)}")
    console.print(f"[bold]出力先:[/] {output_dir.resolve()}\n")

    client = anthropic.Anthropic(api_key=get_api_key())

    # コスト見積もりと確認
    console.print("[dim]コスト見積もりを計算中...[/]")
    try:
        est = estimate_cost(client, company_list)
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim")
        table.add_column(style="bold")
        table.add_row("モデル", est["model"])
        table.add_row("対象企業数", f"{est['num_companies']}社")
        table.add_row("推定inputトークン", f"{est['estimated_total_input_tokens']:,}")
        table.add_row("推定outputトークン", f"{est['estimated_total_output_tokens']:,}")
        table.add_row("推定コスト", f"[yellow]~${est['estimated_cost_usd']:.2f} USD[/]")
        console.print(table)
        console.print("[dim]※ ループ回数・web検索結果により実際のコストは変動します[/]\n")
        answer = typer.confirm("実行しますか？", default=True)
        if not answer:
            console.print("[yellow]キャンセルしました。[/]")
            raise typer.Exit(0)
    except anthropic.APIError as e:
        console.print(f"[yellow]見積もり取得失敗（スキップ）: {e}[/]\n")

    all_organized: list[dict] = []
    ir_data_map: dict[str, dict] = {}

    # 各企業の処理
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        main_task = progress.add_task(
            f"[cyan]全{len(company_list)}社を処理中...", total=len(company_list)
        )

        for i, company in enumerate(company_list):
            console.print(f"\n[bold cyan]■ {i+1}/{len(company_list)}: {company}[/]")
            try:
                ir_data, organized = process_single_company(client, company, progress)
                all_organized.append(organized)
                ir_data_map[company] = ir_data
            except anthropic.RateLimitError:
                console.print(f"  [yellow]⚠ レート制限。30秒待機後に再試行...[/]")
                time.sleep(30)
                try:
                    ir_data, organized = process_single_company(client, company, progress)
                    all_organized.append(organized)
                except Exception as e:
                    console.print(f"  [red]✗ {company} 処理失敗: {e}[/]")
            except Exception as e:
                console.print(f"  [red]✗ {company} エラー: {e}[/]")

            progress.update(main_task, advance=1)

    if not all_organized:
        console.print("[red]処理できた企業がありません。[/]")
        raise typer.Exit(1)

    # 複数企業の場合は優先順位評価
    if len(all_organized) >= 2:
        console.print(f"\n[bold cyan]■ {len(all_organized)}社の優先順位評価を実行中...[/]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("  評価・スコアリング中...", total=1)
            evaluation = evaluate_and_prioritize(client, all_organized)
            progress.update(task, advance=1)

        priority_path = create_priority_excel(evaluation, all_organized)
        console.print(f"\n  ✅ 優先順位評価表: [green]{priority_path}[/]")

        # 結果サマリー表示
        _print_priority_summary(evaluation)
    elif len(all_organized) == 1:
        console.print("\n[yellow]企業が1社のため、優先順位評価はスキップします。[/]")

    console.print(
        Panel.fit(
            f"[bold green]✓ 処理完了[/]\n"
            f"出力先: [cyan]{output_dir.resolve()}[/]",
            border_style="green",
        )
    )


def _print_priority_summary(evaluation: dict):
    """優先順位サマリーをコンソールに表示"""
    evaluations = evaluation.get("evaluations", [])
    if not evaluations:
        return

    evaluations.sort(key=lambda x: x.get("priority_rank", 99))

    table = Table(title="📊 顧客対応優先順位", show_header=True, header_style="bold cyan")
    table.add_column("順位", justify="center", width=6)
    table.add_column("企業名", width=20)
    table.add_column("総合スコア", justify="center", width=10)
    table.add_column("推奨アクション", width=30)

    for ev in evaluations:
        rank = ev.get("priority_rank", "-")
        name = ev.get("company_name", "")
        total = ev.get("weighted_total", 0)
        action = ev.get("recommended_action", "")

        score_color = "green" if total >= 4 else ("yellow" if total >= 2.5 else "red")
        rank_icon = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"{rank}位"))

        table.add_row(
            rank_icon,
            name,
            f"[{score_color}]{total:.2f}[/]",
            action,
        )

    console.print("\n")
    console.print(table)

    summary = evaluation.get("summary", "")
    if summary:
        console.print(
            Panel(
                f"[bold]全体所見:[/]\n{summary}",
                border_style="blue",
                width=80,
            )
        )


if __name__ == "__main__":
    app()
