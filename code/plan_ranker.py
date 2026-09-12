"""
Deterministic Plan Ranker implementing the 6 challenge ranking rules.
"""

from typing import List, Optional
from datetime import date
from code.models import CandidatePlan, PurchaseRequest

class PlanRanker:
    @staticmethod
    def select_best_plan(candidates: List[CandidatePlan], req: PurchaseRequest) -> CandidatePlan:
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
                payment_option_id="999"
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

            # Rule 6: Lowest payment_option_id tie-breaker
            popt_id = plan.payment_option_id

            return (completes_on_time, num_changes, tot_paid, first_date, num_payments, popt_id)

        safe_plans.sort(key=ranking_key)
        return safe_plans[0]
