-- Migration: Add demand_pool_id to demand_signals
ALTER TABLE public.demand_signals 
ADD COLUMN IF NOT EXISTS demand_pool_id UUID REFERENCES public.demand_pools(id);
