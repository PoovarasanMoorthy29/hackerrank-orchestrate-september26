"""
Message Evidence Parser for Financial Updates and Overrides.
"""

import csv
import re
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

@dataclass
class UserMessageUpdates:
    user_id: str
    salary_amount_override: Optional[float] = None
    salary_date_override: Optional[date] = None
    seasonal_contract_ended: bool = False
    rent_increase_percent: Optional[float] = None
    pending_payouts_unconfirmed: List[str] = field(default_factory=list)

class MessageParser:
    def __init__(self, messages_csv_path: str = "dataset/messages.csv"):
        self.user_updates: Dict[str, UserMessageUpdates] = {}
        self._parse_messages(messages_csv_path)

    def _parse_messages(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                msgs = list(reader)
        except FileNotFoundError:
            return

        for m in msgs:
            uid = m['user_id'].strip()
            txt = m['message_text'].strip()
            if not uid:
                continue

            if uid not in self.user_updates:
                self.user_updates[uid] = UserMessageUpdates(user_id=uid)
            
            up = self.user_updates[uid]

            # Seasonal contract ended
            if re.search(r'seasonal contract has ended', txt, re.IGNORECASE):
                up.seasonal_contract_ended = True

            # Salary date override
            m_date = re.search(r'confirmed salary is now expected on\s+(\d{4}-\d{2}-\d{2})', txt, re.IGNORECASE)
            if m_date:
                try:
                    up.salary_date_override = datetime.strptime(m_date.group(1), "%Y-%m-%d").date()
                except ValueError:
                    pass

            # Salary amount override
            # Indonesian pattern: naik menjadi IDR 42750000 / IDR 17290000
            m_sal_idr = re.search(r'(?:naik menjadi|gaji pokok|gaji bulanan|gaji)*\s*(?:IDR|USD|EUR|ZAR|INR)\s*([\d\.\,]+)', txt, re.IGNORECASE)
            # English pattern: increased to / reduced to / salary is / first salary will be ...
            m_sal_eng = re.search(r'(?:increased to|reduced to|salary is|first salary will be|monthly pay is|remaining confirmed monthly salary is)\s+(?:IDR|USD|EUR|ZAR|INR)?\s*([\d\.\,]+)', txt, re.IGNORECASE)

            if m_sal_eng:
                amt_str = m_sal_eng.group(1).replace(',', '')
                try:
                    up.salary_amount_override = float(amt_str)
                except ValueError:
                    pass
            elif m_sal_idr and ('naik menjadi' in txt or 'Gaji' in txt):
                amt_str = m_sal_idr.group(1).replace(',', '')
                try:
                    up.salary_amount_override = float(amt_str)
                except ValueError:
                    pass

            # Rent increase
            m_rent = re.search(r'increases monthly rent by\s+(\d+(?:\.\d+)?)%', txt, re.IGNORECASE)
            if m_rent:
                try:
                    up.rent_increase_percent = float(m_rent.group(1))
                except ValueError:
                    pass

    def get_updates_for_user(self, user_id: str) -> UserMessageUpdates:
        return self.user_updates.get(user_id, UserMessageUpdates(user_id=user_id))
