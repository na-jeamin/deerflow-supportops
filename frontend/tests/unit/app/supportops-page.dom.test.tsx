import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren, ReactNode } from "react";

const mocks = rs.hoisted(() => ({
  list: rs.fn(),
  revise: rs.fn(),
  decide: rs.fn(),
  execute: rs.fn(),
}));

rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: { href: string; children: ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: PropsWithChildren) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => <div />,
  WorkspaceBody: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));

rs.mock("@/core/supportops/api", () => ({
  listSupportActions: mocks.list,
  reviseSupportAction: mocks.revise,
  decideSupportAction: mocks.decide,
  executeSupportAction: mocks.execute,
}));

import { SupportOpsPage } from "@/components/workspace/supportops/supportops-page";
import { I18nProvider } from "@/core/i18n/context";
import type { SupportAction } from "@/core/supportops/api";

const pending: SupportAction = {
  action_id: "action-1",
  order_id: "ORD-1001",
  reason: "物流一直没动",
  status: "pending_approval",
  revision: 2,
  created_at: "2026-11-24T08:00:00Z",
  ticket_id: null,
  ticket_created_at: null,
};

function renderPage() {
  return render(
    <I18nProvider initialLocale="en-US">
      <SupportOpsPage />
    </I18nProvider>,
  );
}

afterEach(() => {
  cleanup();
  mocks.list.mockReset();
  mocks.revise.mockReset();
  mocks.decide.mockReset();
  mocks.execute.mockReset();
});

describe("SupportOpsPage", () => {
  it("approves the exact displayed revision and then creates its ticket", async () => {
    const approved = { ...pending, status: "approved" as const };
    const succeeded = {
      ...approved,
      status: "succeeded" as const,
      ticket_id: "ticket-1",
      ticket_created_at: "2026-11-24T08:05:00Z",
    };
    mocks.list
      .mockResolvedValueOnce([pending])
      .mockResolvedValueOnce([approved])
      .mockResolvedValueOnce([succeeded]);
    mocks.decide.mockResolvedValue(approved);
    mocks.execute.mockResolvedValue({ ticket_id: "ticket-1" });

    renderPage();
    expect((await screen.findAllByText("物流一直没动")).length).toBeGreaterThan(
      0,
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve request" }));
    await screen.findByText("Request approved.");
    expect(mocks.decide).toHaveBeenCalledWith(pending, "approve");

    fireEvent.click(
      screen.getByRole("button", { name: "Execute and create ticket" }),
    );
    await screen.findByText("Ticket created.");
    expect(mocks.execute).toHaveBeenCalledWith(approved);
    expect(await screen.findByText("ticket-1")).toBeTruthy();
  });

  it("edits the reason through the revision flow and keeps approval pending", async () => {
    const revised = {
      ...pending,
      reason: "商品损坏",
      status: "pending_approval" as const,
      revision: 3,
    };
    mocks.list
      .mockResolvedValueOnce([pending])
      .mockResolvedValueOnce([revised]);
    mocks.revise.mockResolvedValue(revised);

    renderPage();
    expect((await screen.findAllByText("物流一直没动")).length).toBeGreaterThan(
      0,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit reason" }));
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "商品损坏" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save and request approval again" }),
    );

    await screen.findByText(
      "Reason updated. The request is pending approval again.",
    );
    await waitFor(() =>
      expect(mocks.revise).toHaveBeenCalledWith(pending, "商品损坏"),
    );
    expect((await screen.findAllByText("商品损坏")).length).toBeGreaterThan(0);
    expect(screen.getByText("Revision 3")).toBeTruthy();
  });

  it("offers chat registration instead of creating a draft outside the Agent flow", async () => {
    mocks.list.mockResolvedValue([]);
    renderPage();
    const link = await screen.findByRole("link", {
      name: "Create a request in chat",
    });
    expect(link.getAttribute("href")).toBe("/workspace/chats/new");
  });
});
