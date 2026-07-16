export type AgentStatus = "started" | "working" | "waiting_for_input" | "finished" | "error" | "stale";

export type Agent = {
  agent_id: string;
  session_id: string;
  status: AgentStatus;
  last_event_type: string;
  last_event_at: string;
  host_id: string;
  working_dir: string;
  harness: string;
  model: string | null;
  chat_title: string | null;
  last_message: string | null;
  location: { kind: "tmux"; pane: string } | { kind: "firefox"; window_tab: string; url: string; title: string };
};

export type Rule = {
  rule_id: string;
  name: string;
  enabled: boolean;
  match: RuleMatchers;
  actions: NotificationAction[];
};

export type RuleMatchers = {
  type: string | null; text: string | null; agent_id: string | null;
  agent_type: string | null; host_id: string | null; session_id: string | null;
  status: string | null; working_dir: string | null; model: string | null;
  chat_title: string | null;
};

export type NotificationAction =
  | { type: "native"; hostname_regex: string }
  | { type: "webpush"; client_ids_regex: string }
  | { type: "ntfy"; topic: string; server: string };
