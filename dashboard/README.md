# Closet Indexing dashboard: Power BI build spec (P6, DECISIONS D-058)

Audience: the product/research team of a wealth platform deciding which large-cap funds to flag.
Source: `data/powerbi/*.csv`, written by `python run_pipeline.py --offline` (step `export`). The pipeline validates
the export before writing it (unique keys; every fund, date and plan in a fact table exists in its dimension).
Refresh = re-run the pipeline, then Home > Refresh in Power BI.

## 1. Load the data (once)

1. **Parameter for the folder.** Home > Transform data > Manage Parameters > New: name `DataFolder`, type Text,
   current value = the full path of `data\powerbi\` **with a trailing backslash**
   (e.g. `C:\Users\yashs\Documents\Project1\data\powerbi\`).
2. **Loader function.** In Power Query: New Source > Blank Query, open Advanced Editor, paste, name it `fnLoad`:
   ```
   (name as text) =>
   let
       Source   = Csv.Document(File.Contents(DataFolder & name & ".csv"),
                               [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
       Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true])
   in
       Promoted
   ```
3. **One query per table.** New Source > Blank Query with formula `= fnLoad("dim_fund")`, name it `dim_fund`.
   Repeat for: `dim_date dim_class dim_plan fact_fund_month fact_rolling fact_daily fact_ter_daily fact_variant
   sensitivity passive_floor build_info`.
4. **Types.** For each query: select all columns > Transform > Detect Data Type, then check:
   dates (`date`, `month_start`, `month_end`, `available_from`) = Date; `TRUE/FALSE` columns = True/False;
   ids, labels, `plan`, `window`, `status`, `class_*` = Text. Decimals use `.`. Close & Apply.
   Untick "Enable load" for `fnLoad`.

## 2. Data model

| From (many) | To (one) | Cardinality / filter |
|---|---|---|
| `fact_fund_month[fund_id]`, `fact_rolling[fund_id]`, `fact_daily[fund_id]`, `fact_ter_daily[fund_id]`, `fact_variant[fund_id]` | `dim_fund[fund_id]` | many-to-one, single |
| `fact_daily[date]`, `fact_ter_daily[date]`, `fact_rolling[month_end]`, `fact_fund_month[month_start]`, `passive_floor[month_start]` | `dim_date[date]` | many-to-one, single |
| `fact_daily[plan]`, `fact_rolling[plan]`, `fact_ter_daily[plan]` | `dim_plan[plan]` | many-to-one, single |
| `dim_fund[class_main]` | `dim_class[class_main]` | many-to-one, single |

`sensitivity`, `build_info` and `Threshold` stay **unrelated**. Then:
- Table tools > **Mark as date table**: `dim_date`, column `date`.
- Sort by column: `dim_class[class_label]` by `class_sort`; `dim_date[month_label]` by `month_sort`;
  `dim_plan[plan_label]` by `plan_sort`.
- Hide key and technical columns from report view (`*_id`, `*_sort`, `n_*`).
- Measures: create the `_Measures` table and paste everything in `measures.dax` (one measure at a time).
  Create the `Threshold` parameter first (instructions at the top of the file).

## 3. Colours and conventions

| Class | Colour | Hex |
|---|---|---|
| Truly active | blue | `#2E6DB4` |
| Closet indexer | amber | `#D99A00` |
| Closet + underperforming | red | `#C0392B` |
| Not classified | grey | `#9AA0A6` |
| Index fund / Excluded | dark grey / light grey | `#5B5B5B` / `#CFCFCF` |

Colour is never the only signal: every class-coloured visual also shows the class label (data labels or
legend). Percent format for fractions; `0.00 pp` for TER and fee gaps; Rs crore with 0 decimals. Canvas 16:9.

## 4. Pages

### Page 1: The answer
*Question it answers: how many funds are closet indexers, and what do their investors pay for it?*
- **Cards (top row):** `[Funds Classified]`, `[Closet Funds]`, `[Closet Underperforming Funds]`,
  `[Annual Fee Gap Closet (Rs cr)]` titled **"Fees paid above an index fund, Rs cr/yr"**.
- **Clustered bar:** axis `dim_class[class_label]`, value count of `dim_fund[fund_id]`; filter class not in
  {Index fund, Excluded}; colours per §3; data labels on.
- **Table:** filter `dim_fund[class_main]` in {closet, closet_underperforming}. Columns `fund_label`,
  `[Active Share (12m avg)]`, `[Fee Gap pp (avg)]`, `[Excess Regular 24m]`, `[Excess Regular 12m]`,
  `[Annual Fee Gap (Rs cr)]`, `[Main Label Agreement]`. Sort by active share ascending. Conditional
  formatting on both excess columns (red if < 0).
- **Text box (the caveat, verbatim):** "Closet = active share below 0.40. Over 24 months 9 of these 10 funds beat
  the Nifty 100 TRI after regular-plan fees; over the latest 12 months most trailed it. The fee figure is what
  investors paid above an index fund, not money lost."

### Page 2: Active share vs outcome
- **Scatter:** X `dim_fund[active_share_main_mean]`, Y `dim_fund[excess_regular_24m]`, size
  `dim_fund[regular_aaum_crore]`, legend `dim_class[class_label]`, details `dim_fund[fund_label]`. Filter
  `has_holdings = TRUE`. Analytics pane: X constant line at **0.40** ("closet threshold"), X constant line at
  `[Passive Floor (80% index + 20% outside)]` ("passive floor, 0.20"), Y constant line at 0.
- **Bar (right):** `fund_label` by `[Fee Gap pp (avg)]`, colour by class, sorted descending, all eligible
  active funds (includes the 15 not classified, labelled as such).
- **Subtitle:** "Each dot is a fund. Left of the line = closet indexer. Below zero = trailed the index after fees."

### Page 3: Fund detail
- **Slicers:** `dim_fund[fund_label]` (single select, filter role = active), `dim_plan[plan_label]`
  (single select, default Regular plan).
- **Cards:** `Class at Threshold`, `[Active Share (12m avg)]`, `[Fee Gap pp (avg)]`,
  `[Fee per Rs 1 lakh, 2y (avg)]`, `[Tracking Error 24m]`.
- **Line (growth):** axis `dim_date[date]` (filter `in_window = TRUE`), values `[Fund Growth of 100]`,
  `[Index Growth of 100]`.
- **Line (active share):** axis `dim_date[month_start]`, values `[Active Share (month)]`,
  `[Out-of-Index Weight (month)]`; constant line 0.40. Empty for funds without holdings (title says so).
- **Line (rolling):** axis `fact_rolling[month_end]`, values `[Rolling Excess Return]`, `[Rolling Tracking Error]`;
  page filter `fact_rolling[window] = 12m`.
- **Line (fees):** axis `dim_date[date]`, values `[Fund TER pp]`, `[Index Fund TER pp]`.

### Page 4: Robustness
- **Slicer:** `Threshold` parameter (slider 0.20 to 0.70).
- **Cards:** `[Closet at Threshold]`, `[Closet Underperforming at Threshold]`, `[Truly Active at Threshold]`.
- **Matrix:** rows `dim_fund[fund_label]` (has_holdings = TRUE), columns `fact_variant[threshold]` then
  `fact_variant[underperformance]`, values First `fact_variant[class_variant]`; background colour by class
  (rules per §3). Filter `active_share_version = main` (add a slicer to switch to `equity_only`).
- **Table:** `sensitivity` filtered to `active_share = active_share_main_mean`: threshold, underperformance,
  truly_active, closet, closet_underperforming.
- **Text:** "No fund changes class for any threshold between 0.37 and 0.43. Changing the return window from 24
  to 12 months moves most closet funds from 'closet' to 'closet + underperforming'."

### Page 5: Method and limitations
Text boxes (from `README.md` / `DECISIONS.md`, kept short):
- Active share vs a Nifty 100 **index fund's disclosed portfolio** (Bandhan; tracking error 0.025%/yr), not NSE
  constituent weights.
- Holdings are month-end snapshots disclosed with a lag (known from the 11th of the next month); intra-month
  trading is invisible. Classification is descriptive, not a forecast.
- 17 of 32 eligible active funds have holdings in scope (the largest funds, 95% of category AAUM); the other 15
  have returns and fees only.
- Survivorship: no large-cap scheme closed or merged in the window; a scheme launched and closed inside it would
  be missed.
- TER regime changed in Apr-2026 (brokerage and transaction cost now inside TER).
- **Table:** `build_info` (window, NAV snapshot, threshold, generated at).

## 5. Acceptance checks (P6)
1. Page 1 cards equal `data/analysis/class_summary.csv`: Funds Classified = 17; Closet Funds = closet + closet
   underperforming funds (10); Closet Underperforming = 1; Annual Fee Gap Closet = the sum of
   `annual_fee_gap_rs_crore_at_q4fy26_aaum` over those two rows.
2. Page 4 at slider 0.40 shows the same three counts as Page 1; at 0.50 and 0.60 it matches the `sensitivity`
   table rows with `underperformance = regular_excess_24m`.
3. Page 3, any fund with holdings, regular plan: the last point of `[Fund Growth of 100]` equals
   100 x (1 + `fund_return`) of that fund's `fact_rolling` row (plan regular, window 24m, month_end 2026-08-31).
4. Save one PNG per page to `dashboard/screenshots/` (`p1_answer.png` ... `p5_method.png`) and the report as
   `dashboard/closet_indexing.pbix`.
