/** Hash-based navigation: #/dashboard/AAPL, #/agent, ... */
export function navigate(path: string) {
  window.location.hash = `#/${path}`;
}
