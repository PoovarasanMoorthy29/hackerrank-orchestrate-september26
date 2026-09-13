"""
Core Data Models for HackerRank Orchestrate "Buy or Wait?" Financial Agent.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict, Any

@dataclass
class FinancialProfile:
    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: List[str]
    expense_categories_to_protect: List[str]
    expense_categories_user_is_willing_to_reduce: List[str]
    expense_categories_user_is_willing_to_stop: List[str]
    payment_methods_user_will_consider: List[str]
    max_installment_months: Optional[int] = None

@dataclass
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str        # income, expense, transfer, investment, etc.
    description: str
    category: str
    direction: str         # credit, debit
    amount: Optional[float]          # normalized in event currency or home currency (None if unresolved)
    currency: str
    event_date: date
    settlement_date: date
    status: str            # settled, pending, scheduled, unrealized, failed, cancelled, forecast
    linked_event_id: str = ""
    flexibility: str = "fixed" # fixed, flexible, stoppable, reducible, protected
    minimum_allowed_amount: Optional[float] = None
    is_recurring: bool = False
    recurrence_day: Optional[int] = None

@dataclass
class Message:
    message_id: str
    user_id: str
    request_id: str
    related_event_id: str
    sent_at: str
    source_type: str
    message_text: str

@dataclass
class PurchaseRequest:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str

@dataclass
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str      # full_payment, installments, etc.
    payment_amount: float
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int
    financing_fee: float
    total_payable_amount: float

@dataclass
class ScheduledPayment:
    payment_date: date
    amount: float

@dataclass
class CandidatePlan:
    payment_method: str                       # full_payment, partial_payment, installments, wait, not_recommended
    payment_plan_str: str                     # YYYY-MM-DD:amount|... or none
    payments: List[ScheduledPayment]
    spending_changes_needed_str: str          # stop:event_id|reduce_to:event_id:amount or none
    spending_changes: List[Dict[str, Any]]
    earliest_date_for_full_payment: str       # YYYY-MM-DD or empty
    affordability_status: str                 # affordable_now, affordable_with_plan, affordable_later, not_affordable
    total_payable_amount: float
    is_safe: bool = False
    payment_option_id: Optional[str] = None

@dataclass
class Recommendation:
    request_id: str
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_explanation: str
