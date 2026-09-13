"""
Payment Option Loader and Candidate Plan Generator with Spending Changes Support.
"""

import csv
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from code.models import PurchaseRequest, FinancialProfile, PaymentOption, CandidatePlan, ScheduledPayment, FinancialEvent
from code.forecaster import CashFlowForecaster

class PlanGenerator:
    def __init__(self, options_csv_path: str = "dataset/request_payment_options.csv"):
        self.options: Dict[str, List[PaymentOption]] = {}
        self._load_options(options_csv_path)

    def _load_options(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rid = row['request_id'].strip()
                    popt_id = row['payment_option_id'].strip()
                    pmethod = row['payment_method'].strip().lower()
                    pamt = float(row['payment_amount'])
                    num_p = int(row['number_of_payments'])
                    fdate = datetime.strptime(row['first_payment_date'].strip(), "%Y-%m-%d").date()

                    freq_str = row['payment_frequency_days'].strip()
                    freq = int(freq_str) if freq_str and freq_str.isdigit() else 30

                    fee_str = row['financing_fee'].strip()
                    fee = float(fee_str) if fee_str else 0.0

                    tot_str = row['total_payable_amount'].strip()
                    tot = float(tot_str) if tot_str else (pamt * num_p)

                    opt = PaymentOption(
                        payment_option_id=popt_id,
                        request_id=rid,
                        payment_method=pmethod,
                        payment_amount=pamt,
                        number_of_payments=num_p,
                        first_payment_date=fdate,
                        payment_frequency_days=freq,
                        financing_fee=fee,
                        total_payable_amount=tot
                    )

                    if rid not in self.options:
                        self.options[rid] = []
                    self.options[rid].append(opt)
        except FileNotFoundError:
            pass

    def get_options_for_request(self, request_id: str) -> List[PaymentOption]:
        return self.options.get(request_id, [])

    def _find_spending_change_combos(self, profile: FinancialProfile, events: List[FinancialEvent]) -> List[Tuple[str, List[Dict[str, Any]]]]:
        """
        Generates candidate spending change combinations (up to 3 changes).
        Returns list of (spending_changes_str, spending_changes_list).
        """
        protected_cats = set(profile.expense_categories_to_protect)
        willing_stop_cats = set(profile.expense_categories_user_is_willing_to_stop)
        willing_reduce_cats = set(profile.expense_categories_user_is_willing_to_reduce)

        stoppable_candidates: List[FinancialEvent] = []
        reducible_candidates: List[FinancialEvent] = []

        # Find latest flexible events
        latest_events: Dict[Tuple[str, str], FinancialEvent] = {}
        for e in events:
            if e.direction == 'debit' and e.category not in protected_cats:
                key = (e.category, e.description)
                if key not in latest_events or e.settlement_date > latest_events[key].settlement_date:
                    latest_events[key] = e

        for e in latest_events.values():
            cat = e.category
            flex = e.flexibility.lower()

            if flex == 'stoppable' or cat in willing_stop_cats:
                stoppable_candidates.append(e)

            if flex in ['reducible', 'reducible_or_stoppable'] or cat in willing_reduce_cats:
                if e.minimum_allowed_amount is not None and e.minimum_allowed_amount < e.amount:
                    reducible_candidates.append(e)

        combos: List[Tuple[str, List[Dict[str, Any]]]] = []
        combos.append(("none", []))

        # Single stop candidates
        for se in stoppable_candidates:
            sc = [{'type': 'stop', 'event_id': se.event_id, 'category': se.category}]
            sc_str = f"stop:{se.event_id}"
            combos.append((sc_str, sc))

        # Single reduce candidates
        for re in reducible_candidates:
            new_amt_str = f"{re.minimum_allowed_amount:.2f}".rstrip('0').rstrip('.') if re.minimum_allowed_amount % 1 != 0 else f"{int(re.minimum_allowed_amount)}"
            sc = [{'type': 'reduce_to', 'event_id': re.event_id, 'category': re.category, 'new_amount': re.minimum_allowed_amount}]
            sc_str = f"reduce_to:{re.event_id}:{new_amt_str}"
            combos.append((sc_str, sc))

        # Double candidates (stop + reduce)
        for se in stoppable_candidates:
            for re in reducible_candidates:
                if se.event_id != re.event_id:
                    new_amt_str = f"{re.minimum_allowed_amount:.2f}".rstrip('0').rstrip('.') if re.minimum_allowed_amount % 1 != 0 else f"{int(re.minimum_allowed_amount)}"
                    sc = [
                        {'type': 'stop', 'event_id': se.event_id, 'category': se.category},
                        {'type': 'reduce_to', 'event_id': re.event_id, 'category': re.category, 'new_amount': re.minimum_allowed_amount}
                    ]
                    sc_str = f"stop:{se.event_id}|reduce_to:{re.event_id}:{new_amt_str}"
                    combos.append((sc_str, sc))

        return combos

    def generate_candidate_plans(self,
                                 req: PurchaseRequest,
                                 profile: FinancialProfile,
                                 forecaster: CashFlowForecaster,
                                 amount_safe_to_pay: float,
                                 earliest_full_date_str: str) -> List[CandidatePlan]:

        candidates: List[CandidatePlan] = []
        user_methods = set(profile.payment_methods_user_will_consider)

        spending_combos = self._find_spending_change_combos(profile, forecaster.events)

        # 1. Full Payment on request_date
        if 'full_payment' in user_methods:
            amt_str = f"{req.requested_amount:.2f}".rstrip('0').rstrip('.') if req.requested_amount % 1 != 0 else f"{int(req.requested_amount)}"
            plan_str = f"{req.request_date.strftime('%Y-%m-%d')}:{amt_str}"
            payments = [ScheduledPayment(payment_date=req.request_date, amount=req.requested_amount)]

            for sc_str, sc_list in spending_combos:
                is_safe = forecaster.is_plan_safe(req.request_date, plan_payments=payments, spending_changes=sc_list)
                if is_safe:
                    aff_status = "affordable_now" if sc_str == "none" else "affordable_with_plan"
                    candidates.append(CandidatePlan(
                        payment_method="full_payment",
                        payment_plan_str=plan_str,
                        payments=payments,
                        spending_changes_needed_str=sc_str,
                        spending_changes=sc_list,
                        earliest_date_for_full_payment=earliest_full_date_str if earliest_full_date_str else req.request_date.strftime('%Y-%m-%d'),
                        affordability_status=aff_status,
                        total_payable_amount=req.requested_amount,
                        is_safe=True,
                        payment_option_id="000"
                    ))
                    if sc_str == "none":
                        break

            if not candidates:
                candidates.append(CandidatePlan(
                    payment_method="full_payment",
                    payment_plan_str=plan_str,
                    payments=payments,
                    spending_changes_needed_str="none",
                    spending_changes=[],
                    earliest_date_for_full_payment=earliest_full_date_str if earliest_full_date_str else req.request_date.strftime('%Y-%m-%d'),
                    affordability_status="not_affordable",
                    total_payable_amount=req.requested_amount,
                    is_safe=False,
                    payment_option_id="000"
                ))

        # 2. Partial Payment
        if req.allows_partial_payment and ('partial_payment' in user_methods or 'full_payment' in user_methods):
            if 0 < amount_safe_to_pay < req.requested_amount and earliest_full_date_str:
                earliest_date = datetime.strptime(earliest_full_date_str, "%Y-%m-%d").date()
                if earliest_date <= req.desired_completion_date:
                    rem_amt = req.requested_amount - amount_safe_to_pay
                    amt1_str = f"{amount_safe_to_pay:.2f}".rstrip('0').rstrip('.') if amount_safe_to_pay % 1 != 0 else f"{int(amount_safe_to_pay)}"
                    amt2_str = f"{rem_amt:.2f}".rstrip('0').rstrip('.') if rem_amt % 1 != 0 else f"{int(rem_amt)}"

                    plan_str = f"{req.request_date.strftime('%Y-%m-%d')}:{amt1_str}|{earliest_full_date_str}:{amt2_str}"
                    payments = [
                        ScheduledPayment(payment_date=req.request_date, amount=amount_safe_to_pay),
                        ScheduledPayment(payment_date=earliest_date, amount=rem_amt)
                    ]
                    is_safe = forecaster.is_plan_safe(req.request_date, plan_payments=payments)
                    candidates.append(CandidatePlan(
                        payment_method="partial_payment",
                        payment_plan_str=plan_str,
                        payments=payments,
                        spending_changes_needed_str="none",
                        spending_changes=[],
                        earliest_date_for_full_payment=earliest_full_date_str,
                        affordability_status="affordable_with_plan",
                        total_payable_amount=req.requested_amount,
                        is_safe=is_safe,
                        payment_option_id="001"
                    ))

        # 3. Installments from request_payment_options.csv
        if 'installments' in user_methods:
            options = self.get_options_for_request(req.request_id)
            for opt in options:
                if opt.payment_method == 'installments':
                    if profile.max_installment_months and opt.number_of_payments > profile.max_installment_months:
                        continue

                    payments: List[ScheduledPayment] = []
                    plan_parts: List[str] = []
                    curr_d = opt.first_payment_date
                    for i in range(opt.number_of_payments):
                        pdate = curr_d + timedelta(days=i * opt.payment_frequency_days)
                        pamt = opt.payment_amount
                        payments.append(ScheduledPayment(payment_date=pdate, amount=pamt))

                        amt_str = f"{pamt:.2f}".rstrip('0').rstrip('.') if pamt % 1 != 0 else f"{int(pamt)}"
                        plan_parts.append(f"{pdate.strftime('%Y-%m-%d')}:{amt_str}")

                    plan_str = "|".join(plan_parts)

                    for sc_str, sc_list in spending_combos:
                        is_safe = forecaster.is_plan_safe(req.request_date, plan_payments=payments, spending_changes=sc_list)
                        if is_safe:
                            candidates.append(CandidatePlan(
                                payment_method="installments",
                                payment_plan_str=plan_str,
                                payments=payments,
                                spending_changes_needed_str=sc_str,
                                spending_changes=sc_list,
                                earliest_date_for_full_payment=earliest_full_date_str,
                                affordability_status="affordable_with_plan",
                                total_payable_amount=opt.total_payable_amount,
                                is_safe=True,
                                payment_option_id=opt.payment_option_id
                            ))
                            if sc_str == "none":
                                break

        # 4. Wait
        if 'full_payment' in user_methods and earliest_full_date_str:
            earliest_date = datetime.strptime(earliest_full_date_str, "%Y-%m-%d").date()
            if earliest_date > req.request_date and earliest_date <= req.desired_completion_date:
                amt_str = f"{req.requested_amount:.2f}".rstrip('0').rstrip('.') if req.requested_amount % 1 != 0 else f"{int(req.requested_amount)}"
                plan_str = f"{earliest_full_date_str}:{amt_str}"
                payments = [ScheduledPayment(payment_date=earliest_date, amount=req.requested_amount)]
                is_safe = forecaster.is_plan_safe(req.request_date, plan_payments=payments)
                candidates.append(CandidatePlan(
                    payment_method="wait",
                    payment_plan_str=plan_str,
                    payments=payments,
                    spending_changes_needed_str="none",
                    spending_changes=[],
                    earliest_date_for_full_payment=earliest_full_date_str,
                    affordability_status="affordable_later",
                    total_payable_amount=req.requested_amount,
                    is_safe=is_safe,
                    payment_option_id="002"
                ))

        return candidates
