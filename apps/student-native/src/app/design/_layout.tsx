import { Stack } from 'expo-router';
import React from 'react';

/** Isolated design previews (Design-00). Fixture data only; see src/design/preview. */
export default function DesignLayout() {
  return <Stack screenOptions={{ headerShown: false, animation: 'none' }} />;
}
