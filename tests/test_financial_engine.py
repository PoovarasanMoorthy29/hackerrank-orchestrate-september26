import os
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

    @unittest.skipUnless(os.path.exists("dataset/exchange_rates.csv"), "dataset/exchange_rates.csv not present")
    def test_currency_converter_foreign(self):
        converter = CurrencyConverter()
        converted = converter.convert(100.0, "EUR", "ZAR", date(2023, 10, 15))
        self.assertGreater(converted, 0.0)

    # 2. Image Extraction Tests
    @unittest.skipUnless(os.path.exists("dataset/images.csv"), "dataset/images.csv not present")
    def test_image_extractor_mapping(self):
        extractor = ImageExtractor()
        # Verifies that mapping loads correctly without hardcoded values
        self.assertIsNotNone(extractor.event_to_image)

    def test_image_extractor_unknown_defaults_to_none(self):
        extractor = ImageExtractor()
        amt = extractor.get_amount_for_event("non_existent_event")
        self.assertIsNone(amt)

    # 3. Message Parser Tests
    @unittest.skipUnless(os.path.exists("dataset/messages.csv"), "dataset/messages.csv not present")
    def test_message_parser_loads_user(self):
        parser = MessageParser()
        up = parser.get_updates_for_user("user_02")
        self.assertIsNotNone(up)

    @unittest.skipUnless(os.path.exists("dataset/messages.csv"), "dataset/messages.csv not present")
    def test_message_parser_seasonal_contract(self):
        parser = MessageParser()
        up = parser.get_updates_for_user("user_12")
        self.assertTrue(up.seasonal_contract_ended)

    # 4. Event Reconstruction & Lifecycle Tests
    @unittest.skipUnless(os.path.exists("dataset/financial_events.csv"), "dataset/financial_events.csv not present")
    def test_event_reconstructor_loads_user(self):
        recon = EventReconstructor()
        p = recon.get_profile("user_01")
        self.assertIsNotNone(p)
        self.assertEqual(p.home_currency, "ZAR")

    @unittest.skipUnless(os.path.exists("dataset/financial_events.csv"), "dataset/financial_events.csv not present")
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

    # 8. Issue 1 Fix Test: Missing amounts must NOT default to 0.0
    @unittest.skipUnless(os.path.exists("dataset/financial_events.csv"), "dataset/financial_events.csv not present")
    def test_blank_amount_failed_extraction_not_zero(self):
        recon = EventReconstructor()
        unresolved_events = [e for evs in recon.user_events.values() for e in evs if e.amount is None]
        for e in unresolved_events:
            self.assertNotEqual(e.amount, 0.0, f"Event {e.event_id} should have amount None, not 0.0")
            self.assertIsNone(e.amount)
        self.assertIsInstance(recon.unresolved_amount_event_ids, list)

    # 9. Issue 2 Fix Test: End-to-end synthetic receipt OCR extraction
    def test_synthetic_receipt_ocr_end_to_end(self):
        import tempfile
        import os
        from PIL import Image, ImageDraw
        extractor = ImageExtractor()
        
        # Test Synthetic Receipt 1
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path1 = f.name
        img1 = Image.new("RGB", (400, 250), color=(255, 255, 255))
        draw1 = ImageDraw.Draw(img1)
        draw1.text((20, 20), "SUPERMARKET RECEIPT", fill=(0, 0, 0))
        draw1.text((20, 60), "Groceries: $45.20", fill=(0, 0, 0))
        draw1.text((20, 100), "TOTAL DUE: $128.75", fill=(0, 0, 0))
        img1.save(path1)

        # Test Synthetic Payslip 2
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path2 = f.name
        img2 = Image.new("RGB", (400, 250), color=(255, 255, 255))
        draw2 = ImageDraw.Draw(img2)
        draw2.text((20, 20), "COMPANY PAYSLIP", fill=(0, 0, 0))
        draw2.text((20, 60), "Gross Pay: $4000.00", fill=(0, 0, 0))
        draw2.text((20, 100), "NET PAY: $3250.00", fill=(0, 0, 0))
        img2.save(path2)

        try:
            amt1 = extractor.extract_from_image_file(path1)
            amt2 = extractor.extract_from_image_file(path2)
            self.assertIsNotNone(amt1, "Failed to extract amount from synthetic receipt 1")
            self.assertIsNotNone(amt2, "Failed to extract amount from synthetic payslip 2")
            self.assertAlmostEqual(amt1, 128.75, places=2)
            self.assertAlmostEqual(amt2, 3250.00, places=2)
        finally:
            if os.path.exists(path1): os.remove(path1)
            if os.path.exists(path2): os.remove(path2)

    # 10. Issue 3 Fix Test: Seasonal contract message parsing (multilingual & varied phrasing)
    @unittest.skipUnless(os.path.exists("dataset/messages.csv"), "dataset/messages.csv not present")
    def test_message_parser_contract_endings(self):
        parser = MessageParser()
        up12 = parser.get_updates_for_user("user_12")
        self.assertTrue(up12.seasonal_contract_ended)
        up133 = parser.get_updates_for_user("user_133")
        self.assertTrue(up133.seasonal_contract_ended)
        up165 = parser.get_updates_for_user("user_165")
        self.assertTrue(up165.seasonal_contract_ended)

    # 11. New Test: Unresolved essential debit applies conservative estimate
    def test_unresolved_essential_debit_conservative_estimate(self):
        msg_up = MessageParser().get_updates_for_user("user_test")
        
        # Events without unresolved debit (baseline)
        baseline_events = [
            FinancialEvent("e_sal", "user_test", "income", "Salary", "salary", "credit", 5000.0, "USD", date(2026, 1, 1), date(2026, 1, 1), "settled"),
            FinancialEvent("e_rent_past", "user_test", "expense", "Rent", "rent", "debit", 1200.0, "USD", date(2025, 12, 1), date(2025, 12, 1), "settled"),
        ]
        forecaster_base = CashFlowForecaster(self.profile, baseline_events, msg_up)
        safe_base = forecaster_base.calculate_amount_safe_to_pay(date(2026, 1, 2), requested_amount=5000.0)

        # Events with unresolved essential debit (rent, amount=None)
        unresolved_events = list(baseline_events) + [
            FinancialEvent("e_rent_pending", "user_test", "expense", "Rent", "rent", "debit", None, "USD", date(2026, 1, 10), date(2026, 1, 10), "pending")
        ]
        forecaster_unresolved = CashFlowForecaster(self.profile, unresolved_events, msg_up, unresolved_event_ids=["e_rent_pending"])
        safe_unresolved = forecaster_unresolved.calculate_amount_safe_to_pay(date(2026, 1, 2), requested_amount=5000.0)

        # Assert conservative estimate ($1200 from history) was applied
        self.assertIn("e_rent_pending", forecaster_unresolved.estimated_unresolved_events)
        self.assertEqual(forecaster_unresolved.estimated_unresolved_events["e_rent_pending"], 1200.0)
        # Assert amount_safe_to_pay is measurably lower than baseline
        self.assertLess(safe_unresolved, safe_base)

    # 12. New Test: Unresolved debit with no estimate available takes explicit exclusion path
    def test_unresolved_debit_explicit_exclusion_path(self):
        msg_up = MessageParser().get_updates_for_user("user_test")
        unresolved_exotic = [
            FinancialEvent("e_exotic", "user_test", "expense", "Exotic Debt", "exotic_category", "debit", None, "USD", date(2026, 1, 10), date(2026, 1, 10), "pending")
        ]
        forecaster = CashFlowForecaster(self.profile, unresolved_exotic, msg_up, unresolved_event_ids=["e_exotic"])
        _ = forecaster.forecast_daily_balances(date(2026, 1, 2))

        # Assert explicit exclusion path was taken and flagged as uncertain
        self.assertIn("e_exotic", forecaster.excluded_unresolved_events)
        self.assertTrue(forecaster.has_uncertain_unresolved_expense)

    # 13. New Test: ExplanationGenerator mentions incomplete/estimated financial facts
    def test_explanation_generator_unresolved_amounts_mention(self):
        req = PurchaseRequest("req_test", "user_test", date(2026, 1, 2), "purchase", 500.0, date(2026, 2, 1), False, "Test")
        plan = CandidatePlan("full_payment", "2026-01-02:500", [ScheduledPayment(date(2026, 1, 2), 500.0)], "none", [], "2026-01-02", "affordable_now", 500.0, True, payment_option_id=None)
        
        expl_normal = ExplanationGenerator.generate_explanation(req, self.profile, plan, 500.0, has_unresolved_amounts=False)
        expl_unresolved = ExplanationGenerator.generate_explanation(req, self.profile, plan, 500.0, has_unresolved_amounts=True)

        self.assertNotIn("conservatively estimated", expl_normal)
        self.assertIn("conservatively estimated", expl_unresolved)

    # 14. Request 1 Test: Uncovered currency conversion returns None and marks event unresolved
    def test_uncovered_currency_conversion_returns_none(self):
        converter = CurrencyConverter()
        converted = converter.convert(100.0, "XYZ_CURRENCY", "USD", date(2026, 1, 1))
        self.assertIsNone(converted)
        self.assertTrue(any(pair[0] == "XYZ_CURRENCY" for pair in converter.missing_rate_pairs))

    # 15. Request 2 Test: Outlier sensitivity in conservative estimate
    def test_outlier_robust_conservative_estimate(self):
        msg_up = MessageParser().get_updates_for_user("user_test")
        events_with_outlier = [
            FinancialEvent("e_sal", "user_test", "income", "Salary", "salary", "credit", 5000.0, "USD", date(2026, 1, 1), date(2026, 1, 1), "settled"),
            FinancialEvent("e_util_1", "user_test", "expense", "Utility 1", "utilities", "debit", 100.0, "USD", date(2025, 10, 1), date(2025, 10, 1), "settled"),
            FinancialEvent("e_util_2", "user_test", "expense", "Utility 2", "utilities", "debit", 105.0, "USD", date(2025, 11, 1), date(2025, 11, 1), "settled"),
            FinancialEvent("e_util_3", "user_test", "expense", "Utility 3", "utilities", "debit", 110.0, "USD", date(2025, 12, 1), date(2025, 12, 1), "settled"),
            FinancialEvent("e_util_outlier", "user_test", "expense", "Misc insurance error", "utilities", "debit", 5000.0, "USD", date(2025, 12, 15), date(2025, 12, 15), "settled"),
            FinancialEvent("e_util_unresolved", "user_test", "expense", "Utility Pending", "utilities", "debit", None, "USD", date(2026, 1, 10), date(2026, 1, 10), "pending"),
        ]
        forecaster = CashFlowForecaster(self.profile, events_with_outlier, msg_up, unresolved_event_ids=["e_util_unresolved"])
        _ = forecaster.forecast_daily_balances(date(2026, 1, 2))

        est = forecaster.estimated_unresolved_events.get("e_util_unresolved")
        self.assertIsNotNone(est)
        self.assertLess(est, 5000.0, "Estimate should not be dominated by single 5000.0 outlier")
        self.assertGreater(est, 100.0, "Estimate should be above minimum typical value")

    # 16. Request 3 Test: Prefix user ID matching produces no cross-contamination
    def test_prefix_user_id_unresolved_isolation(self):
        import tempfile
        # Create temp profiles & events for user_1 and user_10
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f_prof:
            prof_path = f_prof.name
            f_prof.write("user_id,home_currency,current_available_balance,minimum_balance_to_keep,financial_priorities,expense_categories_to_protect,expense_categories_user_is_willing_to_reduce,expense_categories_user_is_willing_to_stop,payment_methods_user_will_consider,max_installment_months\n")
            f_prof.write("user_1,USD,5000,1000,housing,rent,,,full_payment,\n")
            f_prof.write("user_10,USD,5000,1000,housing,rent,,,full_payment,\n")

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f_ev:
            ev_path = f_ev.name
            f_ev.write("event_id,user_id,event_type,description,category,direction,amount,currency,event_date,settlement_date,status,linked_event_id,flexibility,minimum_allowed_amount\n")
            f_ev.write("e_u1_unresolved,user_1,expense,Rent,rent,debit,,USD,2026-01-05,2026-01-05,pending,,,\n")
            f_ev.write("e_u10_normal,user_10,expense,Rent,rent,debit,1000,USD,2026-01-05,2026-01-05,settled,,,\n")

        try:
            recon = EventReconstructor(events_csv_path=ev_path, profiles_csv_path=prof_path)
            u1_unresolved = recon.get_unresolved_event_ids_for_user("user_1")
            u10_unresolved = recon.get_unresolved_event_ids_for_user("user_10")
            self.assertEqual(u1_unresolved, ["e_u1_unresolved"])
            self.assertEqual(u10_unresolved, [], "user_10 should have zero unresolved event IDs despite user_1 prefix match")
        finally:
            if os.path.exists(prof_path): os.remove(prof_path)
            if os.path.exists(ev_path): os.remove(ev_path)

    # 17. Request 4 Test: Standalone end-to-end execution against tests/fixtures/
    def test_end_to_end_fixture_pipeline(self):
        import csv
        from code.main import process_requests

        fixture_requests = "tests/fixtures/requests.csv"
        fixture_output = "tests/fixtures/output.csv"

        process_requests(
            requests_csv_path=fixture_requests,
            output_csv_path=fixture_output,
            profiles_csv="tests/fixtures/financial_profiles.csv",
            events_csv="tests/fixtures/financial_events.csv",
            exchange_rates_csv="tests/fixtures/exchange_rates.csv",
            options_csv="tests/fixtures/request_payment_options.csv",
            messages_csv="tests/fixtures/messages.csv",
            images_csv="tests/fixtures/images.csv",
            media_dir="tests/fixtures/media/images"
        )

        self.assertTrue(os.path.exists(fixture_output))
        with open(fixture_output, 'r', encoding='utf-8') as f:
            reader = list(csv.DictReader(f))

        self.assertEqual(len(reader), 4)

        valid_statuses = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
        valid_methods = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}

        for row in reader:
            safe_amt = float(row['amount_safe_to_pay'])
            self.assertGreaterEqual(safe_amt, 0.0)
            self.assertIn(row['affordability_status'], valid_statuses)
            self.assertIn(row['recommended_payment_method'], valid_methods)
            self.assertTrue(len(row['decision_explanation'].strip()) > 0)

            # Invariant check for partial_payment sum
            if row['recommended_payment_method'] == 'partial_payment':
                parts = row['payment_plan'].split('|')
                self.assertEqual(len(parts), 2)
                p1 = float(parts[0].split(':')[1])
                p2 = float(parts[1].split(':')[1])
                self.assertAlmostEqual(p1 + p2, 2000.0, places=2)

    # 18. Rule 6 Test: Two installment candidates tied on rules 1-5 — lower payment_option_id wins
    def test_installment_option_id_tiebreaker(self):
        req = PurchaseRequest("req_t", "u_t", date(2026, 1, 2), "purchase", 500.0, date(2026, 2, 1), False, "Test")
        plan1 = CandidatePlan("installments", "2026-01-02:500", [ScheduledPayment(date(2026, 1, 2), 500.0)], "none", [], "2026-01-02", "affordable_with_plan", 500.0, True, payment_option_id="opt_2_1")
        plan2 = CandidatePlan("installments", "2026-01-02:500", [ScheduledPayment(date(2026, 1, 2), 500.0)], "none", [], "2026-01-02", "affordable_with_plan", 500.0, True, payment_option_id="opt_1_1")

        best = PlanRanker.select_best_plan([plan1, plan2], req)
        self.assertEqual(best.payment_option_id, "opt_1_1", "Lower option ID opt_1_1 should win rule 6 tie-break over opt_2_1")

    # 19. Method Preference Test: Tied full_payment vs installments on rules 1-5 — full_payment wins by explicit policy
    def test_full_payment_vs_installments_tie_breaking_policy(self):
        # DESIGN POLICY: When a full_payment and an installments plan are identical on rules 1-5 (both on-time,
        # 0 spending changes, same total cost, same start date, 1 payment), full_payment is preferred because it
        # settles the financial obligation immediately upfront without initiating a multi-installment credit structure.
        req = PurchaseRequest("req_t", "u_t", date(2026, 1, 2), "purchase", 500.0, date(2026, 2, 1), False, "Test")
        plan_full = CandidatePlan("full_payment", "2026-01-02:500", [ScheduledPayment(date(2026, 1, 2), 500.0)], "none", [], "2026-01-02", "affordable_now", 500.0, True, payment_option_id=None)
        plan_inst = CandidatePlan("installments", "2026-01-02:500", [ScheduledPayment(date(2026, 1, 2), 500.0)], "none", [], "2026-01-02", "affordable_with_plan", 500.0, True, payment_option_id="opt_1_1")

        best = PlanRanker.select_best_plan([plan_inst, plan_full], req)
        self.assertEqual(best.payment_method, "full_payment", "Full payment should win tie against single-payment installment by explicit method preference policy")

    # 20. Natural Numeric Sort Test: Multi-digit option IDs (opt_2 vs opt_10) sort numerically
    def test_natural_numeric_option_id_sorting(self):
        req = PurchaseRequest("req_t", "u_t", date(2026, 1, 2), "purchase", 500.0, date(2026, 2, 1), False, "Test")
        plan10 = CandidatePlan("installments", "2026-01-02:500", [ScheduledPayment(date(2026, 1, 2), 500.0)], "none", [], "2026-01-02", "affordable_with_plan", 500.0, True, payment_option_id="opt_10")
        plan2 = CandidatePlan("installments", "2026-01-02:500", [ScheduledPayment(date(2026, 1, 2), 500.0)], "none", [], "2026-01-02", "affordable_with_plan", 500.0, True, payment_option_id="opt_2")

        best = PlanRanker.select_best_plan([plan10, plan2], req)
        self.assertEqual(best.payment_option_id, "opt_2", "Natural sorting must place opt_2 before opt_10 (unlike naive string comparison)")

    # 21. Double-Counting Fix Test: Exact reproduction case
    def test_recurring_expense_no_double_counting_with_pending(self):
        msg_up = MessageParser().get_updates_for_user("u1")
        events = [
            FinancialEvent('e1', 'u1', 'expense', 'Rent Nov', 'rent', 'debit', 1000.0, 'USD', date(2025, 11, 5), date(2025, 11, 5), 'settled'),
            FinancialEvent('e2', 'u1', 'expense', 'Rent Dec', 'rent', 'debit', 1000.0, 'USD', date(2025, 12, 5), date(2025, 12, 5), 'settled'),
            FinancialEvent('e3', 'u1', 'expense', 'Rent Jan (scheduled)', 'rent', 'debit', 1000.0, 'USD', date(2026, 1, 5), date(2026, 1, 5), 'pending'),
        ]
        prof = FinancialProfile('u1', 'USD', 5000.0, 1000.0, [], ['rent'], [], [], ['full_payment'])
        forecaster = CashFlowForecaster(prof, events, msg_up)
        balances = forecaster.forecast_daily_balances(date(2026, 1, 1), forecast_days=10)
        
        # Day-by-day balance dict
        bal_dict = dict(balances)
        # Jan 1 to Jan 4 balance should be 5000.0
        self.assertEqual(bal_dict[date(2026, 1, 4)], 5000.0)
        # On Jan 5, balance drops by exactly $1000 to 4000.0 (not $2000 double-counted)
        self.assertEqual(bal_dict[date(2026, 1, 5)], 4000.0)

    # 22. Double-Counting Fix Test: Synthetic projection fires when NO pending record exists
    def test_recurring_expense_synthetic_projection_when_no_pending(self):
        msg_up = MessageParser().get_updates_for_user("u1")
        events = [
            FinancialEvent('e1', 'u1', 'expense', 'Rent Nov', 'rent', 'debit', 1000.0, 'USD', date(2025, 11, 5), date(2025, 11, 5), 'settled'),
            FinancialEvent('e2', 'u1', 'expense', 'Rent Dec', 'rent', 'debit', 1000.0, 'USD', date(2025, 12, 5), date(2025, 12, 5), 'settled'),
        ]
        prof = FinancialProfile('u1', 'USD', 5000.0, 1000.0, [], ['rent'], [], [], ['full_payment'])
        forecaster = CashFlowForecaster(prof, events, msg_up)
        balances = forecaster.forecast_daily_balances(date(2026, 1, 1), forecast_days=10)
        
        bal_dict = dict(balances)
        self.assertEqual(bal_dict[date(2026, 1, 4)], 5000.0)
        self.assertEqual(bal_dict[date(2026, 1, 5)], 4000.0)

    # 23. Double-Counting Fix Test: Near-miss date deduplication
    def test_recurring_expense_near_miss_date_deduplication(self):
        msg_up = MessageParser().get_updates_for_user("u1")
        events = [
            FinancialEvent('e1', 'u1', 'expense', 'Rent Nov', 'rent', 'debit', 1000.0, 'USD', date(2025, 11, 5), date(2025, 11, 5), 'settled'),
            FinancialEvent('e2', 'u1', 'expense', 'Rent Dec', 'rent', 'debit', 1000.0, 'USD', date(2025, 12, 5), date(2025, 12, 5), 'settled'),
            # Pending rent is on Jan 3 due to weekend shift (historical pattern was 5th)
            FinancialEvent('e3', 'u1', 'expense', 'Rent Jan Early', 'rent', 'debit', 1000.0, 'USD', date(2026, 1, 3), date(2026, 1, 3), 'pending'),
        ]
        prof = FinancialProfile('u1', 'USD', 5000.0, 1000.0, [], ['rent'], [], [], ['full_payment'])
        forecaster = CashFlowForecaster(prof, events, msg_up)
        balances = forecaster.forecast_daily_balances(date(2026, 1, 1), forecast_days=10)
        
        bal_dict = dict(balances)
        # On Jan 3, explicit pending bill drops balance to 4000.0
        self.assertEqual(bal_dict[date(2026, 1, 3)], 4000.0)
        # On Jan 5, balance remains 4000.0 (synthetic Jan 5 projection suppressed by Jan month match)
        self.assertEqual(bal_dict[date(2026, 1, 5)], 4000.0)

if __name__ == "__main__":
    unittest.main()
