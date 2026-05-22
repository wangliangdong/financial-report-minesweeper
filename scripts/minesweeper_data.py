#!/usr/bin/env python3
"""财报排雷数据获取脚本 (Minesweeper Data Collector)

使用本项目内置的 TushareClient，获取排雷分析所需的全部结构化数据。
输出 JSON 到 stdout，供 Claude Code Skill 调用。

Usage:
    python3 scripts/minesweeper_data.py --stock-code 600519 [--years 10]
    python3 scripts/minesweeper_data.py --stock-code 000858 --years 5
"""

import argparse
import json
import os
import sys
import time

# Ensure scripts/ directory is on the path for sibling module imports
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import pandas as pd
from config import get_token, validate_stock_code

# Tushare is optional; EastMoney is the fallback public data source.
try:
    from tushare_collector import TushareClient
    _TUSHARE_AVAILABLE = True
except ImportError:
    _TUSHARE_AVAILABLE = False

try:
    import eastmoney_data as em_data
    _EM_AVAILABLE = True
except ImportError:
    _EM_AVAILABLE = False


def _safe_val(v):
    """Convert pandas/numpy values to JSON-serializable Python types."""
    if v is None:
        return None
    if isinstance(v, float) and (pd.isna(v) or v != v):
        return None
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def _df_to_records(df: pd.DataFrame, cols: list[str] | None = None) -> list[dict]:
    """Convert DataFrame to list of dicts with safe values."""
    if df.empty:
        return []
    if cols:
        available = [c for c in cols if c in df.columns]
        df = df[available]
    records = []
    for _, row in df.iterrows():
        records.append({k: _safe_val(v) for k, v in row.items()})
    return records


def get_stock_info(client, ts_code: str) -> dict:
    """Get basic stock info including industry classification."""
    try:
        df = client._safe_call(
            "stock_basic", ts_code=ts_code,
            fields="ts_code,name,industry,area,market,list_date,fullname"
        )
        if df.empty:
            return {"ts_code": ts_code, "name": "", "industry": "", "market": ""}
        row = df.iloc[0]
        return {
            "ts_code": _safe_val(row.get("ts_code", ts_code)),
            "name": _safe_val(row.get("name", "")),
            "industry": _safe_val(row.get("industry", "")),
            "area": _safe_val(row.get("area", "")),
            "market": _safe_val(row.get("market", "")),
            "list_date": _safe_val(row.get("list_date", "")),
            "fullname": _safe_val(row.get("fullname", "")),
        }
    except Exception as e:
        print(f"Warning: stock_basic failed: {e}", file=sys.stderr)
        return {"ts_code": ts_code, "name": "", "industry": "", "market": ""}


def get_audit_data(client, ts_code: str) -> list[dict]:
    """Get audit opinion history."""
    try:
        df = client._safe_call(
            "fina_audit", ts_code=ts_code,
            fields="ts_code,ann_date,end_date,audit_result,audit_agency,audit_fees"
        )
        if df.empty:
            return []
        df = df.sort_values("end_date", ascending=False)
        return _df_to_records(df)
    except Exception as e:
        print(f"Warning: fina_audit failed: {e}", file=sys.stderr)
        return []


def get_income_data(client, ts_code: str) -> list[dict]:
    """Get income statement data (annual reports only, report_type=1)."""
    fields = (
        "ts_code,end_date,ann_date,report_type,"
        "revenue,oper_cost,biz_tax_surchg,"
        "sell_exp,admin_exp,rd_exp,fin_exp,"
        "assets_impair_loss,credit_impa_loss,"
        "fv_value_chg_gain,invest_income,asset_disp_income,"
        "oth_biz_income,oth_biz_cost,"
        "operate_profit,non_oper_income,non_oper_exp,"
        "total_profit,income_tax,n_income,n_income_attr_p,"
        "basic_eps,diluted_eps"
    )
    try:
        df = client._safe_call(
            "income", ts_code=ts_code, report_type="1", fields=fields
        )
        if df.empty:
            return []
        df = df.sort_values("end_date", ascending=False)
        # Keep only year-end reports (ending in 1231)
        df = df[df["end_date"].str.endswith("1231")]
        return _df_to_records(df)
    except Exception as e:
        print(f"Warning: income failed: {e}", file=sys.stderr)
        return []


def get_balance_data(client, ts_code: str) -> list[dict]:
    """Get balance sheet data (annual reports only)."""
    fields = (
        "ts_code,end_date,ann_date,report_type,"
        "money_cap,trad_asset,notes_receiv,accounts_receiv,"
        "oth_receiv,prepayment,inventories,"
        "total_cur_assets,"
        "lt_eqt_invest,fix_assets,cip,intang_assets,goodwill,"
        "lt_amort_deferred_exp,defer_tax_assets,"
        "total_nca,total_assets,"
        "st_borr,notes_payable,acct_payable,"
        "contract_liab,adv_receipts,"
        "non_cur_liab_due_1y,lt_borr,bond_payable,"
        "total_cur_liab,total_ncl,total_liab,"
        "defer_tax_liab,"
        "total_hldr_eqy_exc_min_int,minority_int,total_hldr_eqy"
    )
    try:
        df = client._safe_call(
            "balancesheet", ts_code=ts_code, report_type="1", fields=fields
        )
        if df.empty:
            return []
        df = df.sort_values("end_date", ascending=False)
        df = df[df["end_date"].str.endswith("1231")]
        return _df_to_records(df)
    except Exception as e:
        print(f"Warning: balancesheet failed: {e}", file=sys.stderr)
        return []


def get_cashflow_data(client, ts_code: str) -> list[dict]:
    """Get cash flow statement data (annual reports only)."""
    fields = (
        "ts_code,end_date,ann_date,report_type,"
        "c_recp_prov_sg_act,"  # 销售商品、提供劳务收到的现金
        "n_cashflow_act,"      # 经营活动现金流量净额
        "n_cashflow_inv_act,"  # 投资活动现金流量净额
        "n_cash_flows_fnc_act,"  # 筹资活动现金流量净额
        "c_pay_acq_const_fiolta,"  # 购建固定资产等支付的现金 (capex)
        "n_recp_disp_fiolta,"  # 处置固定资产等收回的现金
        "free_cashflow,"       # 自由现金流 (if available)
        "n_cash_end_bal,"      # 期末现金及现金等价物余额
        "n_cash_beg_bal"       # 期初现金及现金等价物余额
    )
    try:
        df = client._safe_call(
            "cashflow", ts_code=ts_code, report_type="1", fields=fields
        )
        if df.empty:
            return []
        df = df.sort_values("end_date", ascending=False)
        df = df[df["end_date"].str.endswith("1231")]
        return _df_to_records(df)
    except Exception as e:
        print(f"Warning: cashflow failed: {e}", file=sys.stderr)
        return []


def get_indicator_data(client, ts_code: str) -> list[dict]:
    """Get financial indicators (ROE, margins, ratios, etc.)."""
    fields = (
        "ts_code,end_date,ann_date,"
        "roe,roe_waa,grossprofit_margin,netprofit_margin,"
        "rd_exp,"
        "current_ratio,quick_ratio,"
        "assets_turn,inv_turn,ar_turn,"
        "debt_to_assets,"
        "revenue_yoy,netprofit_yoy,op_yoy,"
        "ocfps,bps,profit_dedt,"
        "ebitda,fcff,netdebt,interestdebt,"
        "extra_item,deduct_item"
    )
    try:
        df = client._safe_call(
            "fina_indicator", ts_code=ts_code, fields=fields
        )
        if df.empty:
            return []
        df = df.sort_values("end_date", ascending=False)
        # Keep year-end reports
        df = df[df["end_date"].str.endswith("1231")]
        return _df_to_records(df)
    except Exception as e:
        print(f"Warning: fina_indicator failed: {e}", file=sys.stderr)
        return []


def get_holder_data(client, ts_code: str) -> list[dict]:
    """Get top 10 shareholders for multiple periods."""
    try:
        df = client._safe_call("top10_holders", ts_code=ts_code)
        if df.empty:
            return []
        df = df.sort_values(["end_date", "hold_amount"],
                            ascending=[False, False])
        # Keep last 3 reporting periods
        periods = df["end_date"].unique()[:3]
        df = df[df["end_date"].isin(periods)]
        cols = ["end_date", "holder_name", "hold_amount", "hold_ratio"]
        return _df_to_records(df, cols)
    except Exception as e:
        print(f"Warning: top10_holders failed: {e}", file=sys.stderr)
        return []


def get_peer_data(client, ts_code: str,
                  industry: str) -> dict:
    """Get peer company financial indicators for comparison.

    Finds companies in the same industry and pulls their latest
    gross margin, expense ratios, etc.
    """
    if not industry:
        return {"industry": "", "peers": []}

    try:
        # Get all companies in the same industry
        all_stocks = client._safe_call(
            "stock_basic",
            fields="ts_code,name,industry"
        )
        if all_stocks.empty:
            return {"industry": industry, "peers": []}

        peers = all_stocks[all_stocks["industry"] == industry]
        # Exclude self and limit to 20 peers
        peers = peers[peers["ts_code"] != ts_code].head(20)

        if peers.empty:
            return {"industry": industry, "peers": []}

        peer_data = []
        for _, peer_row in peers.iterrows():
            peer_code = peer_row["ts_code"]
            try:
                ind_df = client._safe_call(
                    "fina_indicator", ts_code=peer_code,
                    fields="ts_code,end_date,grossprofit_margin,netprofit_margin,"
                           "debt_to_assets,roe,assets_turn,inv_turn,ar_turn"
                )
                if ind_df.empty:
                    continue
                # Get latest year-end data
                ind_df = ind_df[ind_df["end_date"].str.endswith("1231")]
                if ind_df.empty:
                    continue
                ind_df = ind_df.sort_values("end_date", ascending=False)
                latest = ind_df.iloc[0]
                peer_data.append({
                    "ts_code": _safe_val(peer_code),
                    "name": _safe_val(peer_row.get("name", "")),
                    "end_date": _safe_val(latest.get("end_date", "")),
                    "grossprofit_margin": _safe_val(latest.get("grossprofit_margin")),
                    "netprofit_margin": _safe_val(latest.get("netprofit_margin")),
                    "debt_to_assets": _safe_val(latest.get("debt_to_assets")),
                    "roe": _safe_val(latest.get("roe")),
                    "assets_turn": _safe_val(latest.get("assets_turn")),
                    "inv_turn": _safe_val(latest.get("inv_turn")),
                    "ar_turn": _safe_val(latest.get("ar_turn")),
                })
            except Exception:
                continue  # Skip peers that fail

        return {"industry": industry, "peers": peer_data}

    except Exception as e:
        print(f"Warning: peer data failed: {e}", file=sys.stderr)
        return {"industry": industry, "peers": []}


def collect_minesweeper_data(stock_code: str, years: int = 10) -> dict:
    """Collect all data needed for minesweeper analysis.

    Data source priority:
      1. Tushare Pro (if TUSHARE_TOKEN is set)
      2. EastMoney datacenter API + Sina Finance HTML + emweb API (public, no token required)

    Args:
        stock_code: Stock code (e.g., '600519', '000858.SZ')
        years: Number of years of historical data to fetch

    Returns:
        Dict with all structured data for rule evaluation
    """
    # Normalize stock code
    ts_code = validate_stock_code(stock_code)

    # Determine which data source to use
    token = get_token()
    if token and _TUSHARE_AVAILABLE:
        print(f"Using Tushare Pro data source for {ts_code}...", file=sys.stderr)
        client = TushareClient(token)
        return _collect_via_tushare(ts_code, years, client)
    elif _EM_AVAILABLE:
        print(f"Tushare token not available; using EastMoney public API for {ts_code}...",
              file=sys.stderr)
        return _collect_via_eastmoney(stock_code, years)
    else:
        raise RuntimeError(
            "No data source available. Please either:\n"
            "  1. Set TUSHARE_TOKEN in .env (Tushare Pro)\n"
            "  2. Install eastmoney_data module (EastMoney public API)\n"
            "  pip install requests pandas"
        )


def _collect_via_tushare(ts_code: str, years: int, client) -> dict:
    """Collect data using Tushare Pro API (original implementation)."""
    print(f"Collecting data for {ts_code}...", file=sys.stderr)

    # Collect all data sections
    stock_info = get_stock_info(client, ts_code)
    print(f"  [1/7] Basic info: {stock_info.get('name', '?')}", file=sys.stderr)

    audit = get_audit_data(client, ts_code)
    print(f"  [2/7] Audit data: {len(audit)} records", file=sys.stderr)

    income = get_income_data(client, ts_code)
    print(f"  [3/7] Income statement: {len(income)} years", file=sys.stderr)

    balance = get_balance_data(client, ts_code)
    print(f"  [4/7] Balance sheet: {len(balance)} years", file=sys.stderr)

    cashflow = get_cashflow_data(client, ts_code)
    print(f"  [5/7] Cash flow: {len(cashflow)} years", file=sys.stderr)

    indicators = get_indicator_data(client, ts_code)
    print(f"  [6/7] Financial indicators: {len(indicators)} years", file=sys.stderr)

    holders = get_holder_data(client, ts_code)
    print(f"  [7/7] Shareholders: {len(holders)} records", file=sys.stderr)

    # Trim to requested years
    if income and len(income) > years:
        income = income[:years]
    if balance and len(balance) > years:
        balance = balance[:years]
    if cashflow and len(cashflow) > years:
        cashflow = cashflow[:years]
    if indicators and len(indicators) > years:
        indicators = indicators[:years]

    # Peer comparison (can be slow, do it last)
    industry = stock_info.get("industry", "")
    print(f"  [bonus] Fetching peer data for industry: {industry}...",
          file=sys.stderr)
    peers = get_peer_data(client, ts_code, industry)
    print(f"  [bonus] Peer data: {len(peers.get('peers', []))} peers",
          file=sys.stderr)

    return {
        "stock_info": stock_info,
        "audit": audit,
        "income": income,
        "balance": balance,
        "cashflow": cashflow,
        "indicators": indicators,
        "holders": holders,
        "peers": peers,
    }


def _collect_via_eastmoney(stock_code: str, years: int) -> dict:
    """Collect data using EastMoney public API (fallback)."""
    data = em_data.collect_eastmoney_data(stock_code, years)
    # Trim to requested years
    if data.get("income") and len(data["income"]) > years:
        data["income"] = data["income"][:years]
    if data.get("balance") and len(data["balance"]) > years:
        data["balance"] = data["balance"][:years]
    if data.get("cashflow") and len(data["cashflow"]) > years:
        data["cashflow"] = data["cashflow"][:years]
    if data.get("indicators") and len(data["indicators"]) > years:
        data["indicators"] = data["indicators"][:years]
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Collect financial data for minesweeper analysis"
    )
    parser.add_argument(
        "--stock-code", required=True,
        help="Stock code (e.g., 600519, 000858.SZ)"
    )
    parser.add_argument(
        "--years", type=int, default=10,
        help="Number of years of historical data (default: 10)"
    )
    args = parser.parse_args()

    try:
        data = collect_minesweeper_data(args.stock_code, args.years)
        # Output JSON to stdout
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        error_result = {"error": str(e)}
        print(json.dumps(error_result, ensure_ascii=False), file=sys.stdout)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
