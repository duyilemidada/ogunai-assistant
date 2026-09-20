import { useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useChatStore } from '../stores/chatStore'
import { useUiStore } from '../stores/uiStore'
import { useAuthStore } from '../stores/authStore'
import { API_BASE_URL } from '../api/client'
import type { ActivityEvent } from '../api/types'

export function useStreamingChat() {
  const {
    activeConversationId,
    addUserMessage,
    resolveConversation,
    addAgentMessage,
    addActivityEvent,
    clearActivity,
    setStreaming,
    currentMessages,
  } = useChatStore()
  const { openActivity, closeActivity } = useUiStore()
  const token = useAuthStore((s) => s.token)
  const queryClient = useQueryClient()

  const controllerRef = useRef<AbortController | null>(null)

  const send = async (text: string) => {
    const wasNewConversation = activeConversationId === null
    const conversationIdAtSendTime = activeConversationId

    addUserMessage(text)
    clearActivity()
    setStreaming(true)
    openActivity()

    const controller = new AbortController()
    controllerRef.current = controller

    try {
      await fetchEventSource(`${API_BASE_URL}/api/v1/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationIdAtSendTime,
        }),
        signal: controller.signal,
        openWhenHidden: true,

        onmessage(ev) {
          if (ev.data === '[DONE]') return
          let event: any
          try {
            event = JSON.parse(ev.data)
          } catch {
            return
          }

          switch (event.type) {
            case 'thinking':
            case 'tool_call':
            case 'tool_result':
            case 'specialist_start':
            case 'specialist_done':
            case 'agent_done': {
              const activityEvent: ActivityEvent = {
                ...event,
                id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
                timestamp: Date.now(),
              }
              addActivityEvent(activityEvent)
              break
            }

            case 'saved': {
              if (wasNewConversation) {
                resolveConversation(event.conversation_id)
                // Brand-new conversation now exists on the backend with a real
                // title — refetch the sidebar list rather than guessing the
                // title client-side, so it always matches what's persisted.
                queryClient.invalidateQueries({ queryKey: ['conversations'] })
              }
              addAgentMessage(event.conversation_id, {
                id: event.message_id,
                role: 'supervisor',
                content: event.content,
              })
              break
            }

            case 'error': {
              addActivityEvent({
                type: 'error',
                id: `${Date.now()}-err`,
                timestamp: Date.now(),
                message: event.message,
              })
              break
            }
          }
        },

        onerror(err) {
          addActivityEvent({
            type: 'error',
            id: `${Date.now()}-conn-err`,
            timestamp: Date.now(),
            message: 'Connection lost while streaming. Please try again.',
          })
          throw err
        },
      })
    } catch {
      // onerror already recorded a visible error card — swallow to avoid
      // an unhandled rejection from the rethrow above.
    } finally {
      setStreaming(false)
      setTimeout(() => closeActivity(), 900)
      controllerRef.current = null
    }
  }

  const cancel = () => controllerRef.current?.abort()

  return { send, cancel, messages: currentMessages() }
}
