-- =====================================================================
-- Sistema Mercadinho — Schema PostgreSQL
-- Use: psql "$DATABASE_URL" -f schema.sql
-- Idempotente: pode ser rodado múltiplas vezes sem quebrar.
-- =====================================================================

-- Extensões úteis
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid() se precisar

-- =====================================================================
-- USERS & AUTH
-- =====================================================================

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('ADMIN', 'OPERADOR', 'GERENCIAL');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id           SERIAL PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE,
    full_name    TEXT NOT NULL,
    email        TEXT UNIQUE,
    password_hash TEXT NOT NULL,           -- bcrypt hash
    role         user_role NOT NULL DEFAULT 'OPERADOR',
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);

-- =====================================================================
-- DOMAIN TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS consignors (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT,
    address    TEXT,
    pix_key    TEXT,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sellers (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id                 SERIAL PRIMARY KEY,
    name               TEXT NOT NULL,
    sku                TEXT NOT NULL UNIQUE,
    price              NUMERIC(12,2) NOT NULL CHECK (price >= 0),
    unit_cost          NUMERIC(12,2) CHECK (unit_cost IS NULL OR unit_cost >= 0),
    supplier_unit_cost NUMERIC(12,2) CHECK (supplier_unit_cost IS NULL OR supplier_unit_cost >= 0),
    stock              INTEGER NOT NULL DEFAULT 0,
    min_stock          INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    is_consigned       BOOLEAN NOT NULL DEFAULT FALSE,
    consignor_id       INTEGER REFERENCES consignors(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_name   ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_sku    ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_active ON products(active);

DO $$ BEGIN
    CREATE TYPE movement_type AS ENUM ('IN', 'OUT', 'ADJUST');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS movements (
    id         SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    type       movement_type NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    qty        INTEGER NOT NULL,
    note       TEXT,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_movements_created ON movements(created_at);
CREATE INDEX IF NOT EXISTS idx_movements_product ON movements(product_id);

DO $$ BEGIN
    CREATE TYPE payment_method AS ENUM ('Dinheiro', 'PIX', 'Crédito', 'Débito', 'Fiado');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE payment_status AS ENUM ('PAGO', 'ABERTO');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS sales (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    seller_id       INTEGER REFERENCES sellers(id) ON DELETE SET NULL,
    buyer_name      TEXT,
    buyer_team      TEXT,
    payment_method  payment_method NOT NULL,
    payment_status  payment_status NOT NULL DEFAULT 'PAGO',
    total           NUMERIC(12,2) NOT NULL CHECK (total >= 0),
    paid            NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (paid >= 0),
    change_amount   NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (change_amount >= 0),
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    paid_at         TIMESTAMPTZ,
    paid_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_created ON sales(created_at);
CREATE INDEX IF NOT EXISTS idx_sales_status  ON sales(payment_status);
CREATE INDEX IF NOT EXISTS idx_sales_seller  ON sales(seller_id);

CREATE TABLE IF NOT EXISTS sale_items (
    id          SERIAL PRIMARY KEY,
    sale_id     INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    qty         INTEGER NOT NULL CHECK (qty > 0),
    unit_price  NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    unit_cost   NUMERIC(12,2),
    line_total  NUMERIC(12,2) NOT NULL CHECK (line_total >= 0)
);

CREATE INDEX IF NOT EXISTS idx_sale_items_sale    ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_product ON sale_items(product_id);

-- =====================================================================
-- AUDIT LOG
-- =====================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username    TEXT,                      -- snapshot caso user seja deletado
    action      TEXT NOT NULL,             -- ex: SALE_CREATE, PRODUCT_UPDATE
    entity      TEXT,                      -- ex: sale, product
    entity_id   INTEGER,
    details     JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_user    ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity  ON audit_log(entity, entity_id);
