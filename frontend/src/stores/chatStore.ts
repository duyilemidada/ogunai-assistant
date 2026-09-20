import { create } from 'zustand'
import type { Message, ActivityEvent } from '../api/types'

// The conversation LIST is no longer stored here — that's now owned by
// useConversations() (TanStack Query) so the sidebar always reflects what
// the backend actually has. This store only holds per-session message
// caches and transient UI/streaming state.
interface ChatState {
  activeConversationId: number | null
  messagesByConversation: Record<number, Message[]>
  draftMessages: Message[] // messages typed before a conversation_id exists yet
  isSending: boolean
  isStreaming: boolean
  activityEvents: ActivityEvent[]

  currentMessages: () => Message[]
  startNewChat: () => void
  selectConversation: (id: number) => void
  addUserMessage: (content: string) => void
  resolveConversation: (conversationId: number) => void
  addAgentMessage: (conversationId: number, message: Message) => void
  hydrateConversation: (conversationId: number, messages: Message[]) => void
  isHydrated: (conversationId: number) => boolean
  setSending: (val: boolean) => void
  setStreaming: (val: boolean) => void
  addActivityEvent: (event: ActivityEvent) => void
  clearActivity: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  activeConversationId: null,
  messagesByConversation: {},
  draftMessages: [],
  isSending: false,
  isStreaming: false,
  activityEvents: [],

  currentMessages: () => {
    const { activeConversationId, messagesByConversation, draftMessages } =
      get()
    if (activeConversationId === null) return draftMessages
    return messagesByConversation[activeConversationId] || []
  },

  startNewChat: () =>
    set({ activeConversationId: null, draftMessages: [], activityEvents: [] }),

  selectConversation: (id) =>
    set({ activeConversationId: id, activityEvents: [] }),

  addUserMessage: (content) => {
    const { activeConversationId } = get()
    const message: Message = { role: 'user', content }
    if (activeConversationId === null) {
      set((s) => ({ draftMessages: [...s.draftMessages, message] }))
    } else {
      set((s) => ({
        messagesByConversation: {
          ...s.messagesByConversation,
          [activeConversationId]: [
            ...(s.messagesByConversation[activeConversationId] || []),
            message,
          ],
        },
      }))
    }
  },

  resolveConversation: (conversationId) => {
    set((s) => ({
      messagesByConversation: {
        ...s.messagesByConversation,
        [conversationId]: [...s.draftMessages],
      },
      draftMessages: [],
      activeConversationId: conversationId,
    }))
  },

  addAgentMessage: (conversationId, message) => {
    set((s) => ({
      messagesByConversation: {
        ...s.messagesByConversation,
        [conversationId]: [
          ...(s.messagesByConversation[conversationId] || []),
          message,
        ],
      },
    }))
  },

  hydrateConversation: (conversationId, messages) => {
    set((s) => ({
      messagesByConversation: {
        ...s.messagesByConversation,
        [conversationId]: messages,
      },
    }))
  },

  isHydrated: (conversationId) =>
    get().messagesByConversation[conversationId] !== undefined,

  setSending: (val) => set({ isSending: val }),
  setStreaming: (val) => set({ isStreaming: val }),

  addActivityEvent: (event) =>
    set((s) => ({ activityEvents: [...s.activityEvents, event] })),
  clearActivity: () => set({ activityEvents: [] }),
}))
