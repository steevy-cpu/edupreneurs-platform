/**
 * Build-time configuration. Values come from `.env.local` (git-ignored, written
 * by `make mobile-env` in the repository root) through Expo's EXPO_PUBLIC_*
 * mechanism. None of them is a secret: the publishable key only identifies the
 * Supabase project, and the URLs are public endpoints.
 */
export interface AppConfig {
  apiUrl: string;
  supabaseUrl: string;
  supabasePublishableKey: string;
}

export function loadConfig(): AppConfig {
  const apiUrl = process.env.EXPO_PUBLIC_API_URL;
  const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL;
  const supabasePublishableKey = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!apiUrl || !supabaseUrl || !supabasePublishableKey) {
    throw new Error(
      'Missing configuration. Run `make mobile-env` in the repository root, then restart the bundler.',
    );
  }
  return { apiUrl, supabaseUrl, supabasePublishableKey };
}
