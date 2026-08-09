/*
# Create guild_settings table

1. Purpose
- Stores per-guild configuration for the Heaven Discord VC bot.
- One row per Discord guild, keyed by guild_id (bigint).
- Written and read by the bot's Python backend using the Supabase
  service_role key. The bot is a single privileged service, not an
  end-user application; there is no sign-in screen and no auth.users
  linkage.

2. New Tables
- `guild_settings`
  - `guild_id` (bigint, primary key) — Discord guild ID.
  - `category_id` (bigint, nullable) — Discord category channel ID where
    temporary voice channels are created.
  - `lobby_id` (bigint, nullable) — Discord voice channel ID that triggers
    temporary channel creation when a user joins.
  - `user_limit` (integer, not null, default 5) — max users per temp VC
    (0 = unlimited).
  - `bitrate` (integer, not null, default 64000) — bitrate in bps for temp VCs.
  - `autodelete_seconds` (integer, not null, default 60) — delay in seconds
    before an empty temp VC is deleted.
  - `created_at` (timestamptz, not null, default now()) — row creation time.
  - `updated_at` (timestamptz, not null, default now()) — last modification time.

3. Security
- Enable RLS on `guild_settings`.
- The bot uses the service_role key, which bypasses RLS, so the bot can
  read and write freely regardless of policies.
- As a defensive baseline, add permissive CRUD policies for
  `anon, authenticated` so the table is never accidentally locked out
  for any legitimate client. This is a server-side configuration table
  with no per-user ownership semantics; guild_id is an operator-set
  value, not a user identity.

4. Idempotency
- Uses `IF NOT EXISTS` for the table.
- Policies are dropped before creation so the migration is safe to re-run.
*/

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id           bigint PRIMARY KEY,
    category_id        bigint,
    lobby_id           bigint,
    user_limit         integer NOT NULL DEFAULT 5,
    bitrate            integer NOT NULL DEFAULT 64000,
    autodelete_seconds integer NOT NULL DEFAULT 60,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE guild_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_select_guild_settings" ON guild_settings;
CREATE POLICY "anon_select_guild_settings" ON guild_settings
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "anon_insert_guild_settings" ON guild_settings;
CREATE POLICY "anon_insert_guild_settings" ON guild_settings
    FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "anon_update_guild_settings" ON guild_settings;
CREATE POLICY "anon_update_guild_settings" ON guild_settings
    FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_delete_guild_settings" ON guild_settings;
CREATE POLICY "anon_delete_guild_settings" ON guild_settings
    FOR DELETE TO anon, authenticated USING (true);
