# Token Usage and Cost Analysis

## Model Configuration

- **Provider**: Deterministic Financial Engine & Local Document OCR Pipeline
- **Model Name**: Deterministic Financial Engine + PyTesseract / EasyOCR (Buy or Wait? v1.0)
- **Total Requests Evaluated**: 250

## Token Usage Summary

| Metric | Value |
|---|---|
| Model Calls | 0 |
| Input Tokens | 0 |
| Output Tokens | 0 |
| Total Tokens | 0 |
| Average Tokens per Request | 0 |
| Total Estimated Cost ($) | $0.0000 |
| Estimated Cost per Request ($) | $0.0000 |

## Methodological Summary

The solution combines a strongly typed, deterministic Python financial simulation pipeline with a local document OCR pipeline:
1. **Local Document OCR & Image Evidence Extractor**: Preprocesses document PNG receipts/payslips (grayscale, contrast enhancement, binarization, upscaling) and extracts monetary amounts using local `pytesseract` OCR with fast startup checks and keyword-anchored regex parsing. Supports optional VLM API fallback when credentials are configured.
2. **Robust Unresolved Financial Amount Handling**: For unresolved essential/protected debits (`amount is None`), applies an outlier-robust conservative statistic (75th percentile with 1.15x median floor) to uphold the problem statement's 'financially safer interpretation' tie-break rule. Employs explicit logged exclusion paths and uncertainty flags for un-estimable debits.
3. **Structured Message & Lifecycle Parser**: Evaluates natural language messages for salary overrides, approved invoice income, rent increases, and contract completions.
4. **90-Day Cash-Flow Forecaster**: Daily balance simulation enforcing minimum balance safety (`minimum_balance_to_keep`).
5. **Deterministic Candidate Plan Generator & Ranker**: Evaluates full payment, partial payment, installment, and wait candidates against user preferences, ranking plans by compliance, safety, and payment count.
6. **Grounded Explanation Generator**: Produces clear decision explanations, explicitly noting when incomplete financial facts were conservatively estimated.

Because all calculations, currency conversions, local OCR extraction, and safety checks run locally in Python without mandatory remote LLM calls, default token usage and API costs are $0.00.
