export function redirectLegacyHash(hash: string, replace: (path: string) => void) {
  const route = hash.replace(/^#/, '');
  if (route === 'projects' || route === 'trash' || route.startsWith('project/') ||
      (route.startsWith('episode/') && ['edit', 'review'].includes(route.split('/')[2]))) {
    replace(`/${route}`);
  }
}
