export default function NewChatButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90
                 text-white text-sm font-medium rounded-lg py-2.5 transition-colors"
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <path d="M12 5v14M5 12h14" strokeLinecap="round" />
      </svg>
      New chat
    </button>
  )
}
