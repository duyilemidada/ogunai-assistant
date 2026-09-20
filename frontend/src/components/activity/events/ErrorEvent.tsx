export default function ErrorEvent({ message }: { message: string }) {
  return (
    <div className="mx-2 mb-1 px-3 py-2 bg-error/10 border border-error/30 rounded-lg">
      <p className="text-xs text-error">{message}</p>
    </div>
  )
}
