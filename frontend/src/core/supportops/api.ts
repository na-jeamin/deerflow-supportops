import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type SupportActionStatus =
  | "pending_approval"
  | "approved"
  | "rejected"
  | "succeeded";

export type SupportAction = {
  action_id: string;
  order_id: string;
  reason: string;
  status: SupportActionStatus;
  revision: number;
  created_at: string;
  ticket_id: string | null;
  ticket_created_at: string | null;
};

const JSON_HEADERS = { "Content-Type": "application/json" };

function actionsUrl(path = "") {
  return `${getBackendBaseURL()}/api/supportops/actions${path}`;
}

async function sendAction<T>(
  path: string,
  body: unknown,
  fallback: string,
): Promise<T> {
  const response = await fetch(actionsUrl(path), {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  if (!response.ok) await throwGatewayApiError(response, fallback);
  return response.json();
}

export async function listSupportActions(): Promise<SupportAction[]> {
  const response = await fetch(actionsUrl());
  if (!response.ok) {
    await throwGatewayApiError(response, "Failed to load support requests");
  }
  return response.json();
}

export async function reviseSupportAction(
  action: SupportAction,
  reason: string,
): Promise<SupportAction> {
  return sendAction(
    `/${encodeURIComponent(action.action_id)}/revision`,
    { reason, revision: action.revision },
    "Failed to update support request",
  );
}

export async function decideSupportAction(
  action: SupportAction,
  decision: "approve" | "reject",
): Promise<SupportAction> {
  return sendAction(
    `/${encodeURIComponent(action.action_id)}/decision`,
    {
      order_id: action.order_id,
      reason: action.reason,
      decision,
      revision: action.revision,
    },
    "Failed to update support request decision",
  );
}

export type SupportTicket = {
  status: "succeeded";
  ticket_id: string;
  action_id: string;
  order_id: string;
  reason: string;
  revision: number;
  created_at: string;
};

export async function executeSupportAction(
  action: SupportAction,
): Promise<SupportTicket> {
  return sendAction(
    `/${encodeURIComponent(action.action_id)}/execute`,
    { revision: action.revision },
    "Failed to create support ticket",
  );
}
