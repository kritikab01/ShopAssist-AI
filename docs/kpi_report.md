# ShopAssist KPI report

Generated 22 Nov 2026 14:42 from the live database.

## Headline numbers

- Conversations handled by the AI: **107** (114 customer messages)
- Escalated to a human (tickets): **30** (30 high priority, 30 angry customers, 30 still open)
- Conversations resolved without a human (approx.): **72%**
- Customer satisfaction (thumbs up in the web app): **100% of 1 ratings**
- Identity checks last 7 days: **26** verified, **3** wrong digits (blocked)
- Products at or below reorder level: **5**
- Purchase orders drafted by the Inventory Agent: **6**

## Orders by status

| status | orders | value_inr |
|---|---|---|
| shipped | 3 | 7095.00 |
| delivered | 2 | 8397.00 |
| delayed | 1 | 1799.00 |
| cancelled | 1 | 599.00 |
| returned | 1 | 6299.00 |
| placed | 1 | 1599.00 |
| out_for_delivery | 1 | 4497.00 |

## Tickets by type and priority

| issue_type | priority | tickets |
|---|---|---|
| delivery | high | 20 |
| refund | high | 10 |

## Low stock

| sku | name | size | stock | reorder_level |
|---|---|---|---|---|
| TSH-BAS-L | Basics Cotton T-shi | L | 6 | 20 |
| JNS-RLX-28 | Relaxed Jeans | 28 | 0 | 10 |
| KUR-LIN-S | Linen Kurta | S | 3 | 8 |
| PLZ-COT-S | Cotton Palazzo | S | 4 | 8 |
| HOD-OVR-XL | Oversized Hoodie | XL | 9 | 10 |

## Latest purchase orders

| po_id | sku | quantity | est_cost_inr | status | decided_by | created_at |
|---|---|---|---|---|---|---|
| PO-0006 | TSH-BAS-L | 35 | 6300.00 | pending_approval | None | 2026-11-22 09:09:05 |
| PO-0005 | TSH-BAS-L | 35 | 6300.00 | pending_approval | None | 2026-11-22 08:53:05 |
| PO-0004 | TSH-BAS-L | 35 | 6300.00 | pending_approval | None | 2026-11-22 08:27:57 |
| PO-0003 | TSH-BAS-L | 35 | 6300.00 | pending_approval | None | 2026-10-11 12:27:11 |
| PO-0002 | TSH-BAS-L | 10 | 1800.00 | pending_approval | None | 2026-10-11 11:25:06 |
| PO-0001 | TSH-BAS-L | 10 | 1800.00 | pending_approval | None | 2026-10-11 06:25:21 |

## Latest tickets

| ticket_id | customer_name | order_id | issue_type | sentiment | priority | language | status | created_at |
|---|---|---|---|---|---|---|---|---|
| TKT-0030 | Rohan Gupta | UT1003 | delivery | angry | high | en | open | 2026-11-22 09:11:38 |
| TKT-0029 | Sneha Iyer | UT1004 | refund | angry | high | en | open | 2026-11-22 09:04:35 |
| TKT-0028 | Rohan Gupta | UT1003 | delivery | angry | high | en | open | 2026-11-22 09:03:24 |
| TKT-0027 | Rohan Gupta | UT1003 | delivery | angry | high | en | open | 2026-11-22 08:59:59 |
| TKT-0026 | Rohan Gupta | UT1003 | delivery | angry | high | en | open | 2026-11-22 08:59:37 |
| TKT-0025 | Rohan Gupta | UT1003 | delivery | angry | high | en | open | 2026-11-22 08:59:13 |
| TKT-0024 | Rohan Gupta | UT1003 | delivery | angry | high | en | open | 2026-11-22 08:58:26 |
| TKT-0023 | Rohan Gupta | UT1003 | delivery | angry | high | en | open | 2026-11-22 08:58:05 |

## Tickets by language

| language | tickets |
|---|---|
| en | 30 |

## Latest order events

| order_id | status | note | created_at |
|---|---|---|---|
| UT1007 | shipped | Status update from  | 2026-11-22 08:08:10 |
| UT1005 | out_for_delivery | Out for delivery in | 2026-10-10 08:30:00 |
| UT1006 | placed | Order placed (COD) | 2026-10-09 19:20:00 |
| UT1007 | packed | Packed at Bengaluru | 2026-10-09 10:00:00 |
| UT1003 | delayed | Ekart: festive-seas | 2026-10-09 08:00:00 |
| UT1007 | placed | Order placed (UPI) | 2026-10-08 22:10:00 |
| UT1010 | shipped | Handed to Ekart | 2026-10-08 09:50:00 |
| UT1005 | placed | Order placed (NetBa | 2026-10-07 11:00:00 |

