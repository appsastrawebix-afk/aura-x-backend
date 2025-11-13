import os, time, json, re, requests
from flask import Blueprint, request, jsonify
from config.firebase_config import get_db
from services.risk_manager import RiskManager
from services.angel_api import AngelSmartAPI
from services.notifier import notify_trade
from services.signal_verifier import verify_signal       # ✅ Smart signal filter
from services.market_snapshot import get_realtime_snapshot  # ✅ Snapshot feed
from controllers.mode_controller import get_mode          # ✅ Demo/Live switch

trade_bp = Blueprint("trade", __name__)
db = get_db()
rm = RiskManager()


# 🧩 Symbol Normalizer (App → AngelOne)
def normalize_symbol_for_angel(symbol: str):
    """Convert NIFTY24NOV22500CE → NIFTY28NOV24C22500"""
    symbol = symbol.upper()
    if not symbol.endswith(("CE", "PE")):
        return symbol
    match = re.search(r"([A-Z]+)(\d{2})([A-Z]{3})(\d+)(CE|PE)", symbol)
    if not match:
        return symbol
    base, year, month, strike, opt_type = match.groups()
    expiry_day = "28"  # 🔹 monthly expiry assumed
    return f"{base}{expiry_day}{month}{year}{opt_type[0]}{strike}"


# 🔹 Load AngelOne Contract Master
def load_contracts():
    """Load angel_contracts.json into memory"""
    try:
        path = os.path.join(os.getcwd(), "data", "angel_contracts.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                contracts = json.load(f)
            lookup = {
                c["symbol"].upper(): {"token": c["token"], "exchange": c["exch_seg"]}
                for c in contracts
            }
            print(f"✅ Loaded {len(lookup)} contract symbols.")
            return lookup
    except Exception as e:
        print("⚠️ Contract Master Load Error:", e)
    return {}

contracts = load_contracts()


# 🚀 MAIN ROUTE — PLACE TRADE
@trade_bp.route("/place", methods=["POST"])
def place_trade():
    start_time = time.time()

    try:
        data = request.get_json(force=True)
        uid = data.get("uid")
        symbol = data.get("symbol", "").upper()
        txn_type = data.get("transaction_type", "").upper()
        entry_price = float(data.get("price", 0))
        capital = float(data.get("capital", 100000))
        candles = data.get("candles", [])
        qty_input = int(data.get("quantity", 0))
        confidence = float(data.get("confidence", 90))

        # Basic input validation
        if not uid or not symbol or txn_type not in ["BUY", "SELL"]:
            return jsonify({"error": "uid, symbol आणि transaction_type आवश्यक आहेत"}), 400

        # 🧠 Mode check
        mode = get_mode()
        print(f"💼 Mode: {mode.upper()} | Symbol: {symbol} | Type: {txn_type}")

        # ⚙️ 1️⃣ — Signal Verification
        snapshot = get_realtime_snapshot(symbol)
        verification = verify_signal(data, snapshot)

        if verification["action"] == "SKIP":
            return jsonify({
                "message": "❌ Signal filtered out by AURA-X Verifier",
                "score": verification["score"],
                "reasons": verification["reasons"]
            }), 200

        normalized_symbol = normalize_symbol_for_angel(symbol)

        # 🧮 2️⃣ — Risk & SL/Target Computation
        if candles and entry_price > 0:
            risk_data = rm.compute_sl_target_from_atr(candles, entry_price, txn_type)
            stoploss, target, atr = risk_data["stoploss"], risk_data["target"], risk_data["atr"]
        else:
            atr = 15
            stoploss = entry_price - 15 if txn_type == "BUY" else entry_price + 15
            target = entry_price + 45 if txn_type == "BUY" else entry_price - 45

        qty = qty_input if qty_input > 0 else rm.calculate_quantity(capital, entry_price, stoploss)
        if qty <= 0:
            return jsonify({"error": "Quantity 0 आली (risk/capital कमी आहे)"}), 400

        # 🛑 3️⃣ — Capital Protection
        allowed, pnl, limit = rm.check_daily_loss_limit(uid, capital)
        if not allowed:
            return jsonify({
                "error": f"🚫 Daily loss limit reached (P&L {pnl}, Limit {limit})"
            }), 403

        # 🧭 4️⃣ — Contract Lookup
        contract_info = contracts.get(normalized_symbol)
        if not contract_info:
            for s, v in contracts.items():
                if normalized_symbol in s:
                    contract_info = v
                    break
        if not contract_info:
            return jsonify({"error": f"Symbol not found in Contract Master: {normalized_symbol}"}), 400

        exchange, symboltoken = contract_info["exchange"], contract_info["token"]

        # ✍️ Base Trade Log
        trade_log = {
            "symbol": normalized_symbol,
            "exchange": exchange,
            "type": txn_type,
            "quantity": qty,
            "entry_price": entry_price,
            "stoploss": stoploss,
            "target": target,
            "atr": atr,
            "confidence": confidence,
            "verify_score": verification["score"],
            "decision_reasons": verification["reasons"],
            "timestamp": int(time.time()),
            "status": "PENDING"
        }

        # 🧪 5️⃣ — DEMO MODE
        if mode == "demo":
            trade_log.update({
                "status": "SIMULATED",
                "order_id": f"DEMO-{int(time.time())}"
            })
            db.child("trades").child(uid).push(trade_log)
            latency = round((time.time() - start_time) * 1000)
            notify_trade(symbol, txn_type, entry_price, target, stoploss, confidence, trade_log["order_id"], latency)
            print(f"🧪 Demo Trade simulated successfully ({latency} ms)")
            return jsonify({"message": "✅ Demo trade simulated", "trade_log": trade_log}), 200

        # 🟢 6️⃣ — LIVE MODE
        broker_info = db.child("broker_tokens").get()
        if not broker_info:
            return jsonify({"error": "No broker token found"}), 404

        client_id = list(broker_info.keys())[0]
        access_token = broker_info[client_id].get("access_token")
        if not access_token:
            return jsonify({"error": "Access token missing"}), 401

        # 🪙 SmartAPI payload
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-PrivateKey": os.getenv("ANGEL_API_KEY"),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "variety": "NORMAL",
            "tradingsymbol": normalized_symbol,
            "symboltoken": symboltoken,
            "transactiontype": txn_type,
            "exchange": exchange,
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": entry_price,
            "squareoff": str(target),
            "stoploss": str(stoploss),
            "quantity": qty
        }

        print("📤 Sending SmartAPI payload:", payload)
        res = requests.post(
            "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/placeOrder",
            json=payload, headers=headers, timeout=10
        )

        raw_text = res.text.strip()
        print("🟠 SmartAPI Response:", raw_text or "<EMPTY>", "| Code:", res.status_code)

        # Broker Response Handling
        try:
            data_res = res.json()
        except:
            return jsonify({"error": "Invalid response from broker", "raw": raw_text}), 502

        # 🔁 Token refresh on expiry
        if "Invalid Session" in str(data_res):
            AngelSmartAPI().get_access_token()
            return jsonify({"error": "Session expired — token refreshed"}), 401

        # ✅ Success Case
        if data_res.get("status") and data_res.get("data", {}).get("orderid"):
            trade_id = data_res["data"]["orderid"]
            trade_log.update({"status": "SUCCESS", "trade_id": trade_id})
            db.child("trades").child(uid).push(trade_log)
            rm.save_trade_plan(uid, trade_log)
            latency = round((time.time() - start_time) * 1000)
            notify_trade(symbol, txn_type, entry_price, target, stoploss, confidence, trade_id, latency)
            return jsonify({"message": "✅ Live trade placed", "trade_log": trade_log}), 200

        # ❌ Failure
        return jsonify({
            "error": "Trade failed ❌",
            "broker_response": data_res
        }), 400

    except Exception as e:
        print("⚠️ Trade Error:", e)
        return jsonify({"error": str(e)}), 500
