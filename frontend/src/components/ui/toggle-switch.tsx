import * as React from "react"

import { cn } from "@/lib/utils"

interface ToggleSwitchProps {
  id?: string
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
  disabled?: boolean
  className?: string
}

function ToggleSwitch({ id, checked, onChange, label, disabled, className }: ToggleSwitchProps) {
  return (
    <label
      htmlFor={id}
      className={cn(
        "inline-flex cursor-pointer items-center gap-3",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
    >
      <div className="relative">
        <input
          id={id}
          type="checkbox"
          className="peer sr-only"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          disabled={disabled}
        />
        <div
          className={cn(
            "h-6 w-11 min-w-11 rounded-full border transition-colors",
            "after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all",
            checked
              ? "border-[#3182F6] bg-[#3182F6] after:translate-x-full"
              : "border-gray-200 bg-gray-200 dark:border-gray-600 dark:bg-gray-600",
          )}
        />
      </div>
      {label && (
        <span className="text-body font-medium text-[#191F28] dark:text-gray-300">
          {label}
        </span>
      )}
    </label>
  )
}

export { ToggleSwitch }
