import csv
from datetime import datetime, date
from typing import Dict, Tuple, List, Optional

class CurrencyConverter:
    def __init__(self, exchange_rates_csv_path: str = "dataset/exchange_rates.csv"):
        # Map (rate_date_str, from_curr, to_curr) -> rate
        self.rates: Dict[Tuple[str, str, str], float] = {}
        # Map (from_curr, to_curr) -> Sorted list of (rate_date, rate)
        self.pair_rates: Dict[Tuple[str, str], List[Tuple[date, float]]] = {}
        # Track missing rate pairs when conversion cannot be performed
        self.missing_rate_pairs: List[Tuple[str, str, date]] = []
        self._load_rates(exchange_rates_csv_path)

    def _load_rates(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                temp_pairs: Dict[Tuple[str, str], List[Tuple[date, float]]] = {}
                for row in reader:
                    rdate_str = row['rate_date'].strip()
                    fc = row['from_currency'].strip()
                    tc = row['to_currency'].strip()
                    rate = float(row['rate'])
                    
                    self.rates[(rdate_str, fc, tc)] = rate
                    rdate = datetime.strptime(rdate_str, "%Y-%m-%d").date()
                    
                    pair = (fc, tc)
                    temp_pairs.setdefault(pair, []).append((rdate, rate))

                for pair, rate_list in temp_pairs.items():
                    rate_list.sort(key=lambda x: x[0])
                    self.pair_rates[pair] = rate_list

        except FileNotFoundError:
            pass

    def get_exchange_rate(self, from_curr: str, to_curr: str, target_date: date) -> Optional[float]:
        if from_curr == to_curr:
            return 1.0

        date_str = target_date.strftime("%Y-%m-%d")
        key = (date_str, from_curr, to_curr)

        # 1. Direct rate on target_date
        if key in self.rates:
            return self.rates[key]

        # 2. Most recent rate on or before target_date
        pair = (from_curr, to_curr)
        if pair in self.pair_rates:
            valid_rates = [r for d, r in self.pair_rates[pair] if d <= target_date]
            if valid_rates:
                return valid_rates[-1]
            # If all available rate dates are after target_date, pick earliest available
            return self.pair_rates[pair][0][1]

        # 3. Inverse rate check
        rev_pair = (to_curr, from_curr)
        rev_key = (date_str, to_curr, from_curr)
        if rev_key in self.rates and self.rates[rev_key] > 0:
            return 1.0 / self.rates[rev_key]

        if rev_pair in self.pair_rates:
            valid_rev_rates = [r for d, r in self.pair_rates[rev_pair] if d <= target_date]
            if valid_rev_rates and valid_rev_rates[-1] > 0:
                return 1.0 / valid_rev_rates[-1]
            if self.pair_rates[rev_pair] and self.pair_rates[rev_pair][0][1] > 0:
                return 1.0 / self.pair_rates[rev_pair][0][1]

        return None

    def convert(self, amount: Optional[float], from_curr: str, to_curr: str, target_date: date) -> Optional[float]:
        if amount is None:
            return None
        if from_curr == to_curr or amount == 0.0:
            return amount

        rate = self.get_exchange_rate(from_curr, to_curr, target_date)
        if rate is not None:
            return amount * rate
        
        # Missing exchange rate: record pair and return None (unresolved amount)
        self.missing_rate_pairs.append((from_curr, to_curr, target_date))
        return None

