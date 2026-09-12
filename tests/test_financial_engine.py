"""
Unit and Integration Tests for Buy or Wait? Financial Engine.
"""

import unittest
from datetime import date
from code.models import FinancialProfile, FinancialEvent, PurchaseRequest, PaymentOption, ScheduledPayment
from code.currency import CurrencyConverter
from code.image_extractor import ImageExtractor
from code.message_parser import MessageParser
from code.forecaster import CashFlowForecaster
from code.plan_generator import PlanGenerator
from code.plan_ranker import PlanRanker
from code.explanation_generator import ExplanationGenerator

class TestFinancialEngine(unittest.TestCase):

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

    def test_currency_converter_same_currency(self):
        converter = CurrencyConverter()
        result = converter.convert(100.0, "USD", "USD", date(2026, 1, 1))
        self.assertEqual(result, 100.0)

    def test_image_extractor(self):
        extractor = ImageExtractor()
        amt = extractor.get_amount_for_event("event_253")
        self.assertEqual(amt, 4365000.0)

    def test_message_parser(self):
        parser = MessageParser()
        up = parser.get_updates_for_user("user_02")
        self.assertEqual(up.salary_amount_override, 42750000.0)

    def test_amount_safe_to_pay_calculation(self):
        msg_updates = MessageParser().get_updates_for_user("user_test")
        forecaster = CashFlowForecaster(self.profile, self.events, msg_updates)
        req_date = date(2026, 1, 2)
        safe_amt = forecaster.calculate_amount_safe_to_pay(req_date, requested_amount=2000.0)
        self.assertGreater(safe_amt, 0.0)
        self.assertLessEqual(safe_amt, 2000.0)

    def test_plan_ranking(self):
        req = PurchaseRequest(
            request_id="req_test",
            user_id="user_test",
            request_date=date(2026, 1, 2),
            request_type="purchase",
            requested_amount=1000.0,
            desired_completion_date=date(2026, 2, 1),
            allows_partial_payment=True,
            request_text="Test request"
        )
        msg_updates = MessageParser().get_updates_for_user("user_test")
        forecaster = CashFlowForecaster(self.profile, self.events, msg_updates)
        plan_gen = PlanGenerator()
        candidates = plan_gen.generate_candidate_plans(req, self.profile, forecaster, 1000.0, "2026-01-02")
        best = PlanRanker.select_best_plan(candidates, req)
        self.assertIsNotNone(best)
        self.assertIn(best.payment_method, ["full_payment", "installments", "partial_payment", "wait", "not_recommended"])

if __name__ == "__main__":
    unittest.main()
