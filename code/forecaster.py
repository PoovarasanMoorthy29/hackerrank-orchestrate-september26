"""
90-Day Cash-Flow Forecaster and Safety Checker.
Simulates daily cash flow over 90 days from request_date, checking minimum balance safety.
"""

from datetime import date, timedelta
from typing import Dict, List, Tuple, Optional, Set, Any
from code.models import FinancialProfile, FinancialEvent, ScheduledPayment
from code.message_parser import UserMessageUpdates

class CashFlowForecaster:
    def __init__(self,
                 profile: FinancialProfile,
                 events: List[FinancialEvent],
                 message_updates: UserMessageUpdates,
                 unresolved_event_ids: Optional[List[str]] = None):
        self.profile = profile
        self.events = events
        self.msg = message_updates
        self.home_currency = profile.home_currency
        self.min_balance = profile.minimum_balance_to_keep
        self.init_balance = profile.current_available_balance
        self.unresolved_event_ids = set(unresolved_event_ids or [])

        # Tracking for estimation vs explicit exclusion decisions
        self.estimated_unresolved_events: Dict[str, float] = {}  # event_id -> estimated_amount
        self.excluded_unresolved_events: List[str] = []         # event_ids with no estimate possible
        self.has_uncertain_unresolved_expense: bool = False     # True if any essential debit was excluded without an estimate

    def _is_essential_or_protected_event(self, e: FinancialEvent) -> bool:
        """
        Determines whether a debit event is essential or protected based on:
        1. Explicit protection in profile.expense_categories_to_protect
        2. Category / description / event_type keywords matching essential/committed obligations
           (rent, housing, utility, bill, loan, debt, tuition, fee, childcare, insurance, tax, deduction, mortgage, credit_card, grocery).
        """
        if e.category in self.profile.expense_categories_to_protect:
            return True
        
        essential_keywords = {
            'rent', 'housing', 'utility', 'utilities', 'bill', 'loan', 'debt',
            'tuition', 'fee', 'childcare', 'insurance', 'tax', 'deduction',
            'mortgage', 'credit_card', 'grocery', 'groceries'
        }
        text_content = (e.category + ' ' + e.description + ' ' + e.event_type).lower()
        return any(kw in text_content for kw in essential_keywords)

    def _get_conservative_estimate_for_event(self, e: FinancialEvent) -> Optional[float]:
        """
        FINANCIALLY SAFER INTERPRETATION ESTIMATION RULE:
        When a debit event has an unresolved amount (amount is None), treating it as $0.0 would understate
        future required spending, overstate available headroom, and risk taking the user's balance below
        minimum_balance_to_keep.
        
        To uphold the problem statement's 'financially safer interpretation' rule, we estimate unresolved
        essential debits conservatively (erring toward assuming MORE required spending, not less):
        
        Order of Preference:
        (a) minimum_allowed_amount if present and > 0.
        (b) Outlier-Robust Conservative Statistic (75th Percentile with 1.15x Median Floor):
            Rather than using raw max(same_cat_amounts) — which is vulnerable to single extreme historical outliers
            (e.g., a one-off annual insurance charge miscategorized as a utility) permanently inflating future estimates —
            we calculate the 75th percentile of settled historical debits for that category, with a lower bound of
            1.15x the median to ensure the estimate remains conservatively above typical spending without being dominated
            by worst-case outliers.
        (c) None if no history or minimum exists (triggers explicit logged exclusion & uncertainty flag).
        """
        # Option (a): minimum_allowed_amount if present
        if e.minimum_allowed_amount is not None and e.minimum_allowed_amount > 0:
            return e.minimum_allowed_amount

        # Option (b): Robust conservative estimate from historical category debits
        same_cat_amounts = [
            ev.amount for ev in self.events
            if ev.category == e.category and ev.direction == 'debit' and ev.status == 'settled' and ev.amount is not None and ev.amount > 0
        ]
        if same_cat_amounts:
            if len(same_cat_amounts) == 1:
                return same_cat_amounts[0]

            sorted_amts = sorted(same_cat_amounts)
            import statistics
            med = statistics.median(sorted_amts)

            # 75th percentile rank with linear interpolation
            n = len(sorted_amts)
            k = (n - 1) * 0.75
            idx_f = int(k)
            idx_c = idx_f + 1
            if idx_c >= n:
                p75 = sorted_amts[-1]
            else:
                p75 = sorted_amts[idx_f] + (k - idx_f) * (sorted_amts[idx_c] - sorted_amts[idx_f])

            # Ensure estimate is conservatively above median (1.15x floor), but bounded by p75 / max
            conservative_est = max(p75, 1.15 * med)
            return min(conservative_est, sorted_amts[-1])

        return None

    def forecast_daily_balances(self,
                                request_date: date,
                                plan_payments: List[ScheduledPayment] = None,
                                spending_changes: List[Dict[str, Any]] = None,
                                forecast_days: int = 90) -> List[Tuple[date, float]]:

        if plan_payments is None:
            plan_payments = []
        if spending_changes is None:
            spending_changes = []

        # Reset per-simulation tracking
        self.estimated_unresolved_events.clear()
        self.excluded_unresolved_events.clear()
        self.has_uncertain_unresolved_expense = False

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

        daily_income: Dict[date, float] = {}
        daily_expense: Dict[date, float] = {}

        end_date = request_date + timedelta(days=forecast_days)

        # 1. Process Pending/Scheduled Debits
        explicit_debit_months: Set[Tuple[str, int, int]] = set()  # Track (category, year, month) of explicit debits

        for e in self.events:
            if e.direction == 'debit' and e.status in ['pending', 'scheduled']:
                pay_date = e.settlement_date if e.settlement_date >= request_date else request_date
                if pay_date <= end_date:
                    if e.event_id in stopped_events or e.category in stopped_categories:
                        continue

                    # Record explicit pending/scheduled debit for (category, year, month)
                    explicit_debit_months.add((e.category, pay_date.year, pay_date.month))

                    amt = reduced_events.get(e.event_id, e.amount)
                    if amt is None:
                        # Event has unresolved amount (amount is None)
                        if self._is_essential_or_protected_event(e):
                            est = self._get_conservative_estimate_for_event(e)
                            if est is not None:
                                amt = est
                                self.estimated_unresolved_events[e.event_id] = est
                            else:
                                # DELIBERATE EXPLICIT EXCLUSION PATH
                                # Essential/protected debit with no historical basis or minimum allowed amount.
                                # Cannot safely estimate, so exclude from math but flag forecast as uncertain.
                                self.excluded_unresolved_events.append(e.event_id)
                                self.has_uncertain_unresolved_expense = True
                                continue
                        else:
                            # DELIBERATE EXPLICIT EXCLUSION PATH (Non-essential / unprotected event)
                            self.excluded_unresolved_events.append(e.event_id)
                            continue

                    daily_expense[pay_date] = daily_expense.get(pay_date, 0.0) + amt

        # 2. Process Confirmed Recurring Salary Income
        # NOTE ON SALARY INCOME DEDUPLICATION:
        # Pending credit events are not counted prior to settlement date per rule §6.3.
        # Salary projections use settled historical salary records and project paydays starting
        # strictly after latest_sal.settlement_date (curr_d > latest_sal.settlement_date).
        # Thus, salary income is free from double-counting risk between pending records and synthetic projections.
        salary_events = [e for e in self.events if e.event_type == 'income' and 'salary' in (e.category + ' ' + e.description).lower() and e.status == 'settled' and e.amount is not None]
        if salary_events and not self.msg.seasonal_contract_ended:
            latest_sal = max(salary_events, key=lambda x: x.settlement_date)
            sal_amt = self.msg.salary_amount_override if self.msg.salary_amount_override is not None else latest_sal.amount
            
            payday_dom = self.msg.salary_date_override.day if self.msg.salary_date_override else latest_sal.settlement_date.day

            curr_d = request_date
            while curr_d <= end_date:
                max_dom_in_month = (date(curr_d.year, curr_d.month % 12 + 1, 1) - timedelta(days=1)).day if curr_d.month < 12 else 31
                actual_payday = min(payday_dom, max_dom_in_month)
                if curr_d.day == actual_payday and curr_d > latest_sal.settlement_date:
                    daily_income[curr_d] = daily_income.get(curr_d, 0.0) + sal_amt
                curr_d += timedelta(days=1)

        # 3. Process Approved One-Time Invoice Income from messages
        if self.msg.invoice_approved_amount and self.msg.invoice_settlement_date:
            inv_date = self.msg.invoice_settlement_date
            if request_date <= inv_date <= end_date:
                daily_income[inv_date] = daily_income.get(inv_date, 0.0) + self.msg.invoice_approved_amount

        # 4. Dynamically Identify Recurring Expenses from transaction history
        # Group historical debit events by category
        cat_debit_events: Dict[str, List[FinancialEvent]] = {}
        for e in self.events:
            if e.direction == 'debit' and e.status == 'settled' and e.amount is not None:
                cat_debit_events.setdefault(e.category, []).append(e)

        for cat, evs in cat_debit_events.items():
            valid_evs = [e for e in evs if e.amount is not None]
            if not valid_evs:
                continue

            # An expense category is recurring if multiple settled entries exist or if marked flexible/protected
            is_recurring = len(valid_evs) > 1 or any(e.flexibility in ['stoppable', 'reducible', 'reducible_or_stoppable'] for e in valid_evs) or cat in self.profile.expense_categories_to_protect
            
            if not is_recurring:
                continue

            if cat in stopped_categories:
                continue

            latest_ev = max(valid_evs, key=lambda x: x.settlement_date)
            base_amt = latest_ev.amount

            # Apply message rent/housing percentage increase if applicable
            if ('rent' in cat or 'housing' in cat) and self.msg.rent_increase_percent:
                base_amt *= (1.0 + self.msg.rent_increase_percent / 100.0)

            # Apply spending change overrides
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
                    # RECURRING EXPENSE DEDUPLICATION FIX:
                    # Do not synthesize a recurring expense for a calendar month/category that ALREADY has
                    # an explicit pending or scheduled debit event processed in Section 1. This prevents
                    # double-counting explicit upcoming bills (including near-miss dates due to weekends/holidays).
                    if (cat, curr_d.year, curr_d.month) in explicit_debit_months:
                        curr_d += timedelta(days=1)
                        continue

                    daily_expense[curr_d] = daily_expense.get(curr_d, 0.0) + base_amt
                curr_d += timedelta(days=1)

        # 5. Run daily simulation
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
        Calculates amount_safe_to_pay BEFORE optional spending changes.

        DESIGN DECISION ON UNRESOLVED AMOUNT SAFETY MARGIN:
        When a user has unresolved financial event amounts (amount is None), we do NOT apply an arbitrary ad-hoc
        percentage reduction to amount_safe_to_pay. Instead, we directly inject conservative non-zero estimates for all
        essential/protected unresolved debits into forecast_daily_balances() (using the maximum historical settled amount
        or minimum allowed amount). Because these estimates already err toward assuming higher required spending (following
        the spec's 'financially safer interpretation' tie-break rule), the 90-day daily balance simulation naturally
        and deterministically restricts amount_safe_to_pay to protect minimum_balance_to_keep without introducing
        un-grounded safety margins.
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
