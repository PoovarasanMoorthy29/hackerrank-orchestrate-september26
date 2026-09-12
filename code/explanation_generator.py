"""
Grounded Decision Explanation Builder for Financial Agent Recommendations.
"""

from typing import Optional
from datetime import datetime
from code.models import PurchaseRequest, FinancialProfile, CandidatePlan

class ExplanationGenerator:
    @staticmethod
    def format_amount(amount: float) -> str:
        if amount % 1 == 0:
            return f"{int(amount):,}"
        return f"{amount:,.2f}"

    @classmethod
    def generate_explanation(cls,
                             req: PurchaseRequest,
                             profile: FinancialProfile,
                             best_plan: CandidatePlan,
                             amount_safe_to_pay: float) -> str:

        curr = profile.home_currency
        min_bal_str = cls.format_amount(profile.minimum_balance_to_keep)
        req_amt_str = cls.format_amount(req.requested_amount)

        method = best_plan.payment_method
        status = best_plan.affordability_status

        # 1. Full Payment (affordable_now)
        if method == "full_payment" and status == "affordable_now":
            if best_plan.spending_changes_needed_str == "none":
                return f"Pay {curr} {req_amt_str} today. This leaves at least {curr} {min_bal_str} available over the next 90 days."
            else:
                changes_text = best_plan.spending_changes_needed_str
                return f"With spending adjustments ({changes_text}), pay {curr} {req_amt_str} today. This keeps the {curr} {min_bal_str} minimum protected."

        # 2. Partial Payment
        if method == "partial_payment":
            safe_str = cls.format_amount(amount_safe_to_pay)
            rem_amt = req.requested_amount - amount_safe_to_pay
            rem_str = cls.format_amount(rem_amt)
            earliest_dt = datetime.strptime(best_plan.earliest_date_for_full_payment, "%Y-%m-%d").strftime("%d %B %Y").lstrip('0')
            return f"Pay {curr} {safe_str} today and the remaining {curr} {rem_str} on {earliest_dt}. This completes the full request and keeps the {curr} {min_bal_str} minimum protected."

        # 3. Installments
        if method == "installments":
            num_p = len(best_plan.payments)
            inst_amt = best_plan.payments[0].amount if best_plan.payments else 0.0
            inst_amt_str = cls.format_amount(inst_amt)
            first_dt = best_plan.payments[0].payment_date.strftime("%d %B %Y").lstrip('0') if best_plan.payments else ""
            return f"Use {num_p} installments of {curr} {inst_amt_str}, starting {first_dt}. This leaves at least {curr} {min_bal_str} available."

        # 4. Wait
        if method == "wait":
            earliest_dt = datetime.strptime(best_plan.earliest_date_for_full_payment, "%Y-%m-%d").strftime("%d %B %Y").lstrip('0')
            return f"Pay {curr} {req_amt_str} in full on {earliest_dt}. Paying earlier would take the balance below the {curr} {min_bal_str} minimum."

        # 5. Not Recommended
        if method == "not_recommended" or status == "not_affordable":
            desired_dt = req.desired_completion_date.strftime("%d %B %Y").lstrip('0')
            if amount_safe_to_pay > 0:
                safe_str = cls.format_amount(amount_safe_to_pay)
                return f"Do not proceed with the {curr} {req_amt_str} request. Although {curr} {safe_str} is available today, the full amount cannot be completed safely within 90 days."
            else:
                return f"Do not make this payment by {desired_dt}. None of the available options keeps the {curr} {min_bal_str} minimum protected."

        return f"Payment of {curr} {req_amt_str} evaluated against {curr} {min_bal_str} minimum balance requirement."
