import json, os

class TokenLookup:
    def __init__(self):
        self.tokens = {}
        path = os.path.join(os.getcwd(), "data", "angel_contracts.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                for item in json.load(f):
                    self.tokens[item["symbol"].upper()] = {
                        "token": item["token"],
                        "exchange": item["exch_seg"]
                    }

    def get_symbol_info(self, symbol):
        symbol = symbol.upper()
        info = self.tokens.get(symbol)
        if not info:
            # try substring match (sometimes Angel uses slightly different casing)
            for s, v in self.tokens.items():
                if symbol in s:
                    return v
            return None
        return info
