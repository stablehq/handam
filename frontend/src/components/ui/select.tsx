import * as React from "react"

import { cn } from "@/lib/utils"

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  sizing?: "sm" | "md"
}

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, sizing = "md", children, ...props }, ref) => {
    const sizeClasses = sizing === "sm" ? "p-2 text-body" : "p-2.5 text-body"

    return (
      <select
        ref={ref}
        className={cn(
          "block w-full rounded-lg border border-[#E5E8EB] bg-white text-[#191F28] outline-none transition-colors",
          "focus:border-[#3182F6] focus:ring-1 focus:ring-[#3182F6]",
          "dark:border-gray-600 dark:bg-[#1E1E24] dark:text-gray-100",
          "dark:focus:border-[#3182F6] dark:focus:ring-[#3182F6]",
          sizeClasses,
          "select-arrow pr-9",
          className,
        )}
        {...props}
      >
        {children}
      </select>
    )
  }
)
Select.displayName = "Select"

export { Select }
