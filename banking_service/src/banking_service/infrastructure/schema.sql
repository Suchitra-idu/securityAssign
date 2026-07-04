CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    account_number BYTEA NOT NULL,
    balance_minor BYTEA NOT NULL,
    card_number BYTEA NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'frozen')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS accounts_owner_id_idx ON accounts(owner_id);

CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY,
    from_account_id UUID NOT NULL REFERENCES accounts(id),
    to_account_id UUID NOT NULL REFERENCES accounts(id),
    amount_minor BIGINT NOT NULL,
    signed_at BIGINT NOT NULL,
    signature BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS transactions_from_idx ON transactions(from_account_id);
CREATE INDEX IF NOT EXISTS transactions_to_idx ON transactions(to_account_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event JSONB NOT NULL,
    prev_hash BYTEA NOT NULL,
    hash BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
