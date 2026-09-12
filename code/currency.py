"""
Currency Conversion Engine using exchange_rates.csv.
"""

import csv
from datetime import datetime, date
from typing import Dict, Tuple

class CurrencyConverter:
    def __init__(self, exchange_rates_csv_path: str = "dataset/exchange_rates.csv"):
        # Map (rate_date_str, from_curr, to_curr) -> rate
        self.rates: Dict[Tuple[str, str, str], float] = {}
        self.all_dates_rates: Dict[Tuple[str, str], Dict[str, float]] = {}
        self._load_rates(exchange_rates_csv_path)

    def _load_rates(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rdate = row['rate_date'].strip()
                    fc = row['from_currency'].strip()
                    tc = row['to_currency'].strip()
                    rate = float(row['rate'])
                    self.rates[(rdate, fc, tc)] = rate
                    
                    pair = (fc, tc)
                    if pair not in self.all_dates_rates:
                        self.all_dates_rates[pair] = {}
                    self.all_dates_rates[pair][rdate] = rate
        except FileNotFoundError:
            pass

    def convert(self, amount: float, from_curr: str, to_curr: str, target_date: date) -> float:
        if from_curr == to_curr or amount == 0.0:
            return amount
        
        date_str = target_date.strftime("%Y-%m-%d")
        key = (date_str, from_curr, to_curr)
        if key in self.rates:
            return amount * self.rates[key]
        
        # Fallback: lookup closest available date for this currency pair
        pair = (from_curr, to_curr)
        if pair in self.all_dates_rates and self.all_dates_rates[pair]:
            # Sort by absolute date distance
            dates = self.all_dates_rates[pair]
            closest_date_str = min(dates.keys(), key=lambda d: abs((datetime.strptime(d, "%Y-%m-%d").date() - target_date).days))
            return amount * dates[closest_date_str]
        
        # Reverse conversion fallback
        rev_pair = (to_curr, from_curr)
        if rev_pair in self.all_dates_rates and self.all_dates_rates[rev_pair]:
            dates = self.all_dates_rates[rev_pair]
            closest_date_str = min(dates.keys(), key=lambda d: abs((datetime.strptime(d, "%Y-%m-%d").date() - target_date).days))
            rev_rate = dates[closest_date_str]
            if rev_rate > 0:
                return amount / rev_rate

        return amount
