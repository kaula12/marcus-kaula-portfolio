-- ============================================================================
-- Marcus Kaula Portfolio CMS — Supabase PostgreSQL + Storage Setup Script
-- Paste and run this entire script in your Supabase SQL Editor.
-- ============================================================================

-- 1. Create the single-row JSONB state table for portfolio content
CREATE TABLE IF NOT EXISTS public.portfolio_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Automatically keep updated_at fresh on every update
CREATE OR REPLACE FUNCTION public.set_portfolio_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_portfolio_state_updated_at ON public.portfolio_state;
CREATE TRIGGER trg_portfolio_state_updated_at
BEFORE UPDATE ON public.portfolio_state
FOR EACH ROW
EXECUTE FUNCTION public.set_portfolio_updated_at();

-- 3. Enable Row Level Security (RLS) on portfolio_state
-- IMPORTANT: We intentionally leave NO public/anon policies on this table.
-- Your FastAPI backend accesses it via SUPABASE_SERVICE_ROLE_KEY (which bypasses RLS)
-- and strips profile.passcode before returning public data via GET /api/portfolio.
ALTER TABLE public.portfolio_state ENABLE ROW LEVEL SECURITY;

-- 4. Create the public Storage bucket for images, videos, gallery photos & CV PDFs
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'portfolio-media',
    'portfolio-media',
    TRUE,
    52428800, -- 50 MB max per file (Supabase Free Tier limit)
    ARRAY[
        'image/png',
        'image/jpeg',
        'image/webp',
        'image/gif',
        'video/mp4',
        'video/webm',
        'video/quicktime',
        'application/pdf'
    ]
)
ON CONFLICT (id) DO UPDATE SET
    public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- 5. Storage RLS policy: allow anyone to VIEW media in portfolio-media
-- Uploads and deletes are handled exclusively by your FastAPI backend using
-- SUPABASE_SERVICE_ROLE_KEY after verifying your private Admin Studio passcode.
DROP POLICY IF EXISTS "Public read access for portfolio-media" ON storage.objects;
CREATE POLICY "Public read access for portfolio-media"
ON storage.objects
FOR SELECT
USING (bucket_id = 'portfolio-media');
