# Interview defence: the 15 hardest questions

Honest answers, including where the work is weak. Numbers are filled from the pipeline's output.

## 1. Your title says investors pay active fees for index exposure. Did you show that?

Half of it. I showed the exposure and the fee: {{n_low}} of {{n_classified}} funds have an active share below {{threshold}}, and their regular-plan investors pay {{low_fee_mean}} points a year on average above an index fund's regular plan. I did not show harm. Over the 24 months, {{n_closet}} of those {{n_low}} beat the Nifty 100 TRI after fees. So the finding is "the fee is high relative to how different the portfolio is", not "these funds lose money for investors". The memo says that, and the recommendation is a disclosure, not a drop.

## 2. Why 0.40 and not the textbook 0.60? That looks like choosing a threshold to get a result.

At 0.60, {{n_as_under_060}} of {{n_classified}} funds are closet indexers, which is a statement about regulation: SEBI makes large-cap funds hold 80% in the top 100 stocks, so they cannot differ much from a 100-stock index. I measured what passive looks like under that rule (a Nifty 50 ETF scores {{floor_n50}}; 80% index plus 20% anything scores {{floor_sleeve}}) and then looked for a break in the data. The widest gap is between {{band_low}} and {{band_high}}, so any threshold in that range gives identical groups. I report 0.50 and 0.60 alongside. It is still a judgement, and I say so. One anchor I proposed first turned out to be degenerate (it equals 0.20 by construction); I removed it and kept a test that documents why.

## 3. {{flag_fund}}'s t-statistic is {{flag_t}}. Why act on noise?

On a significance test alone, I would not. The recommendation is to pause it for new regular-plan money, not to tell investors to sell. The argument is about the burden of proof: the fee gap ({{flag_fee_gap}} points a year) is certain, the fund overlaps the index by {{flag_overlap}}%, and it is the only fund behind on all {{n_variants}} variants, including the direct plan and after beta adjustment. Pausing is cheap to reverse and the memo sets the condition for reinstating it. If the interviewer says that is still thin, they are right: it is the weakest link in the memo and it is labelled as not significant there.

## 4. Your benchmark weights come from an index fund, not NSE. How wrong can that be?

The proxy is the {{index_fund}}, picked from three candidates for the lowest tracking error against the TRI ({{index_te_dir}}% a year), so its weights are close to the index. Errors come from cash, rebalancing lag and rounding. I expect them to be small next to the gap between the two groups ({{band_low}} to {{band_high}}), but I have not measured the proxy against NSE's own weights, so that is an expectation, not a result. NSE's constituent weights are the right source; I did not have a free history of them, which is why this is in the limitations.

## 5. Several funds benchmark to the BSE 100. You measured everyone against the Nifty 100.

Yes, deliberately: one benchmark makes funds comparable, and the two indices hold nearly the same stocks. But a fund managed against the BSE 100 will show slightly higher active share against the Nifty 100 than against its own benchmark, so my numbers, if anything, overstate how active those funds are. I recorded the stated benchmark wherever the portfolio file gives one, but did not compute active share against the BSE 100, because I had no BSE 100 weights.

## 6. Twelve months of holdings and twenty-four of returns. Why should anyone trust this?

They should trust it as a description of this period, not as a forecast. Only {{n_significant}} of {{n_classified}} funds has an excess return distinguishable from zero, and the result flips with the window: on the latest 12 months the classification is {{sens_040_12m}}. Active share itself is stable month to month, so the exposure finding is solid; the performance finding is not. The memo's next step is a re-run with 18 and 30 months.

## 7. You classified {{n_classified}} of {{n_eligible}} funds. Isn't that selection bias?

The cut was made before any result existed: the largest funds up to 95% of category assets, because every file is a manual download. The {{n_classified}} hold {{classified_aaum_share}}% of regular-plan assets. The bias is real in one direction: the excluded funds are small, and small funds are often more active, so "{{n_low}} of {{n_classified}}" overstates the share of funds that are closet indexers. That is why the memo leads with the asset-weighted figure ({{low_aaum_share}}%) and tells the platform not to apply the flag to the unclassified funds.

## 8. What about survivorship bias?

I compared AMFI's scheme list at the start of the window with today's. {{surv_present}} large-cap scheme codes exist at both ends and none closed or merged; {{surv_new}} are new launches or legacy plan codes. So there is no survivorship bias from closures in this window. The gap in the check: a scheme launched and closed inside the window would not appear in either snapshot.

## 9. Where could look-ahead bias enter, and what did you do?

Portfolios are published up to 10 days after month-end, so each one carries an `available_from` date of the 11th of the next month, and a SQL test fails the build if that rule is broken. The classification itself is contemporaneous (holdings and returns over the same period), so it is descriptive. It would be look-ahead if I presented it as a strategy that could have been followed, and I do not.

## 10. How did you treat derivatives, and did it matter?

Stock futures are added to the underlying stock's weight. Index futures are spread across the index's constituents using that month's weights. Options are excluded because month-end files do not give deltas, and I would have had to invent the exposure. I kept an equity-only version next to the main one: {{equity_only_note}}. The treatment matters most for quant, which runs a large futures book.

## 11. Is ₹{{low_cr}} crore a year the amount investors lost?

No. It is the fee paid above an index fund's regular plan by regular-plan investors in the {{n_low}} funds, at one quarter's average assets. Most of those funds returned more than the index after that fee in this window. I compared regular with regular so distributor commission is on both sides; against the direct plan of an index fund the gap would be larger. The accrual is simple, not compounded, and assets from one quarter are applied to a full year, so it is an order of magnitude, not an audited figure.

## 12. Seventeen AMCs, seventeen file formats. How do you know the parsers are right?

Each fund-month must reconcile to the grand total printed in the file itself, or the build stops. Each file's fund name and "as on" date are read from inside the file, which caught wrong downloads. Futures must match the exposure the file states where it states one. Weights and returns in the warehouse were reproduced by a separate pandas implementation that shares no code with the SQL. For expense ratios, the API data matched AMFI's Excel exports exactly wherever I had both. What I cannot rule out is an error that is in the AMC's own file; I logged the inconsistencies I found in source files rather than correcting them.

## 13. What mistakes did you make?

Several, all logged in `DECISIONS.md`. A rule meant to exclude Indian preference shares also excluded Franklin's holding in Cognizant, a US-listed ordinary share, because it read the Indian ISIN type code on a foreign ISIN; a test now fails the build if that happens. A "stability" column first showed each fund's most common label, which let the 0.50 and 0.60 thresholds outvote the main result; it now shows agreement with the main label. A sum-to-one SQL test passed on NULLs. And the threshold anchor in question 2. Each was found by a check or by reading output, which is the argument for having the checks.

## 14. Why not a factor model? A fund with beta {{flag_beta}} in a falling market gets a free ride.

That is the right worry: the TRI returned {{bench_ret_24}}% a year over the window and {{n_beta_below_1}} of {{n_classified}} funds have a beta below one, which flatters raw excess returns. I added a single-factor adjustment (beta against the Nifty 100 TRI) and the classification did not change. A size, value and momentum model would be better, but with 24 months the factor loadings would be estimated too loosely to trust, and there is no free, standard Indian factor dataset I could cite as a source. It is a limitation, not an oversight.

## 15. The commits are co-authored by an AI. What did you do?

The record is in the repository. I chose the question and the scope, downloaded every source file, ran every pipeline step and every acceptance check on my machine, and made the judgement calls marked "Decided by the user" in `DECISIONS.md` (futures treatment, index-future allocation, option and preference-share exclusions, the fee comparator, the threshold and the performance window). Claude wrote most of the code and drafted the documents under a rule set I wrote: no synthetic data, no guessed file layouts, no number stated unless it came from a run of mine. I can explain any file in the repository, and where I cannot, I should not claim it.
