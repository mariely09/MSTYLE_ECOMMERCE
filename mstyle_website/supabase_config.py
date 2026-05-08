"""
Supabase configuration for MStyle web app.
Shared with the mobile app — same project, same database.
"""
import os
from supabase import create_client, Client

SUPABASE_URL  = os.environ.get(
    'SUPABASE_URL',
    'https://vydcnhmgqovketjqvpoe.supabase.co'
)
SUPABASE_ANON = os.environ.get(
    'SUPABASE_ANON_KEY',
    (
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'
        '.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ5ZGNuaG1ncW92a2V0anF2cG9lIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYyMjc4MDMsImV4cCI6MjA5MTgwMzgwM30'
        '.wMFqPcuq_l19zr61-BhRUtGWJyiKa0Rq5300tGntiyE'
    )
)

# Service role key — bypasses Row Level Security for admin operations.
# Set SUPABASE_SERVICE_ROLE_KEY as an environment variable in Railway.
# IMPORTANT: Keep this secret, never expose it to the browser/client.
SUPABASE_SERVICE_ROLE = os.environ.get(
    'SUPABASE_SERVICE_ROLE_KEY',
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ5ZGNuaG1ncW92a2V0anF2cG9lIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NjIyNzgwMywiZXhwIjoyMDkxODAzODAzfQ.N7gBt1F2bLulJkD2Uh1nXaTvLkV2fiEAFvnN3qVLYAY'
)

# Default anon client (for auth operations)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON)

# Admin client — uses service role key, bypasses RLS.
try:
    supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
except Exception:
    supabase_admin = supabase
