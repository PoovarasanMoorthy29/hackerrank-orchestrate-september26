"""
Comprehensive Unit and Integration Test Suite for Buy or Wait? Financial Engine.
Covering State, Lifecycle, Dates, Plans, Images, Messages, Currency, and Edge Cases.
"""

import unittest
from datetime import date
from code.models import FinancialProfile, FinancialEvent, PurchaseRequest, PaymentOption, CandidatePlan, ScheduledPayment
from code.currency import CurrencyConverter
from code.image_extractor import ImageExtractor
from code.message_parser import MessageParser
from code.event_reconstructor import EventReconstructor
from code.forecaster import CashFlowForecaster
from code.plan_generator import PlanGenerator
from code.plan_ranker import PlanRanker
from code.plan_validator import PlanValidator
from code.explanation_generator import ExplanationGenerator

class TestFinancialEngineComprehensive(unittest.TestCase):

    def setUp(self):
        self.profile = FinancialProfile(
            user_id="user_test",
            home_currency="USD",
            current_available_balance=5000.0,
            minimum_balance_to_keep=1000.0,
            financial_priorities=["housing", "utilities"],
            expense_categories_to_protect=["rent", "utilities"],
            expense_categories_user_is_willing_to_reduce=["dining"],
            expense_categories_user_is_willing_to_stop=["cloud_storage"],
            payment_methods_user_will_consider=["full_payment", "installments", "partial_payment"],
            max_installment_months=6
        )

        self.events = [
            FinancialEvent(
                event_id="event_sal",
                user_id="user_test",
                event_type="income",
                description="Salary",
                category="salary",
                direction="credit",
                amount=3000.0,
                currency="USD",
                event_date=date(2026, 1, 15),
                settlement_date=date(2026, 1, 15),
                status="settled"
            ),
            FinancialEvent(
                event_id="event_rent",
                user_id="user_test",
                event_type="expense",
                description="Rent",
                category="rent",
                direction="debit",
                amount=1200.0,
                currency="USD",
                event_date=date(2026, 1, 1),
                settlement_date=date(2026, 1, 1),
                status="settled"
            )
        ]

    # 1. Currency Tests
    def test_currency_converter_same_currency(self):
        converter = CurrencyConverter()
        self.assertEqual(converter.convert(100.0, "USD", "USD", date(2026, 1, 1)), 100.0)

    def test_currency_converter_foreign(self):
        converter = CurrencyConverter()
        converted = converter.convert(100.0, "EUR", "ZAR", date(2023, 10, 15))
        self.assertGreater(converted, 0.0)

    # 2. Image Extraction Tests
    def test_image_extractor_mapping(self):
        extractor = ImageExtractor()
        # Verifies that mapping loads correctly without hardcoded values
        self.assertIsNotNone(extractor.event_to_image)

    def test_image_extractor_unknown_defaults_to_none(self):
        extractor = ImageExtractor()
        amt = extractor.get_amount_for_event("non_existent_event")
        self.assertIsNone(amt)

    # 3. Message Parser Tests
    def test_message_parser_loads_user(self):
        parser = MessageParser()
        up = parser.get_updates_for_user("user_02")
        self.assertIsNotNone(up)

    def test_message_parser_seasonal_contract(self):
        parser = MessageParser()
        up = parser.get_updates_for_user("user_12")
        self.assertTrue(up.seasonal_contract_ended)

    # 4. Event Reconstruction & Lifecycle Tests
    def test_event_reconstructor_loads_user(self):
        recon = EventReconstructor()
        p = recon.get_profile("user_01")
        self.assertIsNotNone(p)
        self.assertEqual(p.home_currency, "ZAR")

    def test_linked_event_supersession(self):
        recon = EventReconstructor()
        evs = recon.get_user_events("user_01")
        event_ids = {e.event_id for e in evs}
        # event_98 (estimate) should be superseded by linked event_99 (settled refund)
        self.assertNotIn("event_98", event_ids)

    # 5. Forecaster & Safety Tests
    def test_amount_safe_to_pay_calculation(self):
        msg_updates = MessageParser().get_updates_for_user("user_test")
        forecaster = CashFlowForecaster(self.profile, self.events, msg_updates)
        req_date = date(2026, 1, 2)
        safe_amt = forecaster.calculate_amount_safe_to_pay(req_date, requested_amount=2000.0)
        self.assertGreater(safe_amt, 0.0)
        self.assertLessEqual(safe_amt, 2000.0)

    def test_minimum_balance_safety(self):
        msg_updates = MessageParser().get_updates_for_user("user_test")
        forecaster = CashFlowForecaster(self.profile, self.events, msg_updates)
        req_date = date(2026, 1, 2)
        # Payment exceeding available headroom should be marked unsafe
        unsafe_payment = [ScheduledPayment(payment_date=req_date, amount=10000.0)]
        self.assertFalse(forecaster.is_plan_safe(req_date, plan_payments=unsafe_payment))

    # 6. Plan Validator Tests
    def test_plan_validator_valid_plan(self):
        req = PurchaseRequest(
            request_id="req_test",
            user_id="user_test",
            request_date=date(2026, 1, 2),
            request_type="purchase",
            requested_amount=500.0,
            desired_completion_date=date(2026, 2, 1),
            allows_partial_payment=False,
            request_text="Test request"
        )
        plan = CandidatePlan(
            payment_method="full_payment",
            payment_plan_str="2026-01-02:500",
            payments=[ScheduledPayment(payment_date=date(2026, 1, 2), amount=500.0)],
            spending_changes_needed_str="none",
            spending_changes=[],
            earliest_date_for_full_payment="2026-01-02",
            affordability_status="affordable_now",
            total_payable_amount=500.0,
            is_safe=True
        )
        is_valid, errors = PlanValidator.validate_plan(plan, req, self.profile)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_plan_validator_protected_category_error(self):
        req = PurchaseRequest(
            request_id="req_test",
            user_id="user_test",
            request_date=date(2026, 1, 2),
            request_type="purchase",
            requested_amount=500.0,
            desired_completion_date=date(2026, 2, 1),
            allows_partial_payment=False,
            request_text="Test request"
        )
        invalid_plan = CandidatePlan(
            payment_method="full_payment",
            payment_plan_str="2026-01-02:500",
            payments=[ScheduledPayment(payment_date=date(2026, 1, 2), amount=500.0)],
            spending_changes_needed_str="stop:event_rent",
            spending_changes=[{'type': 'stop', 'event_id': 'event_rent', 'category': 'rent'}],
            earliest_date_for_full_payment="2026-01-02",
            affordability_status="affordable_with_plan",
            total_payable_amount=500.0,
            is_safe=True
        )
        is_valid, errors = PlanValidator.validate_plan(invalid_plan, req, self.profile)
        self.assertFalse(is_valid)
        self.assertTrue(any("protected category" in err for err in errors))

    # 7. Plan Ranking Tests
    def test_plan_ranking_prefers_on_time_and_no_spending_changes(self):
        req = PurchaseRequest(
            request_id="req_test",
            user_id="user_test",
            request_date=date(2026, 1, 2),
            request_type="purchase",
            requested_amount=500.0,
            desired_completion_date=date(2026, 2, 1),
            allows_partial_payment=False,
            request_text="Test request"
        )
        plan_with_changes = CandidatePlan(
            payment_method="full_payment",
            payment_plan_str="2026-01-02:500",
            payments=[ScheduledPayment(payment_date=date(2026, 1, 2), amount=500.0)],
            spending_changes_needed_str="stop:event_cloud",
            spending_changes=[{'type': 'stop', 'event_id': 'event_cloud', 'category': 'cloud_storage'}],
            earliest_date_for_full_payment="2026-01-02",
            affordability_status="affordable_with_plan",
            total_payable_amount=500.0,
            is_safe=True,
            payment_option_id="001"
        )
        plan_no_changes = CandidatePlan(
            payment_method="full_payment",
            payment_plan_str="2026-01-02:500",
            payments=[ScheduledPayment(payment_date=date(2026, 1, 2), amount=500.0)],
            spending_changes_needed_str="none",
            spending_changes=[],
            earliest_date_for_full_payment="2026-01-02",
            affordability_status="affordable_now",
            total_payable_amount=500.0,
            is_safe=True,
            payment_option_id="002"
        )
        best = PlanRanker.select_best_plan([plan_with_changes, plan_no_changes], req)
        self.assertEqual(best.spending_changes_needed_str, "none")

if __name__ == "__main__":
    unittest.main()
