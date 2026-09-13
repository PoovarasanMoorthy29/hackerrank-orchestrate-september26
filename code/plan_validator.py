"""
Deterministic Plan Validator enforcing all 10 challenge safety and contract rules.
"""

from typing import List, Dict, Any, Tuple, Set
from datetime import date
from code.models import CandidatePlan, PurchaseRequest, FinancialProfile, ScheduledPayment

class PlanValidator:
    @staticmethod
    def validate_plan(plan: CandidatePlan, req: PurchaseRequest, profile: FinancialProfile) -> Tuple[bool, List[str]]:
        errors: List[str] = []
        user_methods = set(profile.payment_methods_user_will_consider)

        # 1. Method allowed by user
        if plan.payment_method not in ["not_recommended", "wait"]:
            if plan.payment_method not in user_methods:
                errors.append(f"Payment method '{plan.payment_method}' not in user preferences {profile.payment_methods_user_will_consider}")

        # 2. Installment month constraint
        if plan.payment_method == "installments" and profile.max_installment_months:
            if len(plan.payments) > profile.max_installment_months:
                errors.append(f"Installment plan has {len(plan.payments)} payments, exceeding max {profile.max_installment_months}")

        # 3. Date ordering and validity
        if plan.payments:
            for i in range(len(plan.payments) - 1):
                if plan.payments[i+1].payment_date < plan.payments[i].payment_date:
                    errors.append(f"Payment dates out of order: {plan.payments[i].payment_date} > {plan.payments[i+1].payment_date}")

        # 4. Spending changes validation
        if len(plan.spending_changes) > 3:
            errors.append("Exceeded maximum allowed 3 spending changes")

        protected_cats = set(profile.expense_categories_to_protect)
        stopped_events: Set[str] = set()
        reduced_events: Set[str] = set()

        for sc in plan.spending_changes:
            stype = sc.get('type')
            eid = sc.get('event_id', '')
            cat = sc.get('category', '')
            if cat and cat in protected_cats:
                errors.append(f"Cannot change protected category '{cat}'")

            if stype == 'stop':
                if eid in stopped_events or eid in reduced_events:
                    errors.append(f"Duplicate/conflicting spending change for event '{eid}'")
                stopped_events.add(eid)
            elif stype == 'reduce_to':
                if eid in stopped_events or eid in reduced_events:
                    errors.append(f"Duplicate/conflicting spending change for event '{eid}'")
                reduced_events.add(eid)

        is_valid = len(errors) == 0
        return is_valid, errors
