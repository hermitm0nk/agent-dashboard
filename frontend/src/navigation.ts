export type DashboardLocation = {
  screen: "agents" | "rules";
  agentId: string;
};

export function apiUrl(path: string, base = document.baseURI): string {
  return new URL(path.replace(/^\/+/, ""), base).toString();
}

export function parseDashboardLocation(search: string): DashboardLocation {
  const parameters = new URLSearchParams(search);
  if (parameters.get("view") === "rules") return { screen: "rules", agentId: "" };
  return { screen: "agents", agentId: parameters.get("agent") ?? "" };
}

export function dashboardUrl(
  pathname: string,
  location: DashboardLocation,
  hash = "",
): string {
  const parameters = new URLSearchParams();
  if (location.screen === "rules") parameters.set("view", "rules");
  if (location.screen === "agents" && location.agentId) {
    parameters.set("agent", location.agentId);
  }
  const search = parameters.toString();
  return `${pathname}${search ? `?${search}` : ""}${hash}`;
}
