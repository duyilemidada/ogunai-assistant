export default function NewChatButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="brand-gradient flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-semibold text-on-primary shadow-soft transition hover:brightness-110 active:scale-[0.98]"
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
      >
        <path d="M12 5v14M5 12h14" strokeLinecap="round" />
      </svg>
      New chat
    </button>
  )
}
