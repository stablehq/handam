import * as React from "react"

import { cn } from "@/lib/utils"

/* ── Table ── */

interface TableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  hoverable?: boolean
  striped?: boolean
}

const Table = React.forwardRef<HTMLTableElement, TableProps>(
  ({ className, hoverable, striped, ...props }, ref) => {
    return (
      <div className="overflow-x-auto">
        <table
          ref={ref}
          className={cn("w-full text-left text-body text-[#4E5968] dark:text-gray-400", className)}
          data-hoverable={hoverable || undefined}
          data-striped={striped || undefined}
          {...props}
        />
      </div>
    )
  }
)
Table.displayName = "Table"

/* ── TableHead ── */

const TableHead = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead
    ref={ref}
    className={cn("text-caption uppercase text-[#8B95A1] dark:text-gray-500", className)}
    {...props}
  />
))
TableHead.displayName = "TableHead"

/* ── TableBody ── */

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("", className)} {...props} />
))
TableBody.displayName = "TableBody"

/* ── TableRow ── */

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b border-[#F2F4F6] dark:border-gray-800 min-h-[44px]",
      "hover:bg-[#F2F4F6] dark:hover:bg-[#1E1E24]",
      className,
    )}
    {...props}
  />
))
TableRow.displayName = "TableRow"

/* ── TableHeadCell ── */

const TableHeadCell = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      "bg-[#F8F9FA] px-3 py-2.5 sm:px-5 sm:py-3 font-medium whitespace-nowrap dark:bg-[#1E1E24]",
      className,
    )}
    {...props}
  />
))
TableHeadCell.displayName = "TableHeadCell"

/* ── TableCell ── */

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn("px-3 py-2.5 sm:px-5 sm:py-3.5 text-body whitespace-nowrap bg-white dark:bg-[#1E1E24]", className)}
    {...props}
  />
))
TableCell.displayName = "TableCell"

export { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell }
