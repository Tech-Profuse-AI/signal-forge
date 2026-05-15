const HTTP_URL_PATTERN = /^https?:\/\//i;

export function canOpenUrl(url) {
  return HTTP_URL_PATTERN.test(String(url || '').trim());
}

export function openExternalUrl(url) {
  const value = String(url || '').trim();
  if (!canOpenUrl(value)) return false;

  const openedWindow = window.open(value, '_blank', 'noopener,noreferrer');
  if (openedWindow) {
    openedWindow.opener = null;
  }

  return Boolean(openedWindow);
}
