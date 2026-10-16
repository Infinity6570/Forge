export const distanceFromBottom = (el: { scrollHeight: number; scrollTop: number; clientHeight: number }) =>
  Math.max(0, el.scrollHeight - el.scrollTop - el.clientHeight);

export const prependedScrollTop = (previous: { height: number; top: number }, newHeight: number) =>
  Math.max(0, previous.top + newHeight - previous.height);
