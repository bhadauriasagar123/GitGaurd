# Regulatory dataset

Loaded by **Load regulatory dataset** in the UI (`POST /api/v1/sample/load?dataset=real`). Every file can also be uploaded on its own through the **Upload** tab.

| File | Upload as | Code / version | Source |
|---|---|---|---|
| `07_bank_control_framework.txt` | Control framework | – | Bank control framework (23 controls) in the production upload format |
| `08_control_testing_evidence.json` | Test evidence | – | Control-testing register (25 records). Dates are shifted relative to `asOf` when loaded by the button |
| `01_certin_directions_2022.txt` | Regulation | `IN-CERTIN` 1.0 | CERT-In Directions No. 20(3)/2022, 28 April 2022 (IT Act s.70B(6)) |
| `02_rbi_cyber_security_framework_2016.txt` | Regulation | `IN-RBI-CSF` 1.0 | RBI Cyber Security Framework in Banks, 2 June 2016 |
| `03_rbi_kyc_master_direction_2016.txt` | Regulation | `IN-RBI-KYC` 1.0 | RBI Master Direction – KYC, 2016 (as amended), with PMLA record keeping |
| `04_dpdp_act_2023.txt` | Regulation | `IN-DPDP` 1.0 | Digital Personal Data Protection Act, 2023 |
| `06_eu_gdpr_2016.txt` | Regulation | `EU-GDPR` 1.0 | Regulation (EU) 2016/679 |
| `05_dpdp_act_and_rules_2025.txt` | Regulation | `IN-DPDP` **2.0** | DPDP Act read with the DPDP Rules, 2025. Upload after 1.0 to trigger change-impact analysis |
| `09_poisoned_vendor_bulletin.html` | Regulation (HTML) | `VENDOR-ADV` 1.0 | Attack sample: must be **blocked** by the firewall |

Regulation clauses are faithful summaries of the operative requirements, not verbatim legal text. Check the official source before relying on them. The control framework and evidence describe a typical Indian scheduled commercial bank. Replace them with your own framework and evidence register to assess a real institution.

Deliberate findings the platform should surface: incident reporting SLA of 24 h vs 6 h (CERT-In, RBI), log retention of 90 days vs 180 days (CERT-In) and one year (DPDP Rules), a failed crisis-management drill, stale privileged-access recertification, a re-KYC backlog, untested parental-consent control, and the KYC 5-year retention vs DPDP/GDPR erasure tension.

`manifest.json` holds the load order, the bank profile and the gold labels used by `python -m scripts.eval_accuracy real`.
