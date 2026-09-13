"""
Message Evidence Parser for Financial Updates and Overrides.
Combines deterministic structural extraction with LLM structured parsing when available.
"""

import csv
import re
import os
import json
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

@dataclass
class UserMessageUpdates:
    user_id: str
    salary_amount_override: Optional[float] = None
    salary_date_override: Optional[date] = None
    seasonal_contract_ended: bool = False
    unconfirmed_gig_income: bool = False
    rent_increase_percent: Optional[float] = None
    recurring_expense_additions: List[Dict[str, Any]] = field(default_factory=list)
    invoice_approved_amount: Optional[float] = None
    invoice_settlement_date: Optional[date] = None
    event_amendments: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    event_cancellations: List[str] = field(default_factory=list)

class MessageParser:
    def __init__(self, messages_csv_path: str = "dataset/messages.csv"):
        self.user_updates: Dict[str, UserMessageUpdates] = {}
        self._parse_messages(messages_csv_path)

    def _parse_with_llm_if_available(self, text: str) -> Optional[Dict[str, Any]]:
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")

        prompt = f"""Extract financial facts from this message into JSON format with keys:
- salary_amount (float or null)
- salary_date (YYYY-MM-DD or null)
- seasonal_contract_ended (boolean)
- unconfirmed_gig_income (boolean)
- rent_increase_percent (float or null)
- invoice_approved_amount (float or null)
- invoice_settlement_date (YYYY-MM-DD or null)
Message: "{text}"
"""
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                res = model.generate_content(prompt)
                match = re.search(r'\{.*\}', res.text, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
            except Exception:
                pass

        if openai_key:
            try:
                import requests
                headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}
                }
                res = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=10)
                if res.status_code == 200:
                    return json.loads(res.json()['choices'][0]['message']['content'])
            except Exception:
                pass

        return None

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
            rel_event = m['related_event_id'].strip()
            if not uid:
                continue

            if uid not in self.user_updates:
                self.user_updates[uid] = UserMessageUpdates(user_id=uid)

            up = self.user_updates[uid]

            # 1. Try LLM extraction if available
            llm_res = self._parse_with_llm_if_available(txt)
            if llm_res:
                if llm_res.get('salary_amount'):
                    up.salary_amount_override = float(llm_res['salary_amount'])
                if llm_res.get('salary_date'):
                    try:
                        up.salary_date_override = datetime.strptime(llm_res['salary_date'], "%Y-%m-%d").date()
                    except ValueError:
                        pass
                if llm_res.get('seasonal_contract_ended'):
                    up.seasonal_contract_ended = True
                if llm_res.get('unconfirmed_gig_income'):
                    up.unconfirmed_gig_income = True
                if llm_res.get('rent_increase_percent'):
                    up.rent_increase_percent = float(llm_res['rent_increase_percent'])
                if llm_res.get('invoice_approved_amount'):
                    up.invoice_approved_amount = float(llm_res['invoice_approved_amount'])
                if llm_res.get('invoice_settlement_date'):
                    try:
                        up.invoice_settlement_date = datetime.strptime(llm_res['invoice_settlement_date'], "%Y-%m-%d").date()
                    except ValueError:
                        pass

            # 2. General Deterministic Structural Parsing
            # Contract ends
            if re.search(r'contract\s+(?:has\s+)?ended|contract\s+terminated|no\s+renewal', txt, re.IGNORECASE):
                up.seasonal_contract_ended = True

            # Unconfirmed gig payouts / unwithdrawable balance / pending earnings
            if re.search(r'payout\s+is\s+still\s+pending|can\s+change\s+until|not\s+withdrawable|balance\s+isn[’\']t\s+withdrawable|unconfirmed|pending\s+assessment', txt, re.IGNORECASE):
                up.unconfirmed_gig_income = True

            # Salary payday override
            m_date = re.search(r'(?:expected|scheduled|resumes|payday|credit date)\s+(?:on|is)\s+(\d{4}-\d{2}-\d{2})', txt, re.IGNORECASE)
            if m_date:
                try:
                    up.salary_date_override = datetime.strptime(m_date.group(1), "%Y-%m-%d").date()
                except ValueError:
                    pass

            # Salary amount override (supports English, Indonesian, EUR, USD, ZAR, INR, IDR)
            m_sal = re.search(r'(?:gaji|salary|pay|monthly pay|reduced to|increased to|resumes|first salary)\s*(?:is|now|to|=|:)?\s*(?:IDR|USD|EUR|ZAR|INR|Rp|\$|€|₹)?\s*([\d\.\,]+)', txt, re.IGNORECASE)
            if m_sal:
                amt_str = m_sal.group(1).replace(',', '')
                try:
                    val = float(amt_str)
                    if val > 10.0:
                        up.salary_amount_override = val
                except ValueError:
                    pass

            # Percentage rent / expense increases
            m_rent = re.search(r'(?:rent|lease|housing)\s+(?:increases|up|increased)\s+by\s+(\d+(?:\.\d+)?)%', txt, re.IGNORECASE)
            if m_rent:
                try:
                    up.rent_increase_percent = float(m_rent.group(1))
                except ValueError:
                    pass

            # Invoice approval
            m_inv = re.search(r'approved\s+(?:an\s+)?invoice\s+payment\s+of\s+(?:IDR|USD|EUR|ZAR|INR)?\s*([\d\.\,]+)', txt, re.IGNORECASE)
            if m_inv:
                try:
                    up.invoice_approved_amount = float(m_inv.group(1).replace(',', ''))
                except ValueError:
                    pass

            # Specific Event Amendments / Cancellations linked by related_event_id
            if rel_event:
                if re.search(r'cancelled|voided|refunded|withdrawn', txt, re.IGNORECASE):
                    up.event_cancellations.append(rel_event)
                m_evt_amt = re.search(r'(?:amount|total|adjusted to|new amount)\s*(?:is|:)?\s*(?:IDR|USD|EUR|ZAR|INR)?\s*([\d\.\,]+)', txt, re.IGNORECASE)
                if m_evt_amt:
                    try:
                        up.event_amendments[rel_event] = {'amount': float(m_evt_amt.group(1).replace(',', ''))}
                    except ValueError:
                        pass

    def get_updates_for_user(self, user_id: str) -> UserMessageUpdates:
        return self.user_updates.get(user_id, UserMessageUpdates(user_id=user_id))
