"""
Financial Event Reconstruction Engine.
Normalizes, filters, converts currency, applies message/image overrides, handles linked events & lifecycle rules, and reconstructs recurring cash flow.
"""

import csv
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from code.models import FinancialProfile, FinancialEvent
from code.currency import CurrencyConverter
from code.image_extractor import ImageExtractor
from code.message_parser import MessageParser, UserMessageUpdates

class EventReconstructor:
    def __init__(self,
                 events_csv_path: str = "dataset/financial_events.csv",
                 profiles_csv_path: str = "dataset/financial_profiles.csv",
                 exchange_rates_csv_path: str = "dataset/exchange_rates.csv",
                 images_csv_path: str = "dataset/images.csv",
                 messages_csv_path: str = "dataset/messages.csv"):

        self.currency_converter = CurrencyConverter(exchange_rates_csv_path)
        self.image_extractor = ImageExtractor(images_csv_path)
        self.message_parser = MessageParser(messages_csv_path)
        self.profiles: Dict[str, FinancialProfile] = {}
        self.user_events: Dict[str, List[FinancialEvent]] = {}

        self.unresolved_amount_event_ids_by_user: Dict[str, List[str]] = {}
        self._load_profiles(profiles_csv_path)
        self._load_events(events_csv_path)

    @property
    def unresolved_amount_event_ids(self) -> List[str]:
        return [eid for eids in self.unresolved_amount_event_ids_by_user.values() for eid in eids]

    def _load_profiles(self, path: str):
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row['user_id'].strip()
                max_inst = row['max_installment_months'].strip()
                self.profiles[uid] = FinancialProfile(
                    user_id=uid,
                    home_currency=row['home_currency'].strip(),
                    current_available_balance=float(row['current_available_balance']),
                    minimum_balance_to_keep=float(row['minimum_balance_to_keep']),
                    financial_priorities=[x.strip() for x in row['financial_priorities'].split('|') if x.strip()],
                    expense_categories_to_protect=[x.strip() for x in row['expense_categories_to_protect'].split('|') if x.strip()],
                    expense_categories_user_is_willing_to_reduce=[x.strip() for x in row['expense_categories_user_is_willing_to_reduce'].split('|') if x.strip()],
                    expense_categories_user_is_willing_to_stop=[x.strip() for x in row['expense_categories_user_is_willing_to_stop'].split('|') if x.strip()],
                    payment_methods_user_will_consider=[x.strip() for x in row['payment_methods_user_will_consider'].split('|') if x.strip()],
                    max_installment_months=int(max_inst) if max_inst and max_inst.isdigit() else None
                )

    def _load_events(self, path: str):
        raw_events_by_user: Dict[str, List[Dict[str, Any]]] = {}
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row['user_id'].strip()
                raw_events_by_user.setdefault(uid, []).append(row)

        for uid, rows in raw_events_by_user.items():
            profile = self.profiles.get(uid)
            home_curr = profile.home_currency if profile else "USD"
            msg_up = self.message_parser.get_updates_for_user(uid)

            # 1. Identify superseded linked events and message cancellations
            superseded_event_ids: Set[str] = set()
            for eid in msg_up.event_cancellations:
                superseded_event_ids.add(eid)

            for row in rows:
                eid = row['event_id'].strip()
                linked_id = row['linked_event_id'].strip()
                status = row['status'].strip().lower()

                if linked_id:
                    # The newer linked record replaces/supersedes the earlier linked event
                    if status in ['settled', 'scheduled', 'pending', 'cancelled', 'amended']:
                        superseded_event_ids.add(linked_id)

            # 2. Process and normalize active events
            parsed_events: List[FinancialEvent] = []
            for row in rows:
                eid = row['event_id'].strip()
                status = row['status'].strip().lower()

                # Filter out cancelled, failed, unrealized, or superseded events
                if status in ['failed', 'cancelled', 'unrealized'] or eid in superseded_event_ids:
                    continue

                etype = row['event_type'].strip().lower()
                desc = row['description'].strip()
                cat = row['category'].strip().lower()
                direction = row['direction'].strip().lower()
                curr = row['currency'].strip()
                edate = datetime.strptime(row['event_date'].strip(), "%Y-%m-%d").date()
                sdate_str = row['settlement_date'].strip()
                sdate = datetime.strptime(sdate_str, "%Y-%m-%d").date() if sdate_str else edate

                # Recover missing amounts via ImageExtractor
                amt_str = row['amount'].strip()
                if amt_str:
                    amt = float(amt_str)
                else:
                    extracted = self.image_extractor.get_amount_for_event(eid)
                    if extracted is not None:
                        amt = extracted
                    elif eid in msg_up.event_amendments and 'amount' in msg_up.event_amendments[eid]:
                        amt = msg_up.event_amendments[eid]['amount']
                    else:
                        amt = None
                        self.unresolved_amount_event_ids_by_user.setdefault(uid, []).append(eid)

                # EXPLANATION OF SAFE FALLBACK (NO BLANK AS ZERO):
                # When an event amount is missing from financial_events.csv and cannot be extracted from images or messages,
                # we set amt = None and track the event ID in self.unresolved_amount_event_ids_by_user.
                # Setting amt = None (and excluding such events from cash-flow calculations in the forecaster) guarantees
                # that we do NOT treat a blank amount as 0.0. A 0.0 value would incorrectly register as zero cash impact,
                # whereas treating it as unresolved (None) explicitly flags the missing data and prevents corrupting
                # cash flow calculations with a fake $0.0 figure.

                # Apply message amendments if present for this event
                if eid in msg_up.event_amendments:
                    amd = msg_up.event_amendments[eid]
                    if 'amount' in amd:
                        amt = amd['amount']

                if amt is not None:
                    amt_home = self.currency_converter.convert(amt, curr, home_curr, sdate)
                    if amt_home is None:
                        # Exchange rate conversion failed for foreign currency event
                        if eid not in self.unresolved_amount_event_ids_by_user.get(uid, []):
                            self.unresolved_amount_event_ids_by_user.setdefault(uid, []).append(eid)
                else:
                    amt_home = None
                flex = row['flexibility'].strip().lower() if row['flexibility'] else 'fixed'
                min_allowed = float(row['minimum_allowed_amount']) if row['minimum_allowed_amount'].strip() else None

                event = FinancialEvent(
                    event_id=eid,
                    user_id=uid,
                    event_type=etype,
                    description=desc,
                    category=cat,
                    direction=direction,
                    amount=amt_home,
                    currency=home_curr,
                    event_date=edate,
                    settlement_date=sdate,
                    status=status,
                    linked_event_id=row['linked_event_id'].strip(),
                    flexibility=flex,
                    minimum_allowed_amount=min_allowed
                )
                parsed_events.append(event)

            self.user_events[uid] = parsed_events

    def get_profile(self, user_id: str) -> Optional[FinancialProfile]:
        return self.profiles.get(user_id)

    def get_user_events(self, user_id: str) -> List[FinancialEvent]:
        return self.user_events.get(user_id, [])

    def get_unresolved_event_ids_for_user(self, user_id: str) -> List[str]:
        return list(self.unresolved_amount_event_ids_by_user.get(user_id, []))

    def get_message_updates(self, user_id: str) -> UserMessageUpdates:
        return self.message_parser.get_updates_for_user(user_id)
