"""
Buy or Wait? AI Financial Agent Pipeline.
Entry point for evaluating dataset/requests.csv and generating output.csv.
"""

import csv
import sys
import os
from datetime import datetime, date
from typing import Dict, List, Any

from code.models import PurchaseRequest, Recommendation
from code.event_reconstructor import EventReconstructor
from code.forecaster import CashFlowForecaster
from code.plan_generator import PlanGenerator
from code.plan_ranker import PlanRanker
from code.explanation_generator import ExplanationGenerator

def process_requests(requests_csv_path: str = "dataset/requests.csv",
                     output_csv_path: str = "output.csv",
                     profiles_csv: str = "dataset/financial_profiles.csv",
                     events_csv: str = "dataset/financial_events.csv",
                     exchange_rates_csv: str = "dataset/exchange_rates.csv",
                     options_csv: str = "dataset/request_payment_options.csv",
                     messages_csv: str = "dataset/messages.csv",
                     images_csv: str = "dataset/images.csv",
                     media_dir: str = "dataset/media/images") -> List[Recommendation]:

    recon = EventReconstructor(
        events_csv_path=events_csv,
        profiles_csv_path=profiles_csv,
        exchange_rates_csv_path=exchange_rates_csv,
        images_csv_path=images_csv,
        messages_csv_path=messages_csv
    )
    plan_gen = PlanGenerator(options_csv_path=options_csv)

    # Load requests
    requests: List[PurchaseRequest] = []
    with open(requests_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid = row['request_id'].strip()
            uid = row['user_id'].strip()
            rdate = datetime.strptime(row['request_date'].strip(), "%Y-%m-%d").date()
            rtype = row['request_type'].strip()
            ramt = float(row['requested_amount'])
            cdate = datetime.strptime(row['desired_completion_date'].strip(), "%Y-%m-%d").date()
            partial = row['allows_partial_payment'].strip().lower() == 'true'
            rtext = row['request_text'].strip()

            requests.append(PurchaseRequest(
                request_id=rid,
                user_id=uid,
                request_date=rdate,
                request_type=rtype,
                requested_amount=ramt,
                desired_completion_date=cdate,
                allows_partial_payment=partial,
                request_text=rtext
            ))

    recommendations: List[Recommendation] = []

    for req in requests:
        profile = recon.get_profile(req.user_id)
        events = recon.get_user_events(req.user_id)
        msg_updates = recon.get_message_updates(req.user_id)

        if not profile:
            continue

        unresolved_eids = recon.get_unresolved_event_ids_for_user(req.user_id)
        forecaster = CashFlowForecaster(profile, events, msg_updates, unresolved_event_ids=unresolved_eids)

        # 1. Calculate amount_safe_to_pay
        amount_safe_to_pay = forecaster.calculate_amount_safe_to_pay(req.request_date, req.requested_amount)

        # 2. Calculate earliest_date_for_full_payment
        earliest_full_date_str = forecaster.calculate_earliest_date_for_full_payment(req.request_date, req.requested_amount)

        # 3. Generate candidate payment plans
        candidates = plan_gen.generate_candidate_plans(
            req=req,
            profile=profile,
            forecaster=forecaster,
            amount_safe_to_pay=amount_safe_to_pay,
            earliest_full_date_str=earliest_full_date_str
        )

        # 4. Rank candidate plans and pick best safe plan
        best_plan = PlanRanker.select_best_plan(candidates, req)

        # 5. Format amount_safe_to_pay string / number
        safe_pay_val = amount_safe_to_pay
        if safe_pay_val % 1 == 0:
            safe_pay_out = str(int(safe_pay_val))
        else:
            safe_pay_out = f"{safe_pay_val:.2f}".rstrip('0').rstrip('.')

        # 6. Generate decision explanation
        has_unresolved = bool(unresolved_eids or forecaster.estimated_unresolved_events or forecaster.has_uncertain_unresolved_expense)
        explanation = ExplanationGenerator.generate_explanation(req, profile, best_plan, amount_safe_to_pay, has_unresolved_amounts=has_unresolved)

        rec = Recommendation(
            request_id=req.request_id,
            amount_safe_to_pay=safe_pay_out,
            affordability_status=best_plan.affordability_status,
            recommended_payment_method=best_plan.payment_method,
            payment_plan=best_plan.payment_plan_str,
            earliest_date_for_full_payment=best_plan.earliest_date_for_full_payment if best_plan.payment_method != "not_recommended" and best_plan.affordability_status != "not_affordable" else (earliest_full_date_str if best_plan.affordability_status == "affordable_later" else ""),
            spending_changes_needed=best_plan.spending_changes_needed_str,
            decision_explanation=explanation
        )

        recommendations.append(rec)

    # Write output.csv
    fieldnames = [
        'request_id',
        'amount_safe_to_pay',
        'affordability_status',
        'recommended_payment_method',
        'payment_plan',
        'earliest_date_for_full_payment',
        'spending_changes_needed',
        'decision_explanation'
    ]

    with open(output_csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in recommendations:
            writer.writerow({
                'request_id': r.request_id,
                'amount_safe_to_pay': r.amount_safe_to_pay,
                'affordability_status': r.affordability_status,
                'recommended_payment_method': r.recommended_payment_method,
                'payment_plan': r.payment_plan,
                'earliest_date_for_full_payment': r.earliest_date_for_full_payment,
                'spending_changes_needed': r.spending_changes_needed,
                'decision_explanation': r.decision_explanation
            })

    print(f"Successfully processed {len(recommendations)} requests into {output_csv_path}")
    return recommendations

if __name__ == "__main__":
    req_file = sys.argv[1] if len(sys.argv) > 1 else "dataset/requests.csv"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "output.csv"
    process_requests(req_file, out_file)
