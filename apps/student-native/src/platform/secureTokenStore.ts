import * as SecureStore from 'expo-secure-store';

import type { StoredSession, TokenStore } from '../core/auth/session';

const KEY = 'edu.session.v1';
const OPTIONS: SecureStore.SecureStoreOptions = {
  // Readable after the first unlock (so sync can run when the app returns to the
  // foreground) and never copied to another device through a backup.
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
};

/**
 * Credentials live ONLY here: iOS Keychain / Android Keystore-encrypted storage.
 * They are never written to SQLite, logs or AsyncStorage.
 */
export const secureTokenStore: TokenStore = {
  async load(): Promise<StoredSession | null> {
    const raw = await SecureStore.getItemAsync(KEY, OPTIONS);
    if (!raw) return null;
    try {
      const value = JSON.parse(raw) as StoredSession;
      return typeof value.userId === 'string' ? value : null;
    } catch {
      return null;
    }
  },
  async save(session: StoredSession): Promise<void> {
    await SecureStore.setItemAsync(KEY, JSON.stringify(session), OPTIONS);
  },
  async clear(): Promise<void> {
    await SecureStore.deleteItemAsync(KEY, OPTIONS);
  },
};
