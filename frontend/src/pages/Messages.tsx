import { useEffect, useState, useRef, useCallback } from 'react'
import { toast } from 'sonner'
import {
  RefreshCw,
  Send,
  MessageSquareText,
} from 'lucide-react'

import { Avatar, Badge, Button, Spinner, TextInput, Textarea } from 'flowbite-react'

import { messagesAPI } from '@/services/api'
import { formatRelativeTime, formatTime } from '@/lib/utils'

const OUR_NUMBER = '010-9999-0000'

const QUICK_MESSAGES = [
  { label: '영업시간', text: '영업시간이 어떻게 되나요?' },
  { label: '예약문의', text: '예약하고 싶습니다' },
  { label: '가격문의', text: '가격이 어떻게 되나요?' },
  { label: '주차안내', text: '주차 가능한가요?' },
  { label: '취소문의', text: '예약 취소하고 싶습니다' },
]

interface Contact {
  phone: string
  last_message: string
  last_message_time: string
  last_direction: string
  customer_name: string | null
}

interface MessageItem {
  id: number
  message_id: string
  direction: string
  from_: string
  to: string
  message: string
  status: string
  created_at: string
  auto_response: string | null
  auto_response_confidence: number | null
  needs_review: boolean
  response_source: string | null
}

function SourceBadge({ source }: { source: string | null }) {
  if (!source) return null
  const config: Record<string, { label: string }> = {
    rule:   { label: '규칙' },
    llm:    { label: 'AI' },
    manual: { label: '수동' },
  }
  const cfg = config[source]
  if (!cfg) return null
  return <Badge color="gray" size="xs">{cfg.label}</Badge>
}

function MessageBubble({ msg }: { msg: MessageItem }) {
  const isOutbound = msg.direction === 'outbound'

  return (
    <div className={`flex flex-col gap-1 ${isOutbound ? 'items-end' : 'items-start'}`}>
      <div className={isOutbound ? 'outbound-bubble' : 'inbound-bubble'}>
        {msg.message}
      </div>

      <div className={`flex items-center gap-1.5 ${isOutbound ? 'flex-row-reverse' : 'flex-row'}`}>
        <span className="text-tiny text-[#B0B8C1] dark:text-gray-600">
          {formatTime(msg.created_at)}
        </span>
        {msg.response_source && <SourceBadge source={msg.response_source} />}
        {msg.auto_response_confidence !== null && (
          <span className="text-tiny tabular-nums text-[#B0B8C1] dark:text-gray-600">
            {Math.round(msg.auto_response_confidence * 100)}%
          </span>
        )}
        {msg.needs_review && (
          <Badge color="warning" size="xs">검토 필요</Badge>
        )}
      </div>
    </div>
  )
}

function ContactItem({
  contact,
  isActive,
  onClick,
}: {
  contact: Contact
  isActive: boolean
  onClick: () => void
}) {
  const displayName = contact.customer_name ?? contact.phone
  const initials = contact.customer_name
    ? contact.customer_name.charAt(0)
    : undefined

  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-[#F2F4F6] dark:hover:bg-[#1E1E24] ${
        isActive ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/10' : ''
      }`}
    >
      <Avatar placeholderInitials={initials} rounded size="sm" />

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-body font-medium text-[#191F28] dark:text-white">
            {displayName}
          </span>
          <span className="shrink-0 text-tiny text-[#B0B8C1] dark:text-gray-600">
            {formatRelativeTime(contact.last_message_time)}
          </span>
        </div>
        <p className="mt-0.5 truncate text-caption text-[#8B95A1] dark:text-gray-500">
          {contact.last_direction === 'outbound' ? '↗ ' : '↙ '}
          {contact.last_message}
        </p>
      </div>
    </button>
  )
}

const Messages = () => {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null)
  const [messages, setMessages] = useState<MessageItem[]>([])
  const [inputText, setInputText] = useState('')
  const [loadingContacts, setLoadingContacts] = useState(false)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [sending, setSending] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const fetchContacts = useCallback(async () => {
    setLoadingContacts(true)
    try {
      const res = await messagesAPI.getContacts()
      setContacts(res.data)
    } catch {
      toast.error('연락처를 불러오지 못했습니다.')
    } finally {
      setLoadingContacts(false)
    }
  }, [])

  useEffect(() => {
    fetchContacts()
  }, [fetchContacts])

  const filteredContacts = searchQuery
    ? contacts.filter(
        (c) =>
          c.phone.includes(searchQuery) ||
          (c.customer_name ?? '').includes(searchQuery) ||
          c.last_message.includes(searchQuery),
      )
    : contacts

  const fetchMessages = useCallback(async (phone: string) => {
    setLoadingMessages(true)
    try {
      const res = await messagesAPI.getAll({ phone, limit: 200 })
      const data: MessageItem[] = res.data
      data.sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      )
      setMessages(data)
    } catch {
      toast.error('메시지를 불러오지 못했습니다.')
    } finally {
      setLoadingMessages(false)
    }
  }, [])

  useEffect(() => {
    if (selectedContact) {
      fetchMessages(selectedContact.phone)
    } else {
      setMessages([])
    }
  }, [selectedContact, fetchMessages])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = useCallback(async () => {
    const text = inputText.trim()
    if (!text || !selectedContact || sending) return

    setSending(true)
    try {
      await messagesAPI.simulateReceive({
        from_: selectedContact.phone,
        to: OUR_NUMBER,
        message: text,
      })
      setInputText('')
      setTimeout(() => {
        fetchMessages(selectedContact.phone)
        fetchContacts()
      }, 800)
    } catch {
      toast.error('메시지 전송에 실패했습니다.')
    } finally {
      setSending(false)
    }
  }, [inputText, selectedContact, sending, fetchMessages, fetchContacts])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const handleQuickMessage = (text: string) => {
    setInputText(text)
    textareaRef.current?.focus()
  }

  return (
    <div className="section-card flex h-[calc(100vh-7rem)] overflow-hidden">

      {/* Left Panel: Contact List */}
      <div className="flex w-72 shrink-0 flex-col overflow-hidden border-r border-[#F2F4F6] dark:border-gray-800 lg:w-80">

        <div className="flex items-center justify-between px-4 py-3">
          <h2 className="text-body font-semibold text-[#191F28] dark:text-white">대화</h2>
          <Button
            color="light"
            size="xs"
            pill
            onClick={fetchContacts}
            disabled={loadingContacts}
          >
            {loadingContacts ? (
              <Spinner size="xs" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>

        <div className="border-b border-[#F2F4F6] px-3 py-2 dark:border-gray-800">
          <TextInput
            sizing="sm"
            placeholder="이름 또는 번호 검색"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="scrollbar-thin flex-1 overflow-auto p-1">
          {filteredContacts.length === 0 ? (
            <div className="empty-state py-12">
              <Avatar rounded size="lg" />
              <p className="text-caption">
                {searchQuery ? '검색 결과가 없습니다' : '연락처가 없습니다'}
              </p>
            </div>
          ) : (
            <div className="space-y-0.5">
              {filteredContacts.map((contact) => (
                <ContactItem
                  key={contact.phone}
                  contact={contact}
                  isActive={selectedContact?.phone === contact.phone}
                  onClick={() => setSelectedContact(contact)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right Panel: Chat */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {!selectedContact ? (
          <div className="empty-state flex-1">
            <div className="rounded-2xl bg-[#F2F4F6] p-6 dark:bg-[#1E1E24]">
              <MessageSquareText size={32} className="text-[#B0B8C1] dark:text-gray-600" />
            </div>
            <p className="text-body text-[#B0B8C1] dark:text-gray-600">
              왼쪽에서 대화를 선택하세요
            </p>
          </div>
        ) : (
          <>
            {/* Chat header */}
            <div className="flex items-center justify-between border-b border-[#F2F4F6] px-5 py-3 dark:border-gray-800">
              <div className="flex items-center gap-3">
                <Avatar
                  placeholderInitials={
                    selectedContact.customer_name
                      ? selectedContact.customer_name.charAt(0)
                      : undefined
                  }
                  rounded
                  size="sm"
                />
                <div>
                  <p className="text-body font-semibold text-[#191F28] dark:text-white">
                    {selectedContact.customer_name ?? selectedContact.phone}
                  </p>
                  {selectedContact.customer_name && (
                    <p className="text-caption text-[#B0B8C1] dark:text-gray-600">
                      {selectedContact.phone}
                    </p>
                  )}
                </div>
              </div>

              <Button
                color="light"
                size="xs"
                pill
                onClick={() => fetchMessages(selectedContact.phone)}
                disabled={loadingMessages}
              >
                {loadingMessages ? (
                  <Spinner size="xs" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>

            {/* Messages area */}
            <div className="scrollbar-thin flex-1 overflow-auto bg-[#F8F9FA] px-5 py-4 dark:bg-[#17171C]">
              {loadingMessages ? (
                <div className="flex items-center justify-center py-16">
                  <Spinner size="md" />
                </div>
              ) : messages.length === 0 ? (
                <div className="empty-state py-12">
                  <p className="text-caption">대화 내역이 없습니다</p>
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  {messages.map((msg) => (
                    <MessageBubble key={msg.id} msg={msg} />
                  ))}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>

            {/* Input area */}
            <div className="border-t border-[#F2F4F6] bg-white px-4 py-3 dark:border-gray-800 dark:bg-[#1E1E24]">
              <div className="mb-2 flex flex-wrap gap-1.5">
                {QUICK_MESSAGES.map((qm) => (
                  <Button
                    key={qm.label}
                    color="light"
                    size="xs"
                    pill
                    onClick={() => handleQuickMessage(qm.text)}
                    disabled={sending}
                  >
                    {qm.label}
                  </Button>
                ))}
              </div>

              <div className="flex items-end gap-2">
                <Textarea
                  ref={textareaRef}
                  className="flex-1"
                  placeholder="메시지를 입력하세요… (Enter 전송, Shift+Enter 줄바꿈)"
                  rows={2}
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={sending}
                />
                <Button
                  color="blue"
                  pill
                  onClick={handleSend}
                  disabled={!inputText.trim() || sending}
                >
                  {sending ? (
                    <Spinner size="sm" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default Messages
