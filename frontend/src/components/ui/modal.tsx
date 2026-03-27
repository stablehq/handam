import * as React from "react"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"

/* ── Modal Root ── */

const sizeClasses: Record<string, string> = {
  fit: "w-fit",
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
  "2xl": "max-w-2xl",
  "3xl": "max-w-3xl",
  "4xl": "max-w-4xl",
  "5xl": "max-w-5xl",
}

interface ModalProps {
  show: boolean
  onClose: () => void
  size?: string
  popup?: boolean
  children: React.ReactNode
  className?: string
}

function Modal({ show, onClose, size = "md", popup, children, className }: ModalProps) {
  // Close on Escape
  React.useEffect(() => {
    if (!show) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [show, onClose])

  // Prevent body scroll
  React.useEffect(() => {
    if (show) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => {
      document.body.style.overflow = ""
    }
  }, [show])

  if (!show) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 p-2 sm:p-4 dark:bg-gray-900/80"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className={cn(
          "relative mx-auto flex max-h-[90dvh] w-full flex-col rounded-xl sm:rounded-2xl bg-white shadow-2xl dark:bg-[#1E1E24]",
          sizeClasses[size] || sizeClasses.md,
          className,
        )}
        data-popup={popup || undefined}
      >
        {children}
      </div>
    </div>
  )
}

/* ── ModalHeader ── */

interface ModalHeaderProps {
  children?: React.ReactNode
  className?: string
  onClose?: () => void
}

function ModalHeader({ children, className }: ModalHeaderProps) {
  // Find parent Modal's onClose from context-like pattern
  // We pass onClose via the close button click on the parent
  return (
    <div
      className={cn(
        "flex items-center justify-between rounded-t-xl sm:rounded-t-2xl border-b border-[#F2F4F6] px-5 py-4 dark:border-gray-800",
        !children && "border-b-0 p-2",
        className,
      )}
    >
      {children && (
        <h3 className="text-heading font-semibold text-[#191F28] dark:text-white">
          {children}
        </h3>
      )}
    </div>
  )
}

/* ── ModalBody ── */

interface ModalBodyProps {
  children: React.ReactNode
  className?: string
}

function ModalBody({ children, className }: ModalBodyProps) {
  return (
    <div className={cn("flex-1 overflow-y-auto px-5 py-4", className)}>
      {children}
    </div>
  )
}

/* ── ModalFooter ── */

interface ModalFooterProps {
  children: React.ReactNode
  className?: string
}

function ModalFooter({ children, className }: ModalFooterProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2 rounded-b-xl sm:rounded-b-2xl border-t border-[#F2F4F6] px-5 py-4 dark:border-gray-800",
        className,
      )}
    >
      {children}
    </div>
  )
}

export { Modal, ModalHeader, ModalBody, ModalFooter }
