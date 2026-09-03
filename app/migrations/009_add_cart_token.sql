ALTER TABLE carts
    ADD COLUMN IF NOT EXISTS cart_token TEXT;

CREATE INDEX IF NOT EXISTS idx_carts_cart_token ON carts(cart_token);
