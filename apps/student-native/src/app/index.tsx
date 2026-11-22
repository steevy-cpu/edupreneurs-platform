import { Redirect } from 'expo-router';
import React from 'react';

import { useApp } from '../ui/AppContext';

export default function Index() {
  const { session } = useApp();
  return <Redirect href={session ? '/home' : '/sign-in'} />;
}
