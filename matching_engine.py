# ============================================================
# matching_engine.py
# ─────────────────────────────────────────────────────────
# WHAT IT DOES:
#   1. Reads Inventory (Sheet A) + Client Requests (Sheet B)
#      from your Google Sheet
#   2. Runs numerical fuzzy matching on price, units,
#      ticket size with configurable tolerance bands
#   3. Scores each deal-client pair (0-100)
#   4. Writes matches to Sheet C (Matches tab)
#   5. Saves call_queue.json → used by call_orchestrator.py
#
# HOW TO RUN:
#   python matching_engine.py
#
# OR triggered automatically by Make.com via webhook_server.py
# ============================================================

import pandas as pd
import json
import datetime
import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# ── CONFIGURATION ────────────────────────────────────────────
SHEET_ID             = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE",
                                  "config/service_account.json")

# Matching tolerance — adjust these to widen or narrow results
PRICE_TOLERANCE     = 0.15   # ±15% of client's budget_max
TICKET_TOLERANCE    = 0.20   # ±20% of client's ticket_size_max
UNIT_TOLERANCE      = 1      # client desired_units ± this value
MIN_SCORE           = 50     # scores below this are discarded


# ── GOOGLE SHEETS ────────────────────────────────────────────
def connect_to_sheets():
    """Authenticate and return a gspread client."""
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = Credentials.from_service_account_file(
                 SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    print("✅ Connected to Google Sheets")
    return gc


def load_sheets(gc):
    """
    Load Inventory and Clients worksheets.
    Returns (inventory_df, clients_df, workbook)
    """
    wb           = gc.open_by_key(SHEET_ID)
    inventory_ws = wb.worksheet("Inventory")   # Sheet A — your deals
    clients_ws   = wb.worksheet("Clients")     # Sheet B — client requests

    inventory = pd.DataFrame(inventory_ws.get_all_records())
    clients   = pd.DataFrame(clients_ws.get_all_records())

    print(f"📊 Loaded: {len(inventory)} deals | {len(clients)} client requests")
    return inventory, clients, wb


# ── DATA NORMALIZATION ────────────────────────────────────────
def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardize column names and parse numeric fields.
    Handles commas, currency symbols, extra spaces.
    """
    # Normalize column names → lowercase with underscores
    df.columns = (df.columns
                  .str.strip()
                  .str.lower()
                  .str.replace(" ", "_")
                  .str.replace("-", "_"))

    # Parse numeric columns — strip any non-numeric characters
    numeric_cols = [
        "price", "units", "ticket_size",
        "budget_max", "budget_min",
        "desired_units", "ticket_size_max"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = (df[col]
                       .astype(str)
                       .str.replace(r"[^\d.]", "", regex=True)
                       .replace("", "0")
                       .astype(float))

    # Normalize phone columns
    phone_cols = ["owner_phone", "broker_phone", "phone", "client_phone"]
    for col in phone_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Normalize date columns
    if "request_date" in df.columns:
        df["request_date"] = pd.to_datetime(
            df["request_date"], errors="coerce"
        ).fillna(pd.Timestamp.now())

    return df


# ── MATCHING LOGIC ────────────────────────────────────────────
def calculate_match_score(deal: dict, client: dict) -> dict:
    """
    Score a single deal against a single client request.

    Scoring breakdown (max 100 pts):
      Price proximity  → 30 pts
      Ticket size      → 25 pts
      Unit exactness   → 25 pts
      Request recency  → 20 pts

    Hard filters applied FIRST — if either fails, score = 0.
    """
    # ── HARD FILTER 1: Price Band ─────────────────────────────
    budget = float(client.get("budget_max", 0) or 0)
    price  = float(deal.get("price", 0) or 0)

    if budget == 0 or price == 0:
        return {"match": False, "score": 0,
                "reason": "Missing price or budget data"}

    price_low  = budget * (1 - PRICE_TOLERANCE)
    price_high = budget * (1 + PRICE_TOLERANCE)

    if not (price_low <= price <= price_high):
        return {"match": False, "score": 0,
                "reason": f"Price {price:,.0f} outside band "
                          f"{price_low:,.0f}–{price_high:,.0f}"}

    # ── HARD FILTER 2: Unit Count Band ───────────────────────
    deal_units   = float(deal.get("units", 0) or 0)
    client_units = float(client.get("desired_units", 0) or 0)

    if abs(deal_units - client_units) > UNIT_TOLERANCE:
        return {"match": False, "score": 0,
                "reason": f"Units {deal_units} vs client need {client_units}"}

    # ── SOFT SCORE: Price Proximity (30 pts) ─────────────────
    score   = 0
    reasons = []
    proximity = 1 - (abs(price - budget) / budget)
    pts = round(proximity * 30)
    score += pts
    reasons.append(f"Price proximity {pts}/30")

    # ── SOFT SCORE: Ticket Size (25 pts) ─────────────────────
    deal_ticket   = float(deal.get("ticket_size", 0) or 0)
    client_ticket = float(client.get("ticket_size_max", 0) or 0)

    if client_ticket > 0 and deal_ticket > 0:
        diff = abs(deal_ticket - client_ticket) / client_ticket
        if diff <= 0.10:
            score += 25; reasons.append("Ticket excellent 25/25")
        elif diff <= TICKET_TOLERANCE:
            score += 15; reasons.append("Ticket acceptable 15/25")
        else:
            score += 5;  reasons.append("Ticket stretched 5/25")
    else:
        score += 10  # Partial credit when ticket data missing

    # ── SOFT SCORE: Unit Exactness (25 pts) ──────────────────
    if deal_units == client_units:
        score += 25; reasons.append("Units exact 25/25")
    else:
        score += 12; reasons.append("Units ±1 variance 12/25")

    # ── SOFT SCORE: Request Recency (20 pts) ─────────────────
    try:
        req_date = client.get("request_date")
        if hasattr(req_date, "date"):
            days_old = (datetime.date.today() - req_date.date()).days
        else:
            days_old = 10  # Default if date unavailable
        recency = max(0, 20 - days_old)
    except Exception:
        recency = 10
    score += recency
    reasons.append(f"Recency {recency}/20")

    # ── TIER ASSIGNMENT ───────────────────────────────────────
    if score < MIN_SCORE:
        return {"match": False, "score": score,
                "reason": f"Score {score} below threshold {MIN_SCORE}"}

    tier = "HIGH" if score >= 70 else "MEDIUM"

    return {
        "match":        True,
        "score":        score,
        "tier":         tier,
        "reasons":      " | ".join(reasons),
        "deal_id":      str(deal.get("deal_id", "")),
        "client_id":    str(client.get("client_id", "")),
        "property":     deal.get("property_name", ""),
        "location":     deal.get("location", ""),
        "price":        price,
        "units":        deal_units,
        "ticket_size":  deal_ticket,
        "owner_phone":  str(deal.get("owner_phone", "")),
        "broker_phone": str(deal.get("broker_phone", "")),
        "client_phone": str(client.get("phone",
                           client.get("client_phone", ""))),
        "client_name":  client.get("client_name", ""),
        "matched_at":   datetime.datetime.now().isoformat(),
        "call_status":  "pending",
    }


def run_matching_engine(inventory: pd.DataFrame,
                        clients: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-match all deals against all client requests.
    Returns sorted DataFrame of matches (highest score first).
    One deal is matched to at most ONE client (the best score).
    """
    results = []

    for _, client in clients.iterrows():
        for _, deal in inventory.iterrows():
            r = calculate_match_score(deal.to_dict(), client.to_dict())
            if r["match"]:
                results.append(r)

    if not results:
        print("⚠️  No matches found — check your data ranges and tolerances")
        return pd.DataFrame()

    df = (pd.DataFrame(results)
          .sort_values("score", ascending=False)
          .drop_duplicates(subset=["deal_id"])   # Best client per deal only
          .reset_index(drop=True))

    high = (df["tier"] == "HIGH").sum()
    med  = (df["tier"] == "MEDIUM").sum()
    print(f"✅ Matching complete: {len(df)} matches  "
          f"({high} HIGH  |  {med} MEDIUM)")
    return df


# ── EXPORT ───────────────────────────────────────────────────
def export_matches(matches_df: pd.DataFrame, wb) -> int:
    """
    1. Write matches to Google Sheet (tab: Matches)
    2. Save local CSV backup
    3. Build call_queue.json for call orchestrator
    Returns: number of calls queued
    """
    if matches_df.empty:
        print("⚠️  Nothing to export — matches DataFrame is empty")
        return 0

    os.makedirs("data", exist_ok=True)

    # ── 1. Google Sheet: Matches tab ─────────────────────────
    try:
        try:
            ws = wb.worksheet("Matches")
        except gspread.exceptions.WorksheetNotFound:
            ws = wb.add_worksheet(title="Matches", rows=1000, cols=25)

        ws.clear()

        # Convert to strings so gspread doesn't choke on floats
        export_df = matches_df.copy()
        for col in export_df.columns:
            export_df[col] = export_df[col].astype(str)

        ws.update([export_df.columns.tolist()] +
                   export_df.values.tolist())
        print("✅ Matches → Google Sheet (Matches tab)")

    except Exception as e:
        print(f"⚠️  Google Sheets write failed: {e}")

    # ── 2. Local CSV backup ───────────────────────────────────
    matches_df.to_csv("data/matches.csv", index=False, encoding="utf-8-sig")
    print("✅ Matches → data/matches.csv")

    # ── 3. Build call_queue.json ──────────────────────────────
    #
    # Call ORDER matters:
    #   1st → Owner   (verify property is still available)
    #   2nd → Broker  (coordinate logistics)
    #   3rd → Client  (pitch the deal)
    #
    call_queue = []

    def is_valid_phone(p: str) -> bool:
        return bool(p and p != "nan" and p.strip() and
                    p.strip() not in ("", "0", "None"))

    for _, row in matches_df.iterrows():
        base = {
            "deal_id":     row["deal_id"],
            "client_id":   row["client_id"],
            "property":    row["property"],
            "location":    row["location"],
            "price":       float(row["price"]),
            "units":       float(row["units"]),
            "ticket_size": float(row["ticket_size"]),
            "score":       int(row["score"]),
            "tier":        row["tier"],
            "client_name": row["client_name"],
            "status":      "pending",
        }

        if is_valid_phone(row["owner_phone"]):
            call_queue.append({**base,
                "call_type": "owner",
                "phone": row["owner_phone"]})

        if is_valid_phone(row["broker_phone"]):
            call_queue.append({**base,
                "call_type": "broker",
                "phone": row["broker_phone"]})

        if is_valid_phone(row["client_phone"]):
            call_queue.append({**base,
                "call_type": "client",
                "phone": row["client_phone"]})

    with open("data/call_queue.json", "w", encoding="utf-8") as f:
        json.dump(call_queue, f, ensure_ascii=False, indent=2)

    print(f"✅ Call queue → data/call_queue.json  ({len(call_queue)} calls)")
    return len(call_queue)


# ── STANDALONE ENTRY POINT ────────────────────────────────────
def main():
    print("\n" + "="*55)
    print("  MATCHING ENGINE — AI Real Estate Agent")
    print("="*55 + "\n")

    gc                     = connect_to_sheets()
    inventory, clients, wb = load_sheets(gc)
    inventory              = normalize(inventory)
    clients                = normalize(clients)
    matches_df             = run_matching_engine(inventory, clients)
    n_calls                = export_matches(matches_df, wb)

    print(f"\n🎯 Done — {n_calls} calls queued")
    print("   Next: python call_orchestrator.py\n")
    return {"matches": len(matches_df), "calls_queued": n_calls}


if __name__ == "__main__":
    main()