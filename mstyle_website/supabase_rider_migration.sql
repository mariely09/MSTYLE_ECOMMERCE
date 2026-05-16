-- ============================================================
-- Rider tables migration for Supabase
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================

-- 1. orders table (mirrors MySQL orders)
CREATE TABLE IF NOT EXISTS orders (
  id                BIGSERIAL   PRIMARY KEY,
  name              TEXT,
  quantity          INT         DEFAULT 1,
  total_price       NUMERIC(10,2),
  payment_method    TEXT,
  status            TEXT        DEFAULT 'Pending',
  email             TEXT,        -- buyer email
  address           TEXT,
  seller_email      TEXT,
  rider_email       TEXT,
  image             TEXT,
  variations        TEXT,
  size              TEXT,
  product_id        BIGINT,
  shipping_fee      NUMERIC(10,2) DEFAULT 50,
  date              TIMESTAMPTZ DEFAULT NOW(),
  delivered_at      TIMESTAMPTZ,
  received_at       TIMESTAMPTZ,
  auto_complete_at  TIMESTAMPTZ,
  is_auto_completed BOOLEAN     DEFAULT FALSE,
  cancellation_reason TEXT,
  cancelled_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_orders_email        ON orders(email);
CREATE INDEX IF NOT EXISTS idx_orders_seller_email ON orders(seller_email);
CREATE INDEX IF NOT EXISTS idx_orders_rider_email  ON orders(rider_email);
CREATE INDEX IF NOT EXISTS idx_orders_status       ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_date         ON orders(date);

-- 2. rider_notifications table
CREATE TABLE IF NOT EXISTS rider_notifications (
  id          BIGSERIAL   PRIMARY KEY,
  rider_email TEXT        NOT NULL,
  message     TEXT        NOT NULL,
  order_id    BIGINT,
  is_read     BOOLEAN     DEFAULT FALSE,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rider_notif_email   ON rider_notifications(rider_email);
CREATE INDEX IF NOT EXISTS idx_rider_notif_is_read ON rider_notifications(is_read);
CREATE INDEX IF NOT EXISTS idx_rider_notif_order   ON rider_notifications(order_id);

-- 3. buyer_rider_messages table
CREATE TABLE IF NOT EXISTS buyer_rider_messages (
  id             BIGSERIAL   PRIMARY KEY,
  order_id       BIGINT      NOT NULL,
  sender_email   TEXT        NOT NULL,
  receiver_email TEXT        NOT NULL,
  message        TEXT        NOT NULL,
  is_read        BOOLEAN     DEFAULT FALSE,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brm_order_id       ON buyer_rider_messages(order_id);
CREATE INDEX IF NOT EXISTS idx_brm_sender         ON buyer_rider_messages(sender_email);
CREATE INDEX IF NOT EXISTS idx_brm_receiver       ON buyer_rider_messages(receiver_email);
CREATE INDEX IF NOT EXISTS idx_brm_is_read        ON buyer_rider_messages(is_read);

-- 4. seller_rider_messages table
CREATE TABLE IF NOT EXISTS seller_rider_messages (
  id             BIGSERIAL   PRIMARY KEY,
  order_id       BIGINT      NOT NULL,
  sender_email   TEXT        NOT NULL,
  receiver_email TEXT        NOT NULL,
  message        TEXT        NOT NULL,
  is_read        BOOLEAN     DEFAULT FALSE,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_srm_order_id  ON seller_rider_messages(order_id);
CREATE INDEX IF NOT EXISTS idx_srm_sender    ON seller_rider_messages(sender_email);
CREATE INDEX IF NOT EXISTS idx_srm_receiver  ON seller_rider_messages(receiver_email);
CREATE INDEX IF NOT EXISTS idx_srm_is_read   ON seller_rider_messages(is_read);

-- 5. notifications table (seller notifications)
CREATE TABLE IF NOT EXISTS notifications (
  id           BIGSERIAL   PRIMARY KEY,
  seller_email TEXT        NOT NULL,
  message      TEXT        NOT NULL,
  type         TEXT        DEFAULT 'order',
  is_read      BOOLEAN     DEFAULT FALSE,
  order_id     BIGINT,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_seller_email ON notifications(seller_email);
CREATE INDEX IF NOT EXISTS idx_notif_is_read      ON notifications(is_read);
CREATE INDEX IF NOT EXISTS idx_notif_type         ON notifications(type);

-- 6. buyer_notifications table
CREATE TABLE IF NOT EXISTS buyer_notifications (
  id          BIGSERIAL   PRIMARY KEY,
  buyer_email TEXT        NOT NULL,
  message     TEXT        NOT NULL,
  type        TEXT        DEFAULT 'status_update',
  is_read     BOOLEAN     DEFAULT FALSE,
  order_id    BIGINT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_buyer_notif_email   ON buyer_notifications(buyer_email);
CREATE INDEX IF NOT EXISTS idx_buyer_notif_is_read ON buyer_notifications(is_read);
CREATE INDEX IF NOT EXISTS idx_buyer_notif_order   ON buyer_notifications(order_id);

-- ============================================================
-- RLS Policies
-- ============================================================

ALTER TABLE orders                ENABLE ROW LEVEL SECURITY;
ALTER TABLE rider_notifications   ENABLE ROW LEVEL SECURITY;
ALTER TABLE buyer_rider_messages  ENABLE ROW LEVEL SECURITY;
ALTER TABLE seller_rider_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications         ENABLE ROW LEVEL SECURITY;
ALTER TABLE buyer_notifications   ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS automatically, so backend (sb_admin) always works.
-- Grant full access to authenticated users for their own data:

-- orders: users can read orders they are involved in
DROP POLICY IF EXISTS "users can read own orders" ON orders;
CREATE POLICY "users can read own orders"
  ON orders FOR SELECT TO authenticated
  USING (
    email = auth.jwt() ->> 'email'
    OR seller_email = auth.jwt() ->> 'email'
    OR rider_email  = auth.jwt() ->> 'email'
  );

-- rider_notifications: riders can read/update their own
DROP POLICY IF EXISTS "rider can read own notifications" ON rider_notifications;
CREATE POLICY "rider can read own notifications"
  ON rider_notifications FOR ALL TO authenticated
  USING (rider_email = auth.jwt() ->> 'email');

-- buyer_rider_messages: participants can read
DROP POLICY IF EXISTS "participants can read buyer_rider_messages" ON buyer_rider_messages;
CREATE POLICY "participants can read buyer_rider_messages"
  ON buyer_rider_messages FOR SELECT TO authenticated
  USING (
    sender_email = auth.jwt() ->> 'email'
    OR receiver_email = auth.jwt() ->> 'email'
  );

-- seller_rider_messages: participants can read
DROP POLICY IF EXISTS "participants can read seller_rider_messages" ON seller_rider_messages;
CREATE POLICY "participants can read seller_rider_messages"
  ON seller_rider_messages FOR SELECT TO authenticated
  USING (
    sender_email = auth.jwt() ->> 'email'
    OR receiver_email = auth.jwt() ->> 'email'
  );

-- notifications: sellers can read their own
DROP POLICY IF EXISTS "seller can read own notifications" ON notifications;
CREATE POLICY "seller can read own notifications"
  ON notifications FOR ALL TO authenticated
  USING (seller_email = auth.jwt() ->> 'email');

-- buyer_notifications: buyers can read their own
DROP POLICY IF EXISTS "buyer can read own notifications" ON buyer_notifications;
CREATE POLICY "buyer can read own notifications"
  ON buyer_notifications FOR ALL TO authenticated
  USING (buyer_email = auth.jwt() ->> 'email');

-- ============================================================
-- Rider Withdrawals
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================

CREATE TABLE IF NOT EXISTS rider_withdrawals (
  id            BIGSERIAL    PRIMARY KEY,
  rider_email   TEXT         NOT NULL,
  amount        NUMERIC(10,2) NOT NULL,
  method        TEXT         NOT NULL,   -- 'GCash' | 'Maya' | 'Bank Transfer'
  account_name  TEXT         NOT NULL,
  account_number TEXT        NOT NULL,
  status        TEXT         DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected'
  note          TEXT,
  requested_at  TIMESTAMPTZ  DEFAULT NOW(),
  processed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rider_withdrawals_email  ON rider_withdrawals(rider_email);
CREATE INDEX IF NOT EXISTS idx_rider_withdrawals_status ON rider_withdrawals(status);

ALTER TABLE rider_withdrawals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "rider can manage own withdrawals" ON rider_withdrawals;
CREATE POLICY "rider can manage own withdrawals"
  ON rider_withdrawals FOR ALL TO authenticated
  USING (rider_email = auth.jwt() ->> 'email')
  WITH CHECK (rider_email = auth.jwt() ->> 'email');
