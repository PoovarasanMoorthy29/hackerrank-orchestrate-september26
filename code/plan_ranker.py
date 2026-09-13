"""
Deterministic Plan Ranker implementing the challenge ranking rules without sentinel string bias.
"""

import re
from typing import List, Optional, Tuple, Any
from datetime import date
from code.models import CandidatePlan, PurchaseRequest

class PlanRanker:
    # Explicit Method Preference Policy:
    # When two candidates of DIFFERENT payment methods tie on rules 1-5 (completes on time,
    # spending changes, total paid, start date, payment count), ties are broken deterministically by method preference:
    # full_payment (0) > partial_payment (1) > installments (2) > wait (3) > not_recommended (4).
    #
    # DESIGN RATIONALE:
    # Upfront full payment completes the transaction immediately with zero future debt or administrative overhead.
    # Partial payment finishes next. Installments spread payments over time (matching seller options), while wait delays
    # full completion to a later date. This explicit hierarchy replaces incidental string/ASCII sorting of sentinel IDs.
    METHOD_PREFERENCE = {
        "full_payment": 0,
        "partial_payment": 1,
        "installments": 2,
        "wait": 3,
        "not_recommended": 4
    }

    @staticmethod
    def _parse_natural_key(s: Optional[str]) -> List[Any]:
        """
        Parses a payment_option_id string into a natural/numeric key list so multi-digit numbers
        sort numerically (e.g. 'opt_2' < 'opt_10', 'payment_option_02' < 'payment_option_10')
        rather than by naive ASCII lexicographical ordering.
        """
        if not s:
            return []
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

    @classmethod
    def select_best_plan(cls, candidates: List[CandidatePlan], req: PurchaseRequest) -> CandidatePlan:
        # Filter for safe plans
        safe_plans = [c for c in candidates if c.is_safe]

        if not safe_plans:
            # Fallback not_recommended plan
            return CandidatePlan(
                payment_method="not_recommended",
                payment_plan_str="none",
                payments=[],
                spending_changes_needed_str="none",
                spending_changes=[],
                earliest_date_for_full_payment="",
                affordability_status="not_affordable",
                total_payable_amount=0.0,
                is_safe=False,
                payment_option_id=None
            )

        def ranking_key(plan: CandidatePlan):
            # Rule 1: Complete by desired_completion_date (0 = yes, 1 = no)
            completion_date = max(p.payment_date for p in plan.payments) if plan.payments else req.request_date
            completes_on_time = 0 if completion_date <= req.desired_completion_date else 1

            # Rule 2: Require no spending changes (number of changes)
            num_changes = len(plan.spending_changes)

            # Rule 3: Minimize total amount paid
            tot_paid = plan.total_payable_amount

            # Rule 4: Start payment earlier (first payment date)
            first_date = min(p.payment_date for p in plan.payments) if plan.payments else req.request_date

            # Rule 5: Use fewer payments
            num_payments = len(plan.payments)

            # Explicit Method Preference (Tie-breaker across different payment methods)
            method_rank = cls.METHOD_PREFERENCE.get(plan.payment_method, 99)

            # Rule 6: Natural/numeric payment_option_id comparison (ONLY between multiple installment candidates)
            # Neutralized for non-installment methods (returns [] so non-installment methods never differ on this field)
            popt_key = cls._parse_natural_key(plan.payment_option_id) if plan.payment_method == "installments" else []

            return (completes_on_time, num_changes, tot_paid, first_date, num_payments, method_rank, popt_key)

        safe_plans.sort(key=ranking_key)
        return safe_plans[0]
