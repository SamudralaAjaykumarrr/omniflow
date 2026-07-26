import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DataTable } from "./DataTable";

interface Row {
  id: string;
  name: string;
}

const rows: Row[] = [
  { id: "1", name: "Alpha" },
  { id: "2", name: "Beta" },
];

const columns = [{ key: "name", header: "Name", render: (row: Row) => row.name }];

describe("DataTable", () => {
  it("renders a caption, headers, and every row", () => {
    render(<DataTable caption="My rows" columns={columns} rows={rows} getRowKey={(r) => r.id} />);
    expect(screen.getByText("My rows")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("calls onRowActivate on click when interactive", async () => {
    const onRowActivate = vi.fn();
    render(
      <DataTable
        caption="My rows"
        columns={columns}
        rows={rows}
        getRowKey={(r) => r.id}
        onRowActivate={onRowActivate}
      />,
    );
    await userEvent.click(screen.getByText("Alpha"));
    expect(onRowActivate).toHaveBeenCalledWith(rows[0]);
  });

  it("calls onRowActivate on Enter key for keyboard users", async () => {
    const onRowActivate = vi.fn();
    render(
      <DataTable
        caption="My rows"
        columns={columns}
        rows={rows}
        getRowKey={(r) => r.id}
        onRowActivate={onRowActivate}
      />,
    );
    const row = screen.getAllByRole("button")[1];
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(onRowActivate).toHaveBeenCalledWith(rows[1]);
  });

  it("rows are not keyboard-focusable when onRowActivate is not supplied", () => {
    render(<DataTable caption="My rows" columns={columns} rows={rows} getRowKey={(r) => r.id} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
