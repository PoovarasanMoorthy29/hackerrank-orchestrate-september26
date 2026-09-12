"""
90-Day Cash-Flow Forecaster and Safety Checker.
"""

from datetime import date, timedelta
from typing import Dict, List, Tuple, Optional, Set, Any
from code.models import FinancialProfile, FinancialEvent, ScheduledPayment
from code.message_parser import UserMessageUpdates

class CashFlowForecaster:
    def __init__(self, profile: FinancialProfile, events: List[FinancialEvent], message_updates: UserMessageUpdates):
        self.profile = profile
        self.events = events
        self.msg = message_updates
        self.home_currency = profile.home_currency
        self.min_balance = profile.minimum_balance_to_keep
        self.init_balance = profile.current_available_balance

    def forecast_daily_balances(self,
                                request_date: date,
                                plan_payments: List[ScheduledPayment] = None,
                                spending_changes: List[Dict[str, Any]] = None,
                                forecast_days: int = 90) -> List[Tuple[date, float]]:

        if plan_payments is None:
            plan_payments = []
        if spending_changes is None:
            spending_changes = []

        # Parse spending changes overrides
        stopped_events: Set[str] = set()
        stopped_categories: Set[str] = set()
        reduced_events: Dict[str, float] = {}

        for sc in spending_changes:
            stype = sc.get('type')
            eid = sc.get('event_id', '')
            cat = sc.get('category', '')
            if stype == 'stop':
                if eid: stopped_events.add(eid)
                if cat: stopped_categories.add(cat)
            elif stype == 'reduce_to':
                new_amt = sc.get('new_amount', 0.0)
                if eid: reduced_events[eid] = new_amt

        # Group plan payments by date
        plan_by_date: Dict[date, float] = {}
        for p in plan_payments:
            plan_by_date[p.payment_date] = plan_by_date.get(p.payment_date, 0.0) + p.amount

        # Build daily income and expense schedules for request_date -> request_date + forecast_days
        daily_income: Dict[date, float] = {}
        daily_expense: Dict[date, float] = {}

        end_date = request_date + timedelta(days=forecast_days)

        # 1. Pending debits scheduled after or on request_date
        for e in self.events:
            if e.direction == 'debit' and e.status in ['pending', 'scheduled']:
                pay_date = e.settlement_date if e.settlement_date >= request_date else request_date
                if pay_date <= end_date:
                    if e.event_id in stopped_events or e.category in stopped_categories:
                        continue
                    amt = reduced_events.get(e.event_id, e.amount)
                    daily_expense[pay_date] = daily_expense.get(pay_date, 0.0) + amt

        # 2. Confirmed Salary Income
        # Identify recurring salary pattern
        salary_events = [e for e in self.events if e.event_type == 'income' and 'salary' in e.category.lower() and e.status == 'settled']
        if salary_events and not self.msg.seasonal_contract_ended:
            latest_sal = max(salary_events, key=lambda x: x.settlement_date)
            sal_amt = self.msg.salary_amount_override if self.msg.salary_amount_override is not None else latest_sal.amount
            
            # Determine payday day of month
            payday_dom = self.msg.salary_date_override.day if self.msg.salary_date_override else latest_sal.settlement_date.day

            curr_d = request_date
            while curr_d <= end_date:
                # Check if payday matches
                # Handle month end if payday_dom > 28
                max_dom_in_month = (date(curr_d.year, curr_d.month % 12 + 1, 1) - timedelta(days=1)).day if curr_d.month < 12 else 31
                actual_payday = min(payday_dom, max_dom_in_month)
                if curr_d.day == actual_payday and curr_d > latest_sal.settlement_date:
                    daily_income[curr_d] = daily_income.get(curr_d, 0.0) + sal_amt
                curr_d += timedelta(days=1)

        # 3. Monthly Recurring Expenses (rent, utilities, insurance, education, healthcare, subscriptions)
        monthly_cats = {'rent', 'housing', 'utilities', 'insurance', 'education', 'healthcare', 'subscription', 'cloud_storage'}
        
        # Group historical recurring expenses
        cat_events: Dict[str, List[FinancialEvent]] = {}
        for e in self.events:
            if e.direction == 'debit' and e.status == 'settled' and (e.category in monthly_cats or 'subscription' in e.category or e.flexibility in ['stoppable', 'reducible']):
                cat_events.setdefault(e.category, []).append(e)

        for cat, evs in cat_events.items():
            if cat in stopped_categories:
                continue
            latest_ev = max(evs, key=lambda x: x.settlement_date)
            base_amt = latest_ev.amount

            # Apply message rent increase
            if cat in ['rent', 'housing'] and self.msg.rent_increase_percent:
                base_amt *= (1.0 + self.msg.rent_increase_percent / 100.0)

            # Apply spending change for this event
            if latest_ev.event_id in stopped_events:
                continue
            if latest_ev.event_id in reduced_events:
                base_amt = reduced_events[latest_ev.event_id]

            dom = latest_ev.settlement_date.day
            curr_d = request_date
            while curr_d <= end_date:
                max_dom_in_month = (date(curr_d.year, curr_d.month % 12 + 1, 1) - timedelta(days=1)).day if curr_d.month < 12 else 31
                actual_dom = min(dom, max_dom_in_month)
                if curr_d.day == actual_dom and curr_d > latest_ev.settlement_date:
                    daily_expense[curr_d] = daily_expense.get(curr_d, 0.0) + base_amt
                curr_d += timedelta(days=1)

        # Run simulation
        balances: List[Tuple[date, float]] = []
        curr_bal = self.init_balance

        curr_d = request_date
        while curr_d <= end_date:
            inc = daily_income.get(curr_d, 0.0)
            exp = daily_expense.get(curr_d, 0.0)
            plan_pay = plan_by_date.get(curr_d, 0.0)

            curr_bal += inc - exp - plan_pay
            balances.append((curr_d, curr_bal))
            curr_d += timedelta(days=1)

        return balances

    def calculate_amount_safe_to_pay(self, request_date: date, requested_amount: float) -> float:
        """
        Calculates amount_safe_to_pay before optional spending changes.
        """
        balances = self.forecast_daily_balances(request_date, plan_payments=[], spending_changes=[])
        if not balances:
            return 0.0
        
        min_headroom = min(bal - self.min_balance for _, bal in balances)
        safe_amt = max(0.0, min(requested_amount, min_headroom))
        return round(safe_amt, 2)

    def calculate_earliest_date_for_full_payment(self, request_date: date, requested_amount: float, forecast_days: int = 90) -> str:
        """
        Finds earliest date in forecast window where full payment is safe without spending changes.
        """
        end_date = request_date + timedelta(days=forecast_days)
        curr_d = request_date
        while curr_d <= end_date:
            plan = [ScheduledPayment(payment_date=curr_d, amount=requested_amount)]
            balances = self.forecast_daily_balances(request_date, plan_payments=plan, spending_changes=[])
            if all(bal >= self.min_balance for _, bal in balances):
                return curr_d.strftime("%Y-%m-%d")
            curr_d += timedelta(days=1)

        return ""

    def is_plan_safe(self, request_date: date, plan_payments: List[ScheduledPayment], spending_changes: List[Dict[str, Any]] = None) -> bool:
        balances = self.forecast_daily_balances(request_date, plan_payments=plan_payments, spending_changes=spending_changes)
        return all(bal >= self.min_balance for _, bal in balances)
