# RQ1 - Ask types

- Population (classifier): first sessions - empty/error = **324,695** labelled asks.
- Sample (manual): **384** hand-coded sessions (validation sample, seed 123).
- Multi-intent: manual 26.6%, population 35.1%.
- Manual-sample provenance: 378/384 of the 384 exist in v1.0; 190 are first-sessions in v1.0 (the sample mixes asks and rounds and excludes review-requests; treat it as classifier validation).

| Ask type | Sample # | Sample % | Pop # | Pop % |
|---|---:|---:|---:|---:|
| **1. Code Authoring** | 186 | 48.4 | 160,345 | 49.4 |
| &nbsp;&nbsp;1.1 New Implementation | 41 | 10.7 | 59,043 | 18.2 |
| &nbsp;&nbsp;1.2 Iterative Modification | 140 | 36.5 | 99,503 | 30.6 |
| &nbsp;&nbsp;1.3 Unspecified Authoring | 5 | 1.3 | 1,799 | 0.6 |
| **2. Failure Reporting** | 81 | 21.1 | 68,368 | 21.1 |
| &nbsp;&nbsp;2.1 Log Paste | 41 | 10.7 | 21,371 | 6.6 |
| &nbsp;&nbsp;2.2 Symptom Description | 26 | 6.8 | 40,268 | 12.4 |
| &nbsp;&nbsp;2.3 Unspecified Failure | 14 | 3.6 | 6,729 | 2.1 |
| **3. Inquiry** | 30 | 7.8 | 14,950 | 4.6 |
| &nbsp;&nbsp;3.1 Planning & Consultation | 16 | 4.2 | 6,967 | 2.1 |
| &nbsp;&nbsp;3.2 Project Comprehension | 10 | 2.6 | 6,945 | 2.1 |
| &nbsp;&nbsp;3.3 General Knowledge Query | 4 | 1.0 | 1,038 | 0.3 |
| **4. Validation** | 22 | 5.7 | 43,337 | 13.3 |
| &nbsp;&nbsp;4.1 Code Review | 20 | 5.2 | 42,786 | 13.2 |
| &nbsp;&nbsp;4.2 Runtime Inspection | 2 | 0.5 | 551 | 0.2 |
| **5. Delegation** | 51 | 13.3 | 34,008 | 10.5 |
| &nbsp;&nbsp;5.1 Documentation | 17 | 4.4 | 16,436 | 5.1 |
| &nbsp;&nbsp;5.2 Toolchain Operation | 34 | 8.9 | 17,572 | 5.4 |
| **6. Others** | 14 | 3.6 | 3,687 | 1.1 |
| **Total** | 384 | 100.0 | 324,695 | 100.0 |
