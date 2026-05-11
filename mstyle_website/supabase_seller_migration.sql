-- ============================================================
-- Seller tables migration for Supabase
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================
-- Covers: products, reviews, promotions, promotion_products,
--         promotion_categories, promotion_usage, variant_inventory,
--         notifications (seller), seller_rider_messages,
--         buyer_seller_messages, conversations, order_issues
-- ============================================================

-- ── 1. products ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
  id                  BIGSERIAL     PRIMARY KEY,
  name                TEXT          NOT NULL,
  category            TEXT          NOT NULL,
  description         TEXT,
  variations          TEXT,
  price               NUMERIC(10,2),
  image               TEXT,
  quantity            INT           DEFAULT 0,
  low_stock_threshold INT           DEFAULT 5,
  seller_email        TEXT          NOT NULL,
  sold                INT           DEFAULT 0,
  rating              NUMERIC(3,2),
  image_colors        TEXT,
  sizes               TEXT,
  sku                 TEXT,
  flag_reason         TEXT,
  flagged_at          TIMESTAMPTZ,
  flagged_by          TEXT,
  is_active           BOOLEAN       DEFAULT TRUE,
  is_flagged          BOOLEAN       DEFAULT FALSE,
  created_at          TIMESTAMPTZ   DEFAULT NOW(),
  updated_at          TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_seller_email ON products(seller_email);
CREATE INDEX IF NOT EXISTS idx_products_category     ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_is_active    ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_flagged_at   ON products(flagged_at);

-- ── 2. reviews ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reviews (
  id              BIGSERIAL   PRIMARY KEY,
  order_id        BIGINT      NOT NULL,
  product_id      BIGINT      NOT NULL,
  customer_email  TEXT        NOT NULL,
  seller_email    TEXT        NOT NULL,
  rating          INT         NOT NULL CHECK (rating >= 1 AND rating <= 5),
  review_text     TEXT        NOT NULL,
  review_images   TEXT,
  seller_response TEXT,
  response_date   TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Add review_images column if it doesn't exist yet (safe to run multiple times)
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS review_images TEXT;

CREATE INDEX IF NOT EXISTS idx_reviews_order_customer ON reviews(order_id, customer_email);
CREATE INDEX IF NOT EXISTS idx_reviews_product_id     ON reviews(product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_seller_email   ON reviews(seller_email);
CREATE INDEX IF NOT EXISTS idx_reviews_rating         ON reviews(rating);

-- ── 3. promotions ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS promotions (
  id                      BIGSERIAL   PRIMARY KEY,
  name                    TEXT        NOT NULL,
  code                    TEXT        NOT NULL,
  seller_email            TEXT        NOT NULL,
  type                    TEXT        NOT NULL,   -- 'percentage' | 'fixed' | 'buy_one_get_one' | 'free_shipping'
  discount_value          NUMERIC(10,2),
  max_discount            NUMERIC(10,2),
  min_purchase            NUMERIC(10,2) DEFAULT 0,
  min_quantity            INT           DEFAULT 1,
  usage_limit_per_customer INT,
  total_usage_limit       INT,
  current_usage_count     INT           DEFAULT 0,
  start_date              DATE          NOT NULL,
  start_time              TIME          DEFAULT '00:00:00',
  end_date                DATE          NOT NULL,
  end_time                TIME          DEFAULT '23:59:59',
  product_scope           TEXT          DEFAULT 'all',  -- 'all' | 'specific' | 'category'
  is_active               BOOLEAN       DEFAULT TRUE,
  created_at              TIMESTAMPTZ   DEFAULT NOW(),
  updated_at              TIMESTAMPTZ   DEFAULT NOW(),
  UNIQUE (seller_email, code)
);

CREATE INDEX IF NOT EXISTS idx_promotions_seller_email  ON promotions(seller_email);
CREATE INDEX IF NOT EXISTS idx_promotions_code          ON promotions(code);
CREATE INDEX IF NOT EXISTS idx_promotions_active_dates  ON promotions(is_active, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_promotions_type          ON promotions(type);
CREATE INDEX IF NOT EXISTS idx_promotions_product_scope ON promotions(product_scope);

-- ── 4. promotion_products ────────────────────────────────────
CREATE TABLE IF NOT EXISTS promotion_products (
  id           BIGSERIAL   PRIMARY KEY,
  promotion_id BIGINT      NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
  product_id   BIGINT      NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (promotion_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_promo_products_promo_id   ON promotion_products(promotion_id);
CREATE INDEX IF NOT EXISTS idx_promo_products_product_id ON promotion_products(product_id);

-- ── 5. promotion_categories ──────────────────────────────────
CREATE TABLE IF NOT EXISTS promotion_categories (
  id           BIGSERIAL   PRIMARY KEY,
  promotion_id BIGINT      NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
  category     TEXT        NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (promotion_id, category)
);

CREATE INDEX IF NOT EXISTS idx_promo_categories_promo_id ON promotion_categories(promotion_id);
CREATE INDEX IF NOT EXISTS idx_promo_categories_category ON promotion_categories(category);

-- ── 6. promotion_usage ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS promotion_usage (
  id               BIGSERIAL     PRIMARY KEY,
  promotion_id     BIGINT        NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
  order_id         BIGINT        NOT NULL,
  customer_email   TEXT          NOT NULL,
  product_id       TEXT,
  discount_applied NUMERIC(10,2) NOT NULL,
  used_at          TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_promo_usage_promo_id       ON promotion_usage(promotion_id);
CREATE INDEX IF NOT EXISTS idx_promo_usage_order_id       ON promotion_usage(order_id);
CREATE INDEX IF NOT EXISTS idx_promo_usage_customer_email ON promotion_usage(customer_email);
CREATE INDEX IF NOT EXISTS idx_promo_usage_product_id     ON promotion_usage(product_id);
CREATE INDEX IF NOT EXISTS idx_promo_usage_used_at        ON promotion_usage(used_at);

-- ── 7. variant_inventory ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS variant_inventory (
  id                  BIGSERIAL   PRIMARY KEY,
  product_id          BIGINT      NOT NULL,
  color               TEXT        NOT NULL,
  size                TEXT        NOT NULL,
  stock_quantity      INT         NOT NULL DEFAULT 0,
  low_stock_threshold INT         DEFAULT 5,
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_variant_inv_product_id ON variant_inventory(product_id);
CREATE INDEX IF NOT EXISTS idx_variant_inv_color      ON variant_inventory(color);
CREATE INDEX IF NOT EXISTS idx_variant_inv_size       ON variant_inventory(size);

-- Unique constraint required for upsert on_conflict to work
ALTER TABLE variant_inventory
  DROP CONSTRAINT IF EXISTS unique_variant,
  ADD CONSTRAINT unique_variant UNIQUE (product_id, color, size);

-- ── 8. notifications (seller) ────────────────────────────────
-- Already created in supabase_rider_migration.sql — safe to re-run with IF NOT EXISTS
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

-- ── 9. seller_rider_messages ─────────────────────────────────
-- Already created in supabase_rider_migration.sql — safe to re-run
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

-- ── 10. buyer_seller_messages ────────────────────────────────
CREATE TABLE IF NOT EXISTS buyer_seller_messages (
  id              BIGSERIAL   PRIMARY KEY,
  conversation_id TEXT        NOT NULL,
  sender_email    TEXT        NOT NULL,
  receiver_email  TEXT        NOT NULL,
  sender_type     TEXT        NOT NULL,   -- 'buyer' | 'seller'
  message_text    TEXT        NOT NULL,
  is_read         BOOLEAN     DEFAULT FALSE,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bsm_conversation_id ON buyer_seller_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_bsm_sender          ON buyer_seller_messages(sender_email);
CREATE INDEX IF NOT EXISTS idx_bsm_receiver        ON buyer_seller_messages(receiver_email);
CREATE INDEX IF NOT EXISTS idx_bsm_is_read         ON buyer_seller_messages(is_read);

-- ── 11. conversations ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
  id              BIGSERIAL   PRIMARY KEY,
  conversation_id TEXT        NOT NULL UNIQUE,
  buyer_email     TEXT        NOT NULL,
  seller_email    TEXT        NOT NULL,
  product_id      BIGINT,
  order_id        BIGINT,
  last_message_at TIMESTAMPTZ DEFAULT NOW(),
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_buyer_email  ON conversations(buyer_email);
CREATE INDEX IF NOT EXISTS idx_conversations_seller_email ON conversations(seller_email);
CREATE INDEX IF NOT EXISTS idx_conversations_product_id   ON conversations(product_id);
CREATE INDEX IF NOT EXISTS idx_conversations_order_id     ON conversations(order_id);

-- ── 12. archive (seller docs in archived_users already handled) ──
-- pending_sellers is defined in supabase_migration.sql.
-- Re-running CREATE TABLE IF NOT EXISTS is safe.
CREATE TABLE IF NOT EXISTS pending_sellers (
  id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  supabase_uid         UUID        NOT NULL UNIQUE,
  email                TEXT        NOT NULL,
  first_name           TEXT,
  last_name            TEXT,
  business_name        TEXT,
  business_type        TEXT,       -- 'individual' | 'business'
  phone                TEXT,
  house_street         TEXT,
  barangay             TEXT,
  city                 TEXT,
  province             TEXT,
  region               TEXT,
  zip_code             TEXT,
  valid_id_path        TEXT,
  dti_path             TEXT,
  bir_path             TEXT,
  business_permit_path TEXT,
  status               TEXT        DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected'
  created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pending_sellers_uid    ON pending_sellers(supabase_uid);
CREATE INDEX IF NOT EXISTS idx_pending_sellers_email  ON pending_sellers(email);
CREATE INDEX IF NOT EXISTS idx_pending_sellers_status ON pending_sellers(status);

-- ── 13. order_issues ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_issues (
  id                     BIGSERIAL   PRIMARY KEY,
  order_id               BIGINT      NOT NULL,
  reporter_role          TEXT        NOT NULL,   -- 'buyer' | 'seller' | 'rider' | 'admin'
  reporter_email         TEXT        NOT NULL,
  reported_against_role  TEXT        NOT NULL DEFAULT 'seller',  -- 'buyer' | 'seller' | 'rider' | 'platform' | 'other'
  reported_against_email TEXT,
  issue_type             TEXT        NOT NULL,
  issue_description      TEXT        NOT NULL,
  status                 TEXT        DEFAULT 'pending',  -- 'pending' | 'in_progress' | 'resolved' | 'closed'
  admin_response         TEXT,
  created_at             TIMESTAMPTZ DEFAULT NOW(),
  updated_at             TIMESTAMPTZ DEFAULT NOW(),
  resolved_at            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_issues_order_id        ON order_issues(order_id);
CREATE INDEX IF NOT EXISTS idx_issues_reporter_role   ON order_issues(reporter_role);
CREATE INDEX IF NOT EXISTS idx_issues_reporter_email  ON order_issues(reporter_email);
CREATE INDEX IF NOT EXISTS idx_issues_against_role    ON order_issues(reported_against_role);
CREATE INDEX IF NOT EXISTS idx_issues_status          ON order_issues(status);
CREATE INDEX IF NOT EXISTS idx_issues_created_at      ON order_issues(created_at);

-- ============================================================
-- RLS Policies
-- ============================================================

ALTER TABLE products              ENABLE ROW LEVEL SECURITY;
ALTER TABLE reviews               ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotions            ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_products    ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_categories  ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_usage       ENABLE ROW LEVEL SECURITY;
ALTER TABLE variant_inventory     ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications         ENABLE ROW LEVEL SECURITY;
ALTER TABLE seller_rider_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE buyer_seller_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations         ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_issues          ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_sellers       ENABLE ROW LEVEL SECURITY;

-- products: anyone can read active/unflagged products; sellers manage their own
DROP POLICY IF EXISTS "anyone can read active products" ON products;
CREATE POLICY "anyone can read active products"
  ON products FOR SELECT TO anon, authenticated
  USING (is_active = TRUE AND (flagged_at IS NULL OR flagged_at::TEXT = ''));

DROP POLICY IF EXISTS "seller can manage own products" ON products;
CREATE POLICY "seller can manage own products"
  ON products FOR ALL TO authenticated
  USING (seller_email = auth.jwt() ->> 'email')
  WITH CHECK (seller_email = auth.jwt() ->> 'email');

-- reviews: anyone can read; buyers can insert their own
DROP POLICY IF EXISTS "anyone can read reviews" ON reviews;
CREATE POLICY "anyone can read reviews"
  ON reviews FOR SELECT TO anon, authenticated
  USING (TRUE);

DROP POLICY IF EXISTS "buyer can insert own review" ON reviews;
CREATE POLICY "buyer can insert own review"
  ON reviews FOR INSERT TO authenticated
  WITH CHECK (customer_email = auth.jwt() ->> 'email');

DROP POLICY IF EXISTS "seller can update own review response" ON reviews;
CREATE POLICY "seller can update own review response"
  ON reviews FOR UPDATE TO authenticated
  USING (seller_email = auth.jwt() ->> 'email');

-- promotions: sellers manage their own; anyone can read active ones
DROP POLICY IF EXISTS "anyone can read active promotions" ON promotions;
CREATE POLICY "anyone can read active promotions"
  ON promotions FOR SELECT TO anon, authenticated
  USING (is_active = TRUE);

DROP POLICY IF EXISTS "seller can manage own promotions" ON promotions;
CREATE POLICY "seller can manage own promotions"
  ON promotions FOR ALL TO authenticated
  USING (seller_email = auth.jwt() ->> 'email')
  WITH CHECK (seller_email = auth.jwt() ->> 'email');

-- promotion_products / promotion_categories: readable by all, managed by service role
DROP POLICY IF EXISTS "anyone can read promotion_products" ON promotion_products;
CREATE POLICY "anyone can read promotion_products"
  ON promotion_products FOR SELECT TO anon, authenticated
  USING (TRUE);

DROP POLICY IF EXISTS "anyone can read promotion_categories" ON promotion_categories;
CREATE POLICY "anyone can read promotion_categories"
  ON promotion_categories FOR SELECT TO anon, authenticated
  USING (TRUE);

-- promotion_usage: customers can read their own usage
DROP POLICY IF EXISTS "customer can read own promotion usage" ON promotion_usage;
CREATE POLICY "customer can read own promotion usage"
  ON promotion_usage FOR SELECT TO authenticated
  USING (customer_email = auth.jwt() ->> 'email');

-- variant_inventory: anyone can read; sellers manage their own via service role
DROP POLICY IF EXISTS "anyone can read variant_inventory" ON variant_inventory;
CREATE POLICY "anyone can read variant_inventory"
  ON variant_inventory FOR SELECT TO anon, authenticated
  USING (TRUE);

-- notifications: sellers can read/manage their own
DROP POLICY IF EXISTS "seller can read own notifications" ON notifications;
CREATE POLICY "seller can read own notifications"
  ON notifications FOR ALL TO authenticated
  USING (seller_email = auth.jwt() ->> 'email');

-- seller_rider_messages: participants can read
DROP POLICY IF EXISTS "participants can read seller_rider_messages" ON seller_rider_messages;
CREATE POLICY "participants can read seller_rider_messages"
  ON seller_rider_messages FOR SELECT TO authenticated
  USING (
    sender_email   = auth.jwt() ->> 'email'
    OR receiver_email = auth.jwt() ->> 'email'
  );

-- buyer_seller_messages: participants can read
DROP POLICY IF EXISTS "participants can read buyer_seller_messages" ON buyer_seller_messages;
CREATE POLICY "participants can read buyer_seller_messages"
  ON buyer_seller_messages FOR SELECT TO authenticated
  USING (
    sender_email   = auth.jwt() ->> 'email'
    OR receiver_email = auth.jwt() ->> 'email'
  );

-- conversations: participants can read their own
DROP POLICY IF EXISTS "participants can read conversations" ON conversations;
CREATE POLICY "participants can read conversations"
  ON conversations FOR SELECT TO authenticated
  USING (
    buyer_email  = auth.jwt() ->> 'email'
    OR seller_email = auth.jwt() ->> 'email'
  );

-- order_issues: reporter can read their own; service role handles admin access
DROP POLICY IF EXISTS "reporter can read own issues" ON order_issues;
CREATE POLICY "reporter can read own issues"
  ON order_issues FOR SELECT TO authenticated
  USING (reporter_email = auth.jwt() ->> 'email');

DROP POLICY IF EXISTS "reporter can insert own issue" ON order_issues;
CREATE POLICY "reporter can insert own issue"
  ON order_issues FOR INSERT TO authenticated
  WITH CHECK (reporter_email = auth.jwt() ->> 'email');

-- pending_sellers: already covered by supabase_migration.sql policies.
-- Re-applying here is safe (DROP IF EXISTS + CREATE).
DROP POLICY IF EXISTS "seller can insert own pending record"  ON pending_sellers;
DROP POLICY IF EXISTS "seller can update own pending record"  ON pending_sellers;
DROP POLICY IF EXISTS "anon can check own pending seller status" ON pending_sellers;

CREATE POLICY "anon can check own pending seller status"
  ON pending_sellers FOR SELECT TO anon, authenticated
  USING (TRUE);

CREATE POLICY "seller can insert own pending record"
  ON pending_sellers FOR INSERT TO authenticated
  WITH CHECK (supabase_uid = auth.uid());

CREATE POLICY "seller can update own pending record"
  ON pending_sellers FOR UPDATE TO authenticated
  USING (supabase_uid = auth.uid())
  WITH CHECK (supabase_uid = auth.uid());

-- ============================================================
-- Storage: review-images bucket
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================

-- Create the public bucket for review images (safe to re-run)
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'review-images',
  'review-images',
  TRUE,
  5242880,   -- 5 MB per file
  ARRAY['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO UPDATE
  SET public             = TRUE,
      file_size_limit    = 5242880,
      allowed_mime_types = ARRAY['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif'];

-- Allow anyone to read (view) review images
DROP POLICY IF EXISTS "review images are publicly readable" ON storage.objects;
CREATE POLICY "review images are publicly readable"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'review-images');

-- Allow authenticated users to upload review images
DROP POLICY IF EXISTS "authenticated users can upload review images" ON storage.objects;
CREATE POLICY "authenticated users can upload review images"
  ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (bucket_id = 'review-images');

-- Allow service role to upload (used by the Flutter app via REST)
DROP POLICY IF EXISTS "service role can upload review images" ON storage.objects;
CREATE POLICY "service role can upload review images"
  ON storage.objects FOR INSERT TO service_role
  WITH CHECK (bucket_id = 'review-images');

-- Allow service role to upsert (x-upsert: true header)
DROP POLICY IF EXISTS "service role can upsert review images" ON storage.objects;
CREATE POLICY "service role can upsert review images"
  ON storage.objects FOR UPDATE TO service_role
  USING (bucket_id = 'review-images');
