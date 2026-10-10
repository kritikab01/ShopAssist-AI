-- ShopAssist-AI database schema (Supabase Postgres)
-- Run this once in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run.
-- Then run seed.sql to load 10 fake orders.

-- 1) ORDERS: looked up by the agent tool "order_lookup" (workflow 03)
--    and updated by the order-update webhook (workflow 05).
CREATE TABLE IF NOT EXISTS orders (
    order_id        VARCHAR(10) PRIMARY KEY,          -- e.g. UT1001
    customer_name   VARCHAR(100) NOT NULL,
    phone           VARCHAR(20)  NOT NULL,            -- E.164 format, e.g. +919000000001
    email           VARCHAR(120),
    items           TEXT         NOT NULL,            -- short human-readable item list
    amount_inr      NUMERIC(10,2) NOT NULL,           -- order value in Rs
    payment_method  VARCHAR(20)  NOT NULL,            -- UPI / Card / COD / NetBanking
    status          VARCHAR(20)  NOT NULL DEFAULT 'placed'
                    CHECK (status IN ('placed','packed','shipped','out_for_delivery',
                                      'delivered','delayed','returned','cancelled')),
    city            VARCHAR(50),
    order_date      DATE         NOT NULL,
    expected_delivery DATE,
    courier         VARCHAR(30),
    tracking_no     VARCHAR(30),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders (phone);

-- 2) TICKETS: created by the escalation sub-workflow (workflow 04).
--    Columns match prompts/ticket_schema.json (the Structured Output Parser schema).
CREATE TABLE IF NOT EXISTS tickets (
    id               SERIAL PRIMARY KEY,
    ticket_id        VARCHAR(12) GENERATED ALWAYS AS ('TKT-' || LPAD(id::text, 4, '0')) STORED,
    customer_name    VARCHAR(100),
    phone            VARCHAR(20),
    order_id         VARCHAR(10),
    issue_type       VARCHAR(30),      -- refund / return / delivery / damaged_item / payment / size / other
    sentiment        VARCHAR(10),      -- positive / neutral / negative / angry
    priority         VARCHAR(10),      -- low / medium / high
    summary          TEXT,
    suggested_action TEXT,
    status           VARCHAR(15) NOT NULL DEFAULT 'open',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3) CHAT MEMORY: used by the "Postgres Chat Memory" node (workflow 03).
--    n8n creates this table automatically on first run; it is listed here so the
--    full data model is documented in one place. Table name must match the node setting.
CREATE TABLE IF NOT EXISTS n8n_chat_histories (
    id         SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    message    JSONB        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_session ON n8n_chat_histories (session_id);
