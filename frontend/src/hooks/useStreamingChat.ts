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
  // The backend now sends {type:'started', conversation_id} as the first event,
  // so Stop works even in a brand-new chat that has no id yet on the frontend.
  const conversationIdRef = useRef<number | null>(null)

  const send = async (text: string) => {
    const wasNewConversation = activeConversationId === null
    const conversationIdAtSendTime = activeConversationId

    addUserMessage(text)
    clearActivity()
    setStreaming(true)
    openActivity()

    const controller = new AbortController()
    controllerRef.current = controller
    conversationIdRef.current = conversationIdAtSendTime

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
            case 'started': {
              conversationIdRef.current = event.conversation_id
              break
            }

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
      if (controllerRef.current === controller) controllerRef.current = null
    }
  }

  const cancel = async () => {
    const controller = controllerRef.current
    if (!controller) return

    const conversationId = conversationIdRef.current
    if (conversationId === null) {
      controller.abort() // id not known yet: closing the stream still stops the agent
      return
    }

    // Ask the server to stop. The stream then ends by itself and delivers the
    // "Stopped" message, so the chat shows what happened.
    try {
      await fetch(`${API_BASE_URL}/api/v1/chat/cancel`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ conversation_id: conversationId }),
      })
    } catch {
      controller.abort()
      return
    }

    // Safety net: if the stream is still open after 8s, close it. The server
    // also stops the agent when the connection closes.
    setTimeout(() => {
      if (controllerRef.current === controller) controller.abort()
    }, 8000)
  }

  return { send, cancel, messages: currentMessages() }
}
