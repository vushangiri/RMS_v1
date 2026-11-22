# Business rules

| Metric or operation | Definition |
|---|---|
| Sales | Cash sales + bank sales + identified credit sales on the operating date. Payment method allocations create the recognized revenue. |
| New purchases / expenses | Sum of positive purchase-line amounts, whether paid or unpaid. This is an operational purchase report. Inventory valuation, tax and cost of goods sold are outside this ledger. |
| Paid at purchase | Cash plus bank allocations on the bill. Remaining bill total becomes a payable. Mixed payments use the entered amounts. |
| Counter credit settlements | Collections and payments posted by each counter on the operating date, through cash or bank. Each total links to the party, account, amount and record for every active settlement. |
| Outstanding credit | Original credit less linked collections/payments through the selected end date. A settlement must reference the correct record and cannot exceed the balance. |
| Opening drawer | Cumulative posted cash before the selected operating date, plus any opening balance entered for a new drawer on that date. |
| Expected drawer | Opening + signed movements through the date. Account balances carry across skipped dates. |
| Cash variance | Actual at count minus ledger cash immediately before the handover. A variance can remain visible at final close. |
| Retained physical cash | Actual counted less cash handed over. Subordinate settlement reconciles the variance and transfers all counted cash to Main in one posting. Finalization brings Main and any historical handover balances in line with retained cash and later same-day movements. Reopening reverses the finalization adjustments. Reversing a subordinate settlement reverses its variance and transfer together. |
| Cash in transit | Amount handed over less amount received at handover, less subsequent receipts against that handover. Main's cash increases only on receipt. |
| Restaurant cash | Sum of cash drawers; cash still in transit is a separate restaurant asset. Transfers between restaurant accounts have zero combined financial effect. |
| Bank balance | Cumulative signed bank postings. Deposits/withdrawals, bank-to-bank transfers and settlements do not recognize new sales or purchases. |
| Quantity sold | Sum of base-unit sale lines by item. No per-item sale price or revenue is inferred. |
| Estimated stock | Opening stock plus tracked purchases and signed adjustments, less tracked sales. A physical count rebaselines the live estimate. Each tracked catalogue variation has its own restaurant-wide balance. |
| Stock variance | Physical count minus the estimate at observation. New stock counts entered in RMS apply the difference in the same transaction. Historical observation-only counts can still be approved separately. |
| Report dates | Local calendar day in the deployment's operating timezone (Nepal by default), Monday–Sunday week, calendar month/year, or inclusive custom dates. Outstanding debt and stock balances use history through the end date. |

## Entry decisions

* Positive money allows two decimal places; base quantities allow three. Excess precision is rejected. The unit conversion pairs are kg/g and l/ml, and conversions must be representable in the base unit. Counts, plates and bottles retain their catalogue units. Use the original entry detail to inspect the submitted quantity and unit.
* An expense-only catalogue item may omit quantity. Tracked purchases require a quantity. A sales-only dish can still have quantity sold. Unrecorded kitchen consumption, waste and transfers affect the estimate until recorded by an adjustment.
* Operating balances cannot become negative at day end, including on later dates affected by a backdated entry. Bank overdrafts, supplier advances and customer deposits are outside this version. A signed stock adjustment with a reason records opening stock or waste.
* Each bill has one optional supplier. Every outstanding credit needs an identified party. Each sales batch can allocate payments to multiple banks and credit to multiple customers. Enter each bank and customer at most once per batch. Each customer allocation can be collected separately, and item quantities post once. The system cannot identify the same handwritten bill entered twice under different submission keys solely by its amount.
* Payment-method filters select bills with that method. The purchase report shows the full cost of matching lines. The purchase payment breakdown shows cash, bank and credit separately. The trade register's “moved” column sums the transaction's financial pairs. It should not be summed as restaurant revenue.
* Count subordinate drawers before Main. Record only the actual cash and explain any variance. The subordinate count records the full transfer to Main. Outstanding receipts from historical handovers must be confirmed before counting Main. A discrepancy requires an explanation at cash/bank count. Finalization requires a count from every active counter, including a zero count for an unused counter. Bank and physical stock observations are optional. A stock count may be recorded after cash closing for the latest finalized date, or dated on the next day when the count is performed. The closing snapshot preserves the figures used for the decision.
* Reverse a mistaken entry on its original date and re-enter it correctly. Reverse dependent settlements and affected later counts first. Reopen finalized dates newest first, with a reason. Original and corrected records remain in Audit history. Earlier closing snapshots preserve the original decisions.
* A counter can be deactivated after its cash balance reaches zero. Main stays active. Catalogue items can be deactivated; historical records remain. A tracking policy with financial stock history is protected. Physical-count entry can be switched off independently.

* Opening stock is a setup entry for a tracked product with no live stock activity. Product variations share a product name and category and can be created together with separate variation names, base units and stock tracking. Archive a product or an empty bank account to remove it from entry choices while preserving records. Existing records protect product units and stock tracking where changing them would alter the interpretation of history.

* Credit account history groups receivables by customer and payables by supplier. The running balance follows posted openings, new credit, settlements and reversals in operating-date and record order. An individual credit history includes only entries against that original credit.
* Cash and bank transaction history shows incoming and outgoing postings per account and record, including reversals. Transfers appear in the history of each affected account. To see both sides of a cash-to-bank transfer, use the combined report. All dates includes postings through the current operating day.
