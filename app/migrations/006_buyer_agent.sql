ALTER TABLE demand_pools
    ADD COLUMN IF NOT EXISTS buyer_agent_reasoning JSONB;

ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS buyer_rank INT;
