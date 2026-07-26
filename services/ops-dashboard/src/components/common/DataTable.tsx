import type { KeyboardEvent, ReactNode } from "react";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  numeric?: boolean;
}

interface DataTableProps<T> {
  caption: string;
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowKey: (row: T) => string;
  onRowActivate?: (row: T) => void;
}

/** Accessible generic table: real <caption>/<th scope>, and (when
 * `onRowActivate` is supplied) keyboard-activatable rows — Enter/Space
 * behave the same as a click, not mouse-only. */
export function DataTable<T>({
  caption,
  columns,
  rows,
  getRowKey,
  onRowActivate,
}: DataTableProps<T>) {
  const interactive = Boolean(onRowActivate);

  function handleKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: T) {
    if (!onRowActivate) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onRowActivate(row);
    }
  }

  return (
    <table className="data-table">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          {columns.map((col) => (
            <th
              key={col.key}
              scope="col"
              className={col.numeric ? "data-table__cell--numeric" : undefined}
            >
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={getRowKey(row)}
            tabIndex={interactive ? 0 : undefined}
            role={interactive ? "button" : undefined}
            className={interactive ? "data-table__row--interactive" : undefined}
            onClick={interactive ? () => onRowActivate?.(row) : undefined}
            onKeyDown={interactive ? (e) => handleKeyDown(e, row) : undefined}
          >
            {columns.map((col) => (
              <td key={col.key} className={col.numeric ? "data-table__cell--numeric" : undefined}>
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
