# Test questions & expected behaviour

Run these in the **public chat URL** of workflow 03, after workflows 01 and 02 have filled Pinecone and
`schema.sql` + `seed.sql` have been run. Open a **new chat session** (refresh the page) before tests 6–8 so
memory from earlier tests does not interfere. Record the result and a screenshot for the report.

| # | Type | Customer message | Expected tool(s) | Expected behaviour | Pass? |
|---|------|------------------|------------------|--------------------|-------|
| 1 | FAQ answer | "What is your return policy?" | `faq_knowledge` | 15 days from delivery; unused with tags; innerwear/Final Sale not returnable; free reverse pickup. Ends with *(Source: Store FAQ)*. | |
| 2 | Website answer | "Is there any Diwali discount code?" | `website_knowledge` | Mentions **DIWALI25**: 25% off above Rs 2,499, 20 Oct – 5 Nov 2026; one coupon per order. Cites the offers page URL. | |
| 3 | Order lookup | "Where is my order UT1002?" | `order_lookup` | Status *shipped*, Delhivery, tracking DL55500112, expected 11 Oct 2026. *(Source: order database)* | |
| 4 | Combined | "My order UT1005 is a shirt that doesn't fit. Can I return it and how long will the refund take?" | `order_lookup` + `faq_knowledge` | Order is *out_for_delivery* → can return within 15 days **after delivery**; prepaid (NetBanking) refund 5–7 business days after QC; also mentions free size exchange. Cites both sources. | |
| 5 | Missing order ID | "When will my order arrive?" | none | Asks for the order ID (e.g. UT1001) or phone number. Does **not** guess or call `order_lookup`. | |
| 6 | Angry customer → escalation | "This is the THIRD time I'm asking! My jeans UT1003 are late and nobody replies. Worst service ever, I want to talk to a manager." (give name *Rohan*, phone *+919000000003* if asked) | `order_lookup`, `escalate_to_human` | Apologises, shows delay status, calls escalation. Replies with ticket ID like **TKT-0001**. Check: new row in `tickets` (priority *high*, sentiment *angry*), Slack message in `#support-escalations`, SMS (if number verified), e-mail to support inbox. | |
| 7 | Out of scope | "Can you write me a Python script to sort a list?" | none | Politely says it can only help with UrbanThread orders and policies. **No** escalation. | |
| 8 | Refund over limit | "I returned order UT1004, please refund me now." | `order_lookup`, `escalate_to_human` | Finds amount Rs 7,499 (> Rs 5,000) → explains it needs manual approval, escalates, gives ticket ID. Ticket `issue_type` = *refund*, priority *high*. | |

## Webhook test (workflow 05)

```bash
curl -X POST https://YOUR-N8N.app.n8n.cloud/webhook/order-update \
  -H 'Content-Type: application/json' \
  -d '{"order_id":"UT1002","status":"delayed","new_expected_delivery":"2026-10-15"}'
```

Expected: `{"ok":true,"order_id":"UT1002","status":"delayed","sms_sent":true,...}`, the `orders` row is
updated, and the customer phone gets a delay SMS. Then ask the chat *"Where is my order UT1002?"* –
the agent should now say **delayed**, new date 15 Oct 2026.

Unknown order: `{"order_id":"UT9999","status":"shipped"}` → `{"ok":false,"message":"Order not found"}`.

## Useful SQL checks (Supabase SQL editor)

```sql
SELECT * FROM tickets ORDER BY id DESC LIMIT 5;
SELECT order_id, status, expected_delivery, updated_at FROM orders ORDER BY updated_at DESC;
SELECT session_id, message->>'type' AS role, message->>'content' AS content
FROM n8n_chat_histories ORDER BY id DESC LIMIT 10;
```
