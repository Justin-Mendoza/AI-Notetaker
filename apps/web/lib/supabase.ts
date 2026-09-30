import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export function makeClient(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  return url && key ? createClient(url, key) : null;
}

export const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
