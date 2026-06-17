export function isImeComposing(
  event: { nativeEvent: KeyboardEvent & { isComposing?: boolean } },
  fallback = false,
) {
  const nativeEvent = event.nativeEvent;
  return Boolean(fallback || nativeEvent.isComposing || nativeEvent.keyCode === 229);
}
