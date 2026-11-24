"use client";

import {
  ArrowUpRight,
  ClipboardList,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { GatewayApiError } from "@/core/api/errors";
import { useI18n } from "@/core/i18n/hooks";
import {
  decideSupportAction,
  executeSupportAction,
  listSupportActions,
  reviseSupportAction,
  type SupportAction,
} from "@/core/supportops/api";

function statusClass(status: SupportAction["status"]): string {
  if (status === "approved")
    return "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200";
  if (status === "rejected") return "bg-muted text-muted-foreground";
  if (status === "succeeded")
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200";
  return "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200";
}

function formatDate(value: string, locale: string): string {
  const date = new Date(
    value.replace(" ", "T") + (value.endsWith("Z") ? "" : "Z"),
  );
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function statusExplanation(
  status: SupportAction["status"],
  copy: ReturnType<typeof useI18n>["t"]["supportOps"]["messages"],
): string {
  switch (status) {
    case "pending_approval":
      return copy.pendingExplanation;
    case "approved":
      return copy.approvedExplanation;
    case "rejected":
      return copy.rejectedExplanation;
    case "succeeded":
      return copy.succeededExplanation;
  }
}

function errorMessage(
  error: unknown,
  copy: ReturnType<typeof useI18n>["t"]["supportOps"],
): string {
  if (!(error instanceof GatewayApiError)) {
    return error instanceof Error ? error.message : copy.messages.actionFailed;
  }
  switch (error.status) {
    case 403:
      return copy.errors.forbidden;
    case 404:
      return copy.errors.notFound;
    case 409:
      return copy.errors.conflict;
    case 422:
      return copy.errors.invalidRequest;
    default:
      return error.message || copy.messages.actionFailed;
  }
}

export function SupportOpsPage() {
  const { t, locale } = useI18n();
  const copy = t.supportOps;
  const [actions, setActions] = useState<SupportAction[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [reasonDraft, setReasonDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(
    async (preserveSelection = true) => {
      setLoading(true);
      setLoadError(null);
      try {
        const next = await listSupportActions();
        setActions(next);
        setSelectedId((current) =>
          preserveSelection &&
          current &&
          next.some((item) => item.action_id === current)
            ? current
            : (next[0]?.action_id ?? null),
        );
      } catch (error) {
        setLoadError(errorMessage(error, copy));
      } finally {
        setLoading(false);
      }
    },
    [copy],
  );

  useEffect(() => {
    void refresh(false);
  }, [refresh]);

  const selected = useMemo(
    () => actions.find((action) => action.action_id === selectedId) ?? null,
    [actions, selectedId],
  );

  const runAction = async (
    operation: () => Promise<unknown>,
    successMessage: string,
  ) => {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await operation();
      setEditing(false);
      setNotice(successMessage);
      await refresh();
    } catch (error) {
      setActionError(errorMessage(error, copy));
    } finally {
      setBusy(false);
    }
  };

  const beginEdit = () => {
    if (!selected) return;
    setReasonDraft(selected.reason);
    setActionError(null);
    setNotice(null);
    setEditing(true);
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-5 px-4 py-5 sm:px-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex flex-col gap-1">
              <h1 className="text-2xl font-semibold">{copy.title}</h1>
              <p className="text-muted-foreground max-w-3xl text-sm">
                {copy.description}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => void refresh()}
                disabled={loading}
              >
                {loading ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <RefreshCw />
                )}
                {copy.refresh}
              </Button>
              <Button asChild>
                <Link href="/workspace/chats/new">
                  <ArrowUpRight />
                  {copy.createInChat}
                </Link>
              </Button>
            </div>
          </div>

          <p className="text-muted-foreground bg-muted/30 rounded-lg border px-4 py-3 text-sm">
            {copy.createInChatHint}
          </p>

          {notice && (
            <p
              role="status"
              className="text-sm text-emerald-700 dark:text-emerald-300"
            >
              {notice}
            </p>
          )}
          {loadError && (
            <p role="alert" className="text-destructive text-sm">
              {copy.loadFailed}: {loadError}
            </p>
          )}
          {actionError && (
            <p role="alert" className="text-destructive text-sm">
              {copy.messages.actionFailed}: {actionError}
            </p>
          )}

          {loading && actions.length === 0 ? (
            <p
              role="status"
              className="text-muted-foreground flex items-center gap-2 py-10 text-sm"
            >
              <LoaderCircle className="size-4 animate-spin" />
              {copy.loading}
            </p>
          ) : actions.length === 0 ? (
            <div className="text-muted-foreground flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
              <ClipboardList className="size-8" />
              <p>{copy.empty}</p>
              <Button asChild variant="outline">
                <Link href="/workspace/chats/new">{copy.createInChat}</Link>
              </Button>
            </div>
          ) : (
            <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.4fr)]">
              <section
                aria-label={copy.title}
                className="flex min-w-0 flex-col gap-2"
              >
                {actions.map((action) => (
                  <button
                    key={action.action_id}
                    type="button"
                    onClick={() => {
                      setSelectedId(action.action_id);
                      setEditing(false);
                      setActionError(null);
                      setNotice(null);
                    }}
                    aria-pressed={selectedId === action.action_id}
                    className={`hover:bg-muted/50 flex min-w-0 flex-col gap-2 rounded-lg border p-4 text-left transition ${selectedId === action.action_id ? "border-primary bg-muted/40" : ""}`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-medium">{action.order_id}</span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${statusClass(action.status)}`}
                      >
                        {copy.status[action.status]}
                      </span>
                    </span>
                    <span className="text-muted-foreground line-clamp-2 text-sm">
                      {action.reason}
                    </span>
                    <span className="text-muted-foreground text-xs">
                      {copy.fields.revision} {action.revision} ·{" "}
                      {formatDate(action.created_at, locale)}
                    </span>
                  </button>
                ))}
              </section>

              {selected ? (
                <section className="flex min-w-0 flex-col gap-4 rounded-xl border p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-3">
                      <h2 className="text-xl font-semibold">
                        {selected.order_id}
                      </h2>
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs ${statusClass(selected.status)}`}
                      >
                        {copy.status[selected.status]}
                      </span>
                    </div>
                    <span className="text-muted-foreground text-sm">
                      {copy.fields.revision} {selected.revision}
                    </span>
                  </div>

                  <dl className="grid gap-3 text-sm sm:grid-cols-2">
                    <div className="sm:col-span-2">
                      <dt className="text-muted-foreground mb-1">
                        {copy.fields.reason}
                      </dt>
                      <dd className="whitespace-pre-wrap">{selected.reason}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground mb-1">
                        {copy.fields.createdAt}
                      </dt>
                      <dd>{formatDate(selected.created_at, locale)}</dd>
                    </div>
                    {selected.ticket_id && (
                      <>
                        <div>
                          <dt className="text-muted-foreground mb-1">
                            {copy.fields.ticketId}
                          </dt>
                          <dd className="font-mono text-xs break-all">
                            {selected.ticket_id}
                          </dd>
                        </div>
                        {selected.ticket_created_at && (
                          <div>
                            <dt className="text-muted-foreground mb-1">
                              {copy.fields.ticketCreatedAt}
                            </dt>
                            <dd>
                              {formatDate(selected.ticket_created_at, locale)}
                            </dd>
                          </div>
                        )}
                      </>
                    )}
                  </dl>

                  <p className="text-muted-foreground bg-muted/40 rounded-md px-3 py-2 text-sm">
                    {statusExplanation(selected.status, copy.messages)}
                  </p>

                  {editing && selected.status !== "succeeded" ? (
                    <div className="flex flex-col gap-3">
                      <label
                        className="text-sm font-medium"
                        htmlFor="supportops-reason"
                      >
                        {copy.fields.reason}
                      </label>
                      <Textarea
                        id="supportops-reason"
                        value={reasonDraft}
                        onChange={(event) => setReasonDraft(event.target.value)}
                        maxLength={300}
                        rows={3}
                        placeholder={copy.messages.reasonPlaceholder}
                        disabled={busy}
                      />
                      <div className="flex flex-wrap gap-2">
                        <Button
                          onClick={() =>
                            void runAction(
                              () => reviseSupportAction(selected, reasonDraft),
                              copy.messages.reasonUpdated,
                            )
                          }
                          disabled={
                            busy ||
                            !reasonDraft.trim() ||
                            reasonDraft.trim() === selected.reason
                          }
                        >
                          {busy && <LoaderCircle className="animate-spin" />}
                          {copy.actions.saveReason}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => setEditing(false)}
                          disabled={busy}
                        >
                          {copy.actions.cancel}
                        </Button>
                      </div>
                    </div>
                  ) : selected.status !== "succeeded" ? (
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        onClick={beginEdit}
                        disabled={busy}
                      >
                        {copy.actions.editReason}
                      </Button>
                      {selected.status === "pending_approval" && (
                        <>
                          <Button
                            onClick={() =>
                              void runAction(
                                () => decideSupportAction(selected, "approve"),
                                copy.messages.approved,
                              )
                            }
                            disabled={busy}
                          >
                            {copy.actions.approve}
                          </Button>
                          <Button
                            variant="destructive"
                            onClick={() =>
                              void runAction(
                                () => decideSupportAction(selected, "reject"),
                                copy.messages.rejected,
                              )
                            }
                            disabled={busy}
                          >
                            {copy.actions.reject}
                          </Button>
                        </>
                      )}
                      {selected.status === "approved" && (
                        <Button
                          onClick={() =>
                            void runAction(
                              () => executeSupportAction(selected),
                              copy.messages.ticketCreated,
                            )
                          }
                          disabled={busy}
                        >
                          {busy && <LoaderCircle className="animate-spin" />}
                          {copy.actions.createTicket}
                        </Button>
                      )}
                    </div>
                  ) : null}
                </section>
              ) : (
                <p className="text-muted-foreground rounded-xl border border-dashed p-8 text-center text-sm">
                  {copy.selectHint}
                </p>
              )}
            </div>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
